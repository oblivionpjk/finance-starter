"""8 张 PNG 图表：全部独立可下载，图内含数据来源、时点、样本区间与口径脚注。

中文复用 src.visualize.setup_chinese_font；matplotlib 全局状态用锁保护。
扩展：register_charts(dim, fn) 注册新维度的图片生成者。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app import config as app_config
from app.reits_analysis import config as cfg
from app.reits_analysis.model import AnalysisTask
from src import visualize

_LOCK = threading.Lock()
_BENCH_COLOR = "#C0392B"
_UP_COLOR = "#D64541"      # A 股惯例：涨 -> 红
_DOWN_COLOR = "#2E9E6B"    # 跌 -> 绿
_OTHER_COLOR = "#7F9CC0"


def _note(task: AnalysisTask, metrics: dict[str, Any]) -> str:
    q = metrics.get("quote", {})
    w = q.get("window", {})
    name = task.source_files[0].original_name if task.source_files else "WIND 导出文件"
    label = cfg.PRICE_BASIS["label"]
    bench = q.get("benchmark") or {}
    bench_name = bench.get("name") or q.get("benchmark_code") or "—"
    bench_code = bench.get("code") or q.get("benchmark_code") or "—"
    return (f"数据来源：WIND：{name}；数据时点：{q.get('snapshot_date', '—')}；"
            f"样本区间：{w.get('start', '—')} ~ {w.get('end', '—')}"
            f"（{w.get('days', 0)} 个交易日）；口径：{label}（详见报告第 1 节）；"
            f"对标基准：{bench_name}（{bench_code}）")


def _save(fig: plt.Figure, path: Path, note: str) -> Path:
    fig.text(0.012, 0.012, note, fontsize=7.5, color="#555555")
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.savefig(path, dpi=app_config.CHART_DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _bars(labels: list[str], values: list[float | None], benchmark_code: str,
          codes: list[str], title: str, ylabel: str, fmt: str,
          path: Path, note: str, color_by_sign: bool = False) -> Path:
    pairs = [(l, v, c) for l, v, c in zip(labels, values, codes) if v is not None]
    pairs.sort(key=lambda p: p[1])
    fig, ax = plt.subplots(figsize=(10, max(4.2, 0.42 * len(pairs) + 1.6)))
    colors = []
    for _, value, code in pairs:
        if code == benchmark_code:
            colors.append(_BENCH_COLOR)
        elif color_by_sign:
            colors.append(_UP_COLOR if value >= 0 else _DOWN_COLOR)
        else:
            colors.append(_OTHER_COLOR)
    bars = ax.barh([p[0] for p in pairs], [p[1] for p in pairs], color=colors,
                   edgecolor=["#4A2C2A" if p[2] == benchmark_code else "none" for p in pairs],
                   linewidth=1.4)
    for bar, (_, value, code) in zip(bars, pairs):
        offset = (max(abs(p[1]) for p in pairs) or 1) * 0.015
        ax.text(bar.get_width() + (offset if value >= 0 else -offset),
                bar.get_y() + bar.get_height() / 2,
                fmt.format(value) + ("  ★基准" if code == benchmark_code else ""),
                va="center", ha="left" if value >= 0 else "right", fontsize=8)
    ax.axvline(0, color="#888888", linewidth=0.8)
    ax.set_title(title)
    ax.set_xlabel(ylabel)
    ax.grid(axis="x", alpha=0.25)
    return _save(fig, path, note)


def quote_charts(task: AnalysisTask, metrics: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    q = metrics.get("quote")
    if not q:
        return {}
    rows = q["series"]
    bench = q["benchmark_code"]
    bench_name = (q.get("benchmark") or {}).get("name") or bench
    codes = [r["code"] for r in rows]
    names = [r["name"] for r in rows]
    note = _note(task, metrics)
    paths: dict[str, Path] = {}

    # 1 归一化走势
    fig, ax = plt.subplots(figsize=(11, 6))
    for r in rows:
        curve = r["normalized_curve"]
        if not curve:
            continue
        is_bench = r["code"] == bench
        ax.plot(range(len(curve)), curve,
                linewidth=2.8 if is_bench else 1.15,
                color=_BENCH_COLOR if is_bench else _OTHER_COLOR,
                alpha=1.0 if is_bench else 0.75,
                label=(f"{r['name']}（基准）" if is_bench else None))
    ax.axhline(100, color="#888888", linestyle="--", linewidth=0.8)
    ax.set_title(f"{len(rows)} 只消费 REIT 归一化累计收益（基期 = 100；对标基准：{bench_name}）")
    ax.set_xlabel("公共窗口交易日序号")
    ax.set_ylabel("归一化净值")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", fontsize=9)
    paths["price_trend"] = _save(fig, out_dir / cfg.CHART_FILES["price_trend"], note)

    # 2 年初至今涨跌幅
    paths["ytd_return"] = _bars(
        names, [r["ytd_return"] for r in rows], bench, codes,
        f"年初至今涨跌幅（上年最后交易日基准；对标基准：{bench_name}）", "涨跌幅（%）", "{:+.2f}%",
        out_dir / cfg.CHART_FILES["ytd_return"], note, color_by_sign=True)

    # 3 上市至今涨跌幅
    paths["since_listing"] = _bars(
        names, [r["since_listing_return"] for r in rows], bench, codes,
        f"上市至今涨跌幅（各标的上市首日起算；对标基准：{bench_name}）", "涨跌幅（%）", "{:+.2f}%",
        out_dir / cfg.CHART_FILES["since_listing"], note, color_by_sign=True)

    # 4 期末收盘价
    paths["close_price"] = _bars(
        names, [r["snapshot_close"] for r in rows], bench, codes,
        f"期末收盘价（{q['snapshot_date']}；对标基准：{bench_name}）", "收盘价（元）", "{:.3f}",
        out_dir / cfg.CHART_FILES["close_price"], note)

    # 5 风险收益散点
    fig, ax = plt.subplots(figsize=(9, 5.8))
    for r in rows:
        vol, ret = r.get("annualized_volatility"), r.get("window_return")
        if vol is None or ret is None:
            continue
        is_bench = r["code"] == bench
        ax.scatter(vol * 100, ret * 100, s=210 if is_bench else 70,
                   color=_BENCH_COLOR if is_bench else _OTHER_COLOR,
                   marker="*" if is_bench else "o", zorder=3)
        ax.annotate(r["code"] + (" ★" if is_bench else ""),
                    (vol * 100, ret * 100), fontsize=8,
                    xytext=(4, 4), textcoords="offset points")
    ax.axhline(0, color="#888888", linewidth=0.8)
    ax.set_title(f"风险收益散点（年化波动率 × 公共窗口收益；对标基准：{bench_name}）")
    ax.set_xlabel("年化波动率（%）")
    ax.set_ylabel("区间收益（%）")
    ax.grid(alpha=0.25)
    paths["vol_return_scatter"] = _save(
        fig, out_dir / cfg.CHART_FILES["vol_return_scatter"], note)

    # 6 最大回撤
    paths["drawdown"] = _bars(
        names, [r["max_drawdown"] for r in rows], bench, codes,
        f"公共窗口最大回撤（对标基准：{bench_name}）", "最大回撤（%）", "{:.2f}%",
        out_dir / cfg.CHART_FILES["drawdown"], note)

    # 7 日均成交额
    paths["liquidity"] = _bars(
        names, [r["avg_amount_million"] for r in rows], bench, codes,
        f"日均成交金额（百万元；对标基准：{bench_name}"
        + ("，已剔除上市首日）" if q.get("exclude_listing_day") else "）"),
        "百万元", "{:.2f}",
        out_dir / cfg.CHART_FILES["liquidity"], note)

    # 8 相关性热力图
    corr = q["correlation"]
    matrix = np.array([[np.nan if v is None else v for v in row]
                       for row in corr["matrix"]], dtype=float)
    fig, ax = plt.subplots(figsize=(9.5, 8))
    im = ax.imshow(matrix, cmap="RdYlBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(corr["codes"])))
    ax.set_xticklabels(corr["codes"], rotation=45, ha="right")
    ax.set_yticks(range(len(corr["codes"])))
    ax.set_yticklabels(corr["codes"])
    for i in range(len(corr["codes"])):
        for j in range(len(corr["codes"])):
            if not np.isnan(matrix[i, j]):
                ax.text(j, i, f"{matrix[i, j]:.2f}", ha="center", va="center", fontsize=7)
    bench_idx = corr["codes"].index(bench) if bench in corr["codes"] else -1
    if bench_idx >= 0:
        ax.add_patch(plt.Rectangle((bench_idx - 0.5, -0.5), 1, len(corr["codes"]),
                                   fill=False, edgecolor="#111111", linewidth=2.2))
        ax.add_patch(plt.Rectangle((-0.5, bench_idx - 0.5), len(corr["codes"]), 1,
                                   fill=False, edgecolor="#111111", linewidth=2.2))
    fig.colorbar(im, ax=ax, label="日收益相关系数")
    ax.set_title(f"日收益率相关性矩阵（基准行/列加框：{bench_name}）")
    paths["corr_heatmap"] = _save(fig, out_dir / cfg.CHART_FILES["corr_heatmap"], note)

    return paths


BUILDERS: dict[str, Callable[[AnalysisTask, dict[str, Any], Path], dict[str, Path]]] = {}


def register_charts(dimension: str, fn: Callable[[AnalysisTask, dict[str, Any], Path], dict[str, Path]]) -> None:
    """扩展入口：注册新维度的图片生成者。"""
    BUILDERS[dimension] = fn


register_charts("quote", quote_charts)


def generate_charts(task: AnalysisTask, metrics: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    """按已实现维度产出图片；文件名由配置统一登记，供页面下载。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    with _LOCK:
        visualize.setup_chinese_font()
        for dimension, fn in BUILDERS.items():
            if dimension in metrics:
                paths.update(fn(task, metrics, out_dir))
    return paths
