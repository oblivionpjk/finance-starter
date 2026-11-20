"""指标层：纯函数计算，不读写文件、不生成图表。

口径：
  * 单一时点：snapshot_date = 数据最新交易日，全报告锁定；
  * 年初至今：默认基准为上年最后一个交易日（实测可复现集团报告 -19.25%）；
  * 横向对比：默认使用所有标的齐全的公共窗口，避免上市时间不同造成失真；
  * 所有缺失值保留 None，不补零、不插值。

扩展：register_provider(dim, fn) 为新维度注册指标提供者，compute_metrics 会自动合并。
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Callable

from app.reits_analysis import config as cfg
from app.reits_analysis.model import AnalysisTask, QuoteDataset, ReitSeries

Provider = Callable[[Any, AnalysisTask], dict[str, Any]]


def daily_returns(close: list[float]) -> list[float]:
    if len(close) < 2:
        return []
    return [close[i] / close[i - 1] - 1.0 for i in range(1, len(close))
            if close[i - 1] > 0]


def annualized_volatility(close: list[float]) -> float | None:
    rets = daily_returns(close)
    if len(rets) < 2:
        return None
    return statistics.stdev(rets) * math.sqrt(cfg.TRADING_DAYS_PER_YEAR)


def max_drawdown(close: list[float]) -> float | None:
    """区间最大回撤，返回负值（如 -0.15 表示 -15%）。"""
    if not close:
        return None
    peak = close[0]
    worst = 0.0
    for value in close:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def normalized_curve(close: list[float], base: float = 100.0) -> list[float]:
    if not close or close[0] <= 0:
        return []
    return [base * v / close[0] for v in close]


def average_amount(amounts: list[float], exclude_listing_day: bool = False) -> float | None:
    values = amounts[1:] if exclude_listing_day and len(amounts) > 1 else amounts
    if not values:
        return None
    return sum(values) / len(values)


def _window_values(series: ReitSeries, start: str, end: str) -> tuple[list[str], list[float], list[float]]:
    pairs = [(d, c, a) for d, c, a in zip(series.dates, series.close, series.amount_million)
             if start <= d <= end]
    if not pairs:
        return [], [], []
    return ([p[0] for p in pairs], [p[1] for p in pairs], [p[2] for p in pairs])


def _correlation_matrix(series_map: dict[str, ReitSeries], start: str, end: str) -> dict[str, Any]:
    codes = sorted(series_map)
    rets_by_code: dict[str, list[float]] = {}
    for code in codes:
        _, close, _ = _window_values(series_map[code], start, end)
        rets_by_code[code] = daily_returns(close)
    length = min((len(v) for v in rets_by_code.values()), default=0)
    matrix: list[list[float | None]] = []
    for a in codes:
        row: list[float | None] = []
        for b in codes:
            x, y = rets_by_code[a][:length], rets_by_code[b][:length]
            if len(x) < 2:
                row.append(None)
                continue
            mx, my = sum(x) / len(x), sum(y) / len(y)
            num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
            den = math.sqrt(sum((xi - mx) ** 2 for xi in x) * sum((yi - my) ** 2 for yi in y))
            row.append(None if den == 0 else num / den)
        matrix.append(row)
    return {"codes": codes, "matrix": matrix, "trading_days": length + 1}


def _ytd_base_date(series: ReitSeries, snapshot_date: str, mode: str) -> str | None:
    if mode == cfg.YTD_BASE_ALTERNATIVE or not series.dates:
        return series.dates[0] if series.dates else None
    year = int(snapshot_date[:4])
    anchor = f"{year - 1}-12-31"
    candidates = [d for d in series.dates if d <= anchor]
    return candidates[-1] if candidates else None


def single_metrics(series: ReitSeries, start: str, end: str, snapshot_date: str,
                   ytd_mode: str = cfg.YTD_BASE_MODE,
                   exclude_listing_day: bool = False) -> dict[str, Any]:
    """单标的指标；区间统计用公共窗口，涨跌幅按各自完整序列。"""
    _, window_close, window_amount = _window_values(series, start, end)
    base_date = _ytd_base_date(series, snapshot_date, ytd_mode)
    ytd_base = series.base_close(base_date) if base_date else None
    last = series.last_close
    first = series.close[0] if series.close else None
    return {
        "code": series.code,
        "name": series.name,
        "market": series.market,
        "listing_date": series.listing_date,
        "end_date": series.end_date,
        "snapshot_close": last,
        "ytd_base_date": base_date,
        "ytd_base_close": ytd_base,
        "ytd_return": None if last is None or ytd_base in (None, 0) else last / ytd_base - 1.0,
        "since_listing_return": None if last is None or first in (None, 0) else last / first - 1.0,
        "window_return": None if not window_close or window_close[0] == 0
                          else window_close[-1] / window_close[0] - 1.0,
        "annualized_volatility": annualized_volatility(window_close),
        "max_drawdown": max_drawdown(window_close),
        "avg_amount_million": average_amount(window_amount, exclude_listing_day),
        "window_days": len(window_close),
        "normalized_curve": normalized_curve(window_close),
    }


def _rank(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    valid = [r for r in rows if r.get(key) is not None]
    ordered = sorted(valid, key=lambda r: r[key], reverse=True)
    return [{"code": r["code"], "name": r["name"], "value": r[key]} for r in ordered]


def compare_quotes(dataset: QuoteDataset, benchmark_code: str = cfg.BENCHMARK_CODE,
                   ytd_mode: str = cfg.YTD_BASE_MODE,
                   exclude_listing_day: bool = False) -> dict[str, Any]:
    """华安百联（或指定基准）vs 其余标的的横向对标。"""
    start, end = dataset.common_start, dataset.common_end
    rows = [single_metrics(dataset.series[c], start, end, dataset.snapshot_date,
                           ytd_mode, exclude_listing_day) for c in dataset.codes()]
    benchmark = next((r for r in rows if r["code"] == benchmark_code), None)
    return {
        "dimension": "quote",
        "snapshot_date": dataset.snapshot_date,
        "window": {"start": start, "end": end,
                   "days": rows[0]["window_days"] if rows else 0},
        "ytd_mode": ytd_mode,
        "exclude_listing_day": exclude_listing_day,
        "benchmark_code": benchmark_code,
        "benchmark": benchmark,
        "series": rows,
        "rankings": {
            "ytd_return": _rank(rows, "ytd_return"),
            "since_listing_return": _rank(rows, "since_listing_return"),
            "window_return": _rank(rows, "window_return"),
            "annualized_volatility": _rank(rows, "annualized_volatility"),
            "max_drawdown": _rank(rows, "max_drawdown"),
            "avg_amount_million": _rank(rows, "avg_amount_million"),
        },
        "correlation": _correlation_matrix(dataset.series, start, end),
        "curve": {
            "dates": [d for d in dataset.series[dataset.codes()[0]].dates
                      if start <= d <= end],
            "series": {r["code"]: r["normalized_curve"] for r in rows},
        },
        "price_field": dataset.price_field,
        "price_unit": dataset.price_unit,
    }


PROVIDERS: dict[str, Provider] = {}


def register_provider(dimension: str, fn: Provider) -> None:
    """扩展入口：注册新维度的指标提供者。"""
    PROVIDERS[dimension] = fn


def compute_metrics(task: AnalysisTask, benchmark_code: str = cfg.BENCHMARK_CODE,
                    exclude_listing_day: bool = False) -> dict[str, Any]:
    """汇总所有已实现维度的指标；未实现维度不进入结果，由报告列缺口。"""
    out: dict[str, Any] = {}
    q = task.quotes
    if q is not None:
        out["quote"] = compare_quotes(q, benchmark_code, cfg.YTD_BASE_MODE, exclude_listing_day)
    for dimension, provider in PROVIDERS.items():
        if dimension in task.datasets:
            out[dimension] = provider(task.datasets[dimension], task)
    return out
