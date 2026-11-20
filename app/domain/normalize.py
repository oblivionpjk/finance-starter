"""归一化：任意上传表格 / 数据源宽表 → 统一 Dataset；Dataset → 现有引擎视图。

支持两种常见布局（自动探测）：
- by_date：首列为「报告日」，每行一个报告期、每列一个科目（新浪/演示数据口径）；
- by_item：首列为「项目」，每行一个科目、每列一个期间（企业 ERP 导出口径）。

所有金额统一换算为「元」存入 facts，unit_raw 保留原单位供审计。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app import config
from app.domain import dictionary as dic
from app.domain.model import Dataset, QualityIssue, StatementFact

DATE_COL_WORDS = ("报告日", "报告日期", "报表日期", "日期", "报告期", "会计期间")
ITEM_COL_WORDS = ("项目", "科目", "科目名称", "项目名称", "指标")


@dataclass
class ParsedTable:
    name: str                       # 原始文件名 + sheet 标识
    df: pd.DataFrame
    layout: str                     # by_date / by_item / unknown
    sheet: str
    raw_labels: list[str] = field(default_factory=list)
    period_labels: list[str] = field(default_factory=list)
    role_guess: str = "BS"


def _to_float(value: Any) -> float | None:
    """把单元格转为数值；空值/文本/千分位/括号负数统一处理，失败返回 None。"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return None if math.isnan(float(value)) else float(value)
    s = str(value).strip().replace(",", "").replace("，", "")
    if s in ("", "-", "--", "—", "N/A", "nan", "None"):
        return None
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_period_label(raw: object) -> tuple[str, str] | None:
    """解析期间标签 → (period_end, period_type)。只保留可跨期比较的年度/中期口径。"""
    s = str(raw).strip()
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    # pandas 把纯数值行提升为 float 时，20221231 会变成 "20221231.0"；
    # 日期时间戳也会带时分秒。前 4 位是合理年份时统一截取到 8 位日期。
    if len(digits) > 8 and digits[:4].isdigit() and 1900 <= int(digits[:4]) <= 2100:
        digits = digits[:8]
    if len(digits) == 8:
        y, m, d = digits[:4], digits[4:6], digits[6:]
    elif len(digits) == 6:
        y, m, d = digits[:4], digits[4:6], "31"
    elif len(digits) == 4:
        y, m, d = digits, "12", "31"
    else:
        return None
    if not (1900 <= int(y) <= 2100 and 1 <= int(m) <= 12):
        return None
    end = f"{y}-{m}-{d}"
    if (m, d) == ("12", "31"):
        return end, "FY"
    return end, {"03": "Q1", "06": "H1", "09": "Q3"}.get(m, "OTHER")


