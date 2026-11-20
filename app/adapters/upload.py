"""上传文件解析：当前仅支持 xlsx / xls / csv，解析器通过注册表扩展。

布局自动探测（报告日 × 科目 / 项目 × 期间），并产出映射确认页所需的建议数据：
未命中词典的「可能关键科目」带候选标准科目，由用户显式指定后才纳入分析。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from app import config
from app.domain import dictionary as dic
from app.domain.normalize import ParsedTable, inspect

PARSERS: dict[str, Callable[[Path], list[ParsedTable]]] = {}


def register_parser(suffix: str, fn: Callable[[Path], list[ParsedTable]]) -> None:
    PARSERS[suffix.lower()] = fn


def _read_csv(path: Path) -> list[ParsedTable]:
    last: Exception | None = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            df = pd.read_csv(path, encoding=enc)
            return [inspect(df, path.name, "")]
        except UnicodeDecodeError as e:
            last = e
    raise ValueError(f"CSV 编码无法识别：{path.name}（{last}）")


def _read_excel(path: Path) -> list[ParsedTable]:
    sheets = pd.read_excel(path, sheet_name=None)
    out: list[ParsedTable] = []
    for sheet, df in sheets.items():
        name = f"{path.name}::{sheet}" if len(sheets) > 1 else path.name
        out.append(inspect(df, name, str(sheet)))
    return out


register_parser(".csv", _read_csv)
register_parser(".xlsx", _read_excel)
register_parser(".xls", _read_excel)


def read_tables(path: Path) -> list[ParsedTable]:
    suffix = path.suffix.lower()
    if suffix not in config.ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError(f"不支持的文件格式：{suffix}；当前仅支持 xlsx / xls / csv")
    parser = PARSERS.get(suffix)
    if parser is None:
        raise ValueError(f"未注册解析器：{suffix}")
    return parser(path)


def inspect_payload(tables: list[ParsedTable]) -> dict:
    """给前端映射确认页的结构化建议。"""
    all_labels: list[str] = []
    for t in tables:
        all_labels.extend(t.raw_labels)
    unique = list(dict.fromkeys(all_labels))

    mapped, unmapped = [], []
    for raw in unique:
        key, conf, matched = dic.map_label(raw)
        if matched == "meta":
            continue
        if key:
            mapped.append({"raw": raw, "label": dic.BY_KEY[key].label,
                           "item_key": key, "confidence": conf})
        elif dic.is_important_label(raw):
            unmapped.append({"raw": raw, "suggestions": dic.suggest(raw)})

    return {
        "files": [{
            "name": t.name, "layout": t.layout, "sheet": t.sheet,
            "role_guess": t.role_guess, "labels": len(t.raw_labels),
            "periods": t.period_labels[:6],
        } for t in tables],
        "roles": {t.name: t.role_guess for t in tables},
        "roles_allowed": ["BS", "IS", "CF"],
        "units": list(config.AMOUNT_UNITS),
        "default_unit": config.DEFAULT_UPLOAD_UNIT,
        "standard_items": [{"item_key": s.key, "label": s.label} for s in dic.ITEMS],
        "mapped": mapped[:60],
        "unmapped": unmapped[:40],
    }
