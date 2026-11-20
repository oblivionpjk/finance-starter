"""解析质量报告与数据缺口清单（机器可读）。

首屏先展示「解析了几只 / 异常行 / 哪些对标做不了」，而不是直接堆图表。
"""
from __future__ import annotations

from typing import Any

from app.reits_analysis import config as cfg
from app.reits_analysis.model import AnalysisTask, QuoteDataset


def _issue_payload(issue: Any) -> dict[str, str]:
    return {
        "level": issue.level,
        "code": issue.code,
        "message": issue.message,
        "detail": issue.detail,
    }


def build_quality_report(task: AnalysisTask) -> dict[str, Any]:
    """汇总各维度质量、样本区间与未覆盖维度。"""
    q: QuoteDataset | None = task.quotes
    issues: list[dict[str, str]] = []
    per_series: list[dict[str, Any]] = []

    if q is not None:
        issues.extend(_issue_payload(i) for i in q.quality)
        for code in q.codes():
            s = q.series[code]
            per_series.append({
                "code": code, "name": s.name, "market": s.market,
                "sheet": s.sheet, "rows": len(s.dates),
                "listing_date": s.listing_date, "end_date": s.end_date,
                "last_close": s.last_close,
                "listing_day_amount": s.amount_million[0] if s.amount_million else None,
                "listing_day_spike": bool(s.is_listing_day and s.is_listing_day[0]
                                          and len(s.amount_million) > 1
                                          and s.amount_million[0] > 0),
            })

    gaps = []
    for key, spec in cfg.DIMENSIONS.items():
        # attachments 是「有上传才出现」的附加概览，未上传时不应列为缺口
        if key == "attachments" and key not in task.datasets:
            continue
        if spec.implemented and key in task.datasets:
            continue
        gaps.append({
            "dimension": key,
            "label": spec.label,
            "reason": spec.pending_reason if not spec.implemented else "尚未上传对应数据",
            "expected_columns": list(spec.expected_columns),
        })

    for f in task.source_files:
        if f.dimension is None:
            gaps.append({
                "dimension": "unrecognized",
                "label": f.original_name,
                "reason": f.note or "未识别为已声明的数据维度，已保留原文件但未参与分析",
                "expected_columns": [],
            })

    counts = {level: sum(1 for i in issues if i["level"] == level)
              for level in ("block", "warn", "info")}
    return {
        "source_files": [vars(f) for f in task.source_files],
        "datasets": sorted(task.datasets),
        "dimension_implemented": {
            k: cfg.DIMENSIONS[k].implemented for k in task.datasets if k in cfg.DIMENSIONS
        },
        "series_count": len(per_series),
        "snapshot_date": q.snapshot_date if q else "",
        "common_window": {
            "start": q.common_start, "end": q.common_end,
            "trading_days": len({
                d for d in (q.series[next(iter(q.series))].dates if q.series else [])
                if all(d in s.dates for s in q.series.values())
            }),
        } if q else {},
        "per_series": per_series,
        "price_basis": dict(cfg.PRICE_BASIS),
        "issues": issues,
        "issue_counts": counts,
        "gaps": gaps,
        "note": ("本份 WIND Excel 仅含日频行情；基本面类对标一律标注「待补」，"
                 "不估算、不补零。所有数值均从原始行情重算。"),
    }