def detect_layout(df: pd.DataFrame) -> str:
    """按首列名 + 首列取值形态判断表格布局。"""
    if df.empty or df.shape[1] < 2:
        return "unknown"
    first = dic.normalize_label(df.columns[0])
    if any(w in first for w in DATE_COL_WORDS):
        return "by_date"
    if any(first == w or w in first for w in ITEM_COL_WORDS):
        return "by_item"
    sample = [str(x) for x in df.iloc[:, 0].head(8).tolist()]
    date_like = sum(1 for x in sample if parse_period_label(x) is not None)
    if date_like >= max(1, len(sample) // 2):
        return "by_date"
    col_dates = sum(1 for c in df.columns[1:] if parse_period_label(c) is not None)
    if col_dates >= max(1, (df.shape[1] - 1) // 2):
        return "by_item"
    return "unknown"


def inspect(df: pd.DataFrame, name: str, sheet: str = "") -> ParsedTable:
    layout = detect_layout(df)
    if layout == "by_date":
        labels = [str(c) for c in df.columns[1:]]
        periods = [str(x) for x in df.iloc[:, 0].tolist()]
    elif layout == "by_item":
        labels = [str(x) for x in df.iloc[:, 0].tolist()]
        periods = [str(c) for c in df.columns[1:]]
    else:
        labels, periods = [], []
    return ParsedTable(
        name=name, df=df, layout=layout, sheet=sheet,
        raw_labels=labels, period_labels=periods,
        role_guess=dic.guess_role(labels),
    )


def build_dataset(
    tables: list[ParsedTable],
    *,
    origin: str,
    subject: str,
    source_ref: str,
    dataset_id: str,
    unit: str = config.DEFAULT_UPLOAD_UNIT,
    currency: str = "CNY",
    statement_scope: str = "consolidated",
    roles: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
    company_name: str = "",
    name_source: str = "",
) -> Dataset:
    """把解析后的表格转成 Dataset。roles/overrides 来自映射确认页。"""
    if unit not in config.AMOUNT_UNITS:
        raise ValueError(f"不支持的金额单位：{unit}")
    scale = config.AMOUNT_UNITS[unit]
    roles = roles or {}
    overrides = {dic.normalize_label(k): v for k, v in (overrides or {}).items() if v}
    facts: list[StatementFact] = []
    audit: list[dict[str, Any]] = []
    quality: list[QualityIssue] = []
    skipped_periods: set[str] = set()

    def resolve(raw: object) -> tuple[str | None, float, str]:
        norm = dic.normalize_label(raw)
        if norm in overrides and overrides[norm] in dic.BY_KEY:
            return overrides[norm], 1.0, "override"
        key, conf, matched = dic.map_label(raw)
        return key, conf, matched

    for t in tables:
        statement = roles.get(t.name, t.role_guess)
        if statement not in ("BS", "IS", "CF"):
            statement = t.role_guess
        if t.layout == "by_date":
            # 用 iloc 取标量，避免 iterrows() 把纯数值行整体提升为 float
            pairs: list[tuple[str, str, str, Any]] = []
            cols = list(t.df.columns[1:])
            for i in range(len(t.df)):
                parsed = parse_period_label(t.df.iloc[i, 0])
                if parsed is None:
                    continue
                period_end, ptype = parsed
                if ptype != "FY":
                    skipped_periods.add(f"{period_end}({ptype})")
                    continue
                for j, col in enumerate(cols, start=1):
                    pairs.append((period_end, ptype, str(col), t.df.iloc[i, j]))
        elif t.layout == "by_item":
            col_periods = [(c, parse_period_label(c)) for c in t.df.columns[1:]]
            pairs = []
            for i in range(len(t.df)):
                raw_label = str(t.df.iloc[i, 0])
                for j, (col, parsed) in enumerate(col_periods, start=1):
                    if parsed is None:
                        continue
                    period_end, ptype = parsed
                    if ptype != "FY":
                        skipped_periods.add(f"{period_end}({ptype})")
                        continue
                    pairs.append((period_end, ptype, raw_label, t.df.iloc[i, j]))
        else:
            quality.append(QualityIssue("warn", "LAYOUT_UNKNOWN",
                                        f"{t.name} 的表格布局无法识别，已跳过",
                                        "请使用首列为「报告日」或「项目」的表格"))
            continue

        for period_end, ptype, raw_label, cell in pairs:
            key, conf, matched = resolve(raw_label)
            if matched == "meta":
                continue
            if key is None:
                if dic.is_important_label(raw_label):
                    audit.append({"raw": raw_label, "item_key": None,
                                  "confidence": 0.0, "action": "unmapped",
                                  "suggestions": dic.suggest(raw_label)})
                continue
            value = _to_float(cell)
            facts.append(StatementFact(
                period_end=period_end, period_type=ptype, statement=statement,
                item_key=key, item_label_raw=raw_label,
                value=None if value is None else value * scale,
                unit_raw=unit, currency=currency,
                mapping_confidence=conf,
                source_ref=f"{t.name}#{period_end}",
                is_restated=False,
            ))
            audit.append({"raw": raw_label, "item_key": key,
                          "label": dic.BY_KEY[key].label,
                          "confidence": conf, "action": "override" if matched == "override" else "auto"})

    if skipped_periods:
        quality.append(QualityIssue(
            "info", "NON_ANNUAL_SKIPPED",
            "存在非年度报告期，为保证跨期可比已排除",
            "、".join(sorted(skipped_periods)[:8]),
        ))
    unmapped = [a["raw"] for a in audit if a["action"] == "unmapped"]
    if unmapped:
        # 财报科目远多于分析所需，未纳入词典属正常；核心科目缺失由校验网关单独给 warn。
        quality.append(QualityIssue(
            "info", "UNMAPPED_ITEMS",
            f"有 {len(set(unmapped))} 个科目未纳入标准科目词典，不影响本次指标计算",
            "、".join(sorted(set(unmapped))[:12]),
        ))
    return Dataset(
        dataset_id=dataset_id, origin=origin, subject=subject,
        source_ref=source_ref, statement_scope=statement_scope,
        currency=currency, facts=facts, quality=quality,
        created_at=config.now_str(), mapping_audit=audit,
        company_name=company_name, name_source=name_source,
    )


def to_legacy_frames(dataset: Dataset) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """转成 src/ratios.py 期望的「科目 × 年份(int)」三张表（单位：元）。

    这是复用现有 26 项指标与杜邦分解的适配层：ratios.py 一行都不用改。
    缺失科目补 NaN，不伪造数据。
    """
    years = sorted({int(p[:4]) for p in dataset.periods()})
    out: dict[str, pd.DataFrame] = {}
    for st in ("IS", "BS", "CF"):
        frame = pd.DataFrame(columns=years, dtype=float)
        for key, legacy in dic.LEGACY_BY_KEY.items():
            values = [dataset.value(key, f"{y}-12-31", st) for y in years]
            if any(v is not None for v in values):
                frame.loc[legacy] = values
        for name in dic.CORE_LEGACY_ITEMS:
            if name not in frame.index:
                frame.loc[name] = float("nan")
        out[st] = frame
    return out["IS"], out["BS"], out["CF"]


def display_frames(dataset: Dataset, unit: str = config.DISPLAY_UNIT) -> dict[str, pd.DataFrame]:
    """展示层金额视图（默认亿元），供图表与报告表格使用。

    与 to_legacy_frames 不同：这里保留全部标准科目（含费用、投资/筹资现金流等），
    并同时以标准名与 legacy 名建行，图表取数不必关心两种命名。
    """
    divisor = config.AMOUNT_UNITS[unit]
    out: dict[str, pd.DataFrame] = {}
    for st in ("IS", "BS", "CF"):
        raw = dataset.frame(st)                      # index=item_key, columns=报告期末
        cols = sorted({int(c[:4]) for c in raw.columns})
        view = pd.DataFrame(columns=cols, dtype=float)
        for key, row in raw.iterrows():
            spec = dic.BY_KEY.get(key)
            if spec is None:
                continue
            for c in raw.columns:
                view.loc[spec.label, int(c[:4])] = row[c] / divisor if row[c] is not None else None
        for key, legacy in dic.LEGACY_BY_KEY.items():
            if legacy not in view.index and key in raw.index:
                for c in raw.columns:
                    v = raw.loc[key, c]
                    view.loc[legacy, int(c[:4])] = v / divisor if v is not None else None
        out[st] = view
    return out
