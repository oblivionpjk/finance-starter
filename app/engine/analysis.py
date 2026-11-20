"""分析引擎：原样复用 src/ratios.py 的 26 项指标与杜邦，扩展趋势/结构/质量。

产出 AnalysisResult 是报告与图表的唯一数字来源；NumberRegistry 随结果一同返回，
供报告生成阶段做数字一致性校验。
"""
from __future__ import annotations

import pandas as pd

from app import config
from app.domain import dictionary as dic
from app.domain.model import AnalysisResult, Dataset, QualityIssue
from app.domain.normalize import display_frames, to_legacy_frames
from app.domain.numbers import NumberRegistry
from app.engine import rules
from app.rendering import charts
from src import ratios

CORE_FOR_HEATMAP = (
    ("revenue", "IS", "营业收入"), ("cogs", "IS", "营业成本"),
    ("net_profit", "IS", "净利润"), ("total_assets", "BS", "资产总计"),
    ("total_liab", "BS", "负债合计"), ("equity", "BS", "所有者权益"),
    ("cfo", "CF", "经营活动现金流"), ("cfi", "CF", "投资活动现金流"),
    ("cff", "CF", "筹资活动现金流"),
)


def analyze(
    dataset: Dataset,
    quality: list[QualityIssue],
    max_periods: int | None = None,
) -> tuple[AnalysisResult, NumberRegistry]:
    reg = NumberRegistry()
    inc, bs, cf = to_legacy_frames(dataset)          # 单位：元，引擎口径
    tables = ratios.summary(inc, bs, cf)              # 现有 26 项指标 + 杜邦，一行未改

    years = sorted(set(inc.columns) & set(bs.columns) & set(cf.columns))
    valid = [
        y for y in years
        if pd.notna(inc.loc["营业收入", y]) and pd.notna(bs.loc["资产总计", y])
    ]
    if max_periods and max_periods > 0:
        valid = valid[-max_periods:]
    periods = [str(y) for y in valid]
    period_ends = [f"{y}-12-31" for y in valid]

    frames = {k: v.reindex(columns=valid) for k, v in display_frames(dataset).items()}

    missing_matrix: list[dict] = []
    for y, p in zip(valid, period_ends):
        missing: dict[str, bool] = {}
        for key, st, label in CORE_FOR_HEATMAP:
            frame = dataset.frame(st)
            missing[label] = key not in frame.index or p not in frame.columns or pd.isna(frame.loc[key, p])
        missing_matrix.append({"period": str(y), "missing": missing})

    source_meta = {
        "标的": dataset.subject,
        "证券简称": dataset.company_name or "—",
        "简称来源": dataset.name_source or (
            "不适用：上传入口不含证券代码" if dataset.origin == "upload"
            else "未匹配到证券简称"
        ),
        "数据入口": "A 股代码" if dataset.origin == "code" else "用户上传三大报表",
        "数据来源": dataset.source_ref,
        "数据获取时间": dataset.created_at,
        "报表范围": "合并报表" if dataset.statement_scope == "consolidated" else "母公司报表",
        "报告期": "、".join(periods) if periods else "无可比年度报告期",
        "金额单位": config.DISPLAY_UNIT,
        "币种": dataset.currency,
        "口径": "年度报告期；净利润为报表净利润口径（非归母净利润）；周转率用期初期末平均余额",
    }

    chart_specs = charts.build_chart_specs(tables, frames, periods,
                                           dataset.source_ref, missing_matrix)
    insights = rules.build_insights(tables, frames, periods, quality, reg)

    result = AnalysisResult(
        subject=dataset.subject, periods=periods, period_ends=period_ends,
        tables=tables, frames=frames, chart_specs=chart_specs,
        insights=insights, quality=quality, source_meta=source_meta,
        mapping_audit=dataset.mapping_audit,
    )
    return result, reg
