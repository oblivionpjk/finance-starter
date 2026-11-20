"""REITs 分析标准数据模型。

与 A 股 Dataset 分离：这里只描述「一只标的的一条行情序列」和「一次分析任务」。
数据集按维度（quote / distribution / ...）挂在任务下，新增维度不需要改模型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app import config as app_config
from app.domain.model import QualityIssue
from app.reits_analysis import config as cfg


@dataclass
class ReitSeries:
    """一只 REIT 的日频行情序列（按日期升序）。"""

    code: str
    name: str
    market: str
    sheet: str
    dates: list[str] = field(default_factory=list)
    close: list[float] = field(default_factory=list)
    amount_million: list[float] = field(default_factory=list)
    is_listing_day: list[bool] = field(default_factory=list)

    @property
    def listing_date(self) -> str:
        return self.dates[0] if self.dates else ""

    @property
    def end_date(self) -> str:
        return self.dates[-1] if self.dates else ""

    @property
    def last_close(self) -> float | None:
        return self.close[-1] if self.close else None

    def index_of(self, date: str) -> int | None:
        try:
            return self.dates.index(date)
        except ValueError:
            return None

    def base_close(self, date: str, mode: str = "at_or_before") -> float | None:
        """取基准价。at_or_before：不晚于 date 的最后一个交易日。"""
        if not self.dates:
            return None
        if mode == "first":
            return self.close[0]
        idx = None
        for i, d in enumerate(self.dates):
            if d <= date:
                idx = i
            else:
                break
        return self.close[idx] if idx is not None else None


@dataclass
class QuoteDataset:
    """dimension='quote' 的数据集。"""

    dimension: str = "quote"
    source_file: str = ""
    series: dict[str, ReitSeries] = field(default_factory=dict)
    snapshot_date: str = ""
    common_start: str = ""
    common_end: str = ""
    price_field: str = cfg.PRICE_FIELD
    price_unit: str = cfg.PRICE_UNIT
    quality: list[QualityIssue] = field(default_factory=list)

    def codes(self) -> list[str]:
        return sorted(self.series)


@dataclass
class GenericDataset:
    """预留给后续维度：保留解析后的表，等待对应 metrics/report 提供者接入。"""

    dimension: str
    source_file: str
    tables: dict[str, Any] = field(default_factory=dict)
    quality: list[QualityIssue] = field(default_factory=list)
    note: str = ""


@dataclass
class SourceFile:
    key: str                  # 会话目录内的安全文件名
    original_name: str
    dimension: str | None     # 识别失败为 None
    sheet_count: int = 0
    note: str = ""


@dataclass
class AnalysisTask:
    """一次分析任务：上传文件 → 各维度数据集 → 指标 → 产物。"""

    id: str
    source_files: list[SourceFile] = field(default_factory=list)
    datasets: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    quote_field: str = cfg.PRICE_FIELD
    quote_unit: str = cfg.PRICE_UNIT
    benchmark_code: str = cfg.BENCHMARK_CODE
    exclude_listing_day: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)   # key -> 文件名
    quality_report: dict[str, Any] = field(default_factory=dict)

    @property
    def quotes(self) -> QuoteDataset | None:
        ds = self.datasets.get("quote")
        return ds if isinstance(ds, QuoteDataset) else None

    def state(self) -> dict[str, Any]:
        """给前端的状态摘要（不含完整序列）。"""
        q = self.quotes
        return {
            "task_id": self.id,
            "created_at": self.created_at,
            "source_files": [vars(f) for f in self.source_files],
            "snapshot_date": q.snapshot_date if q else "",
            "series_count": len(q.series) if q else 0,
            "common_window": {
                "start": q.common_start, "end": q.common_end,
            } if q else {},
            "benchmark": self.benchmark_code,
            "exclude_listing_day": self.exclude_listing_day,
            "price_basis": dict(cfg.PRICE_BASIS),
            "datasets": sorted(self.datasets),
            "quality": self.quality_report,
            "metrics_ready": bool(self.metrics),
            "artifacts": self.artifacts,
            "retention": "上传文件与产物仅在当前会话内留存，关闭页面即销毁。",
            "engine": app_config.NARRATOR,
        }
