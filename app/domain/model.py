"""统一财务数据模型（Canonical Financial Dataset）。

两条入口（A 股代码 / 上传三表）都必须产出同构的 Dataset，下游分析、报告、图表
只消费这一份结果。所有金额在 facts 里统一以「元」存储，展示层才做单位换算。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class StatementFact:
    """一条财务事实：某报告期、某报表、某标准科目的值。"""
    period_end: str          # YYYY-MM-DD
    period_type: str         # FY / H1 / Q1 / Q3
    statement: str           # BS / IS / CF
    item_key: str            # 标准科目编码（见 dictionary.py）
    item_label_raw: str      # 原始科目名，保留供审计
    value: float | None      # 单位：元；缺失为 None，禁止补 0
    unit_raw: str            # 原始单位（元 / 万元 / 亿元）
    currency: str
    mapping_confidence: float
    source_ref: str          # 文件名 / 接口 + 报告期
    is_restated: bool = False


@dataclass
class QualityIssue:
    """数据质量条目。level=block 会中止分析。"""
    level: str               # block / warn / info
    code: str
    message: str
    detail: str = ""


@dataclass
class Dataset:
    dataset_id: str
    origin: str              # code / upload
    subject: str             # 展示名：代码入口「贵州茅台（600519）」/ 上传入口「上传报表」
    source_ref: str
    statement_scope: str     # consolidated 合并 / parent 母公司
    currency: str
    facts: list[StatementFact] = field(default_factory=list)
    quality: list[QualityIssue] = field(default_factory=list)
    created_at: str = ""
    company_name: str = ""       # 证券简称，仅展示层使用；上传入口为空
    name_source: str = ""        # 简称来源，报告与界面需标注以便审计
    mapping_audit: list[dict[str, Any]] = field(default_factory=list)

    def periods(self, statement: str | None = None, period_type: str = "FY") -> list[str]:
        """返回排序后的报告期末列表。"""
        return sorted({
            f.period_end for f in self.facts
            if f.period_type == period_type and (statement is None or f.statement == statement)
        })

    def frame(self, statement: str, period_type: str = "FY") -> pd.DataFrame:
        """转为「标准科目 × 报告期」数值矩阵，便于校验与图表取数。"""
        rows = [
            f for f in self.facts
            if f.statement == statement and f.period_type == period_type
        ]
        periods = sorted({f.period_end for f in rows})
        keys = sorted({f.item_key for f in rows})
        out = pd.DataFrame(index=keys, columns=periods, dtype=float)
        for f in rows:
            out.loc[f.item_key, f.period_end] = f.value
        return out

    def value(self, item_key: str, period_end: str, statement: str | None = None) -> float | None:
        """取单条事实；同一科目在多张表出现时必须指定 statement。"""
        for f in self.facts:
            if (f.item_key == item_key and f.period_end == period_end
                    and (statement is None or f.statement == statement)):
                return f.value
        return None


@dataclass
class Insight:
    """确定性规则产出的结论。文字里的数字全部由 NumberRegistry 注入。"""
    text: str
    level: str = "info"      # info / warn
    refs: tuple[str, ...] = ()


@dataclass
class ChartSpec:
    """与渲染框架无关的图表规格：同一份数据可渲染静态图或未来的交互图。"""
    chart_id: str
    title: str
    chart_type: str          # line / bar / stacked_bar / area / radar / waterfall / pie / heatmap
    categories: list[str]
    series: list[dict[str, Any]]   # {name, values, axis}
    unit: str
    note: str = ""
    source_ref: str = ""


@dataclass
class AnalysisResult:
    """分析引擎唯一输出。报告与图表都只消费它，不重新读取原始报表。"""
    subject: str
    periods: list[str]                       # 年份标签（str(int year)）
    period_ends: list[str]
    tables: dict[str, pd.DataFrame]          # 复用 src.ratios 的六大类指标
    frames: dict[str, pd.DataFrame]          # 三张「科目 × 年份」金额视图（亿元）
    chart_specs: list[ChartSpec]
    insights: list[Insight]
    quality: list[QualityIssue]
    source_meta: dict[str, str]
    mapping_audit: list[dict[str, Any]]


@dataclass
class ReportBlock:
    """结构化报告块。渲染器只按 type 排版，不产生任何数字。"""
    type: str                # heading / paragraph / table / image / bullets / callout / pagebreak
    payload: Any


@dataclass
class ReportDocument:
    title: str
    subject: str
    blocks: list[ReportBlock]
    source_meta: dict[str, str]
    disclaimer: str

    def all_text(self) -> str:
        """汇总所有可读文本，供数字一致性校验扫描。"""
        chunks: list[str] = [self.title, self.subject, self.disclaimer]
        for b in self.blocks:
            p = b.payload
            if isinstance(p, str):
                chunks.append(p)
            elif isinstance(p, dict):
                chunks.append(str(p.get("text", "")))
                chunks.append(str(p.get("caption", "")))
                chunks.append(str(p.get("note", "")))
                header = p.get("header")
                if header:
                    chunks.extend(str(x) for x in header)
                for row in p.get("rows", []):
                    chunks.extend(str(x) for x in row)
            elif isinstance(p, (list, tuple)):
                chunks.extend(str(x) for x in p)
        return "\n".join(chunks)
