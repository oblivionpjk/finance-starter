"""图表规格（ChartSpec）生成 + matplotlib 静态渲染。

规格与渲染分离：同一份 ChartSpec 现在渲染为 PDF 内嵌 PNG，
未来接前端交互图时只需新增渲染器，不改分析引擎。
全局锁保证 matplotlib 在 FastAPI 线程池里并发渲染时不会串图。
"""
from __future__ import annotations

import math
import threading
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from app import config
from app.domain.model import ChartSpec
from src import visualize

_RENDER_LOCK = threading.Lock()


def _clean(values: list[float | None]) -> np.ndarray:
    return np.array([np.nan if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
                     for v in values], dtype=float)


def _frame_values(frame: pd.DataFrame, label: str, years: list[int]) -> list[float | None]:
    if label not in frame.index:
        return [None] * len(years)
    out: list[float | None] = []
    for y in years:
        try:
            v = frame.loc[label, y]
        except (KeyError, TypeError):
            v = None
        out.append(None if v is None or pd.isna(v) else float(v))
    return out


def _metric_values(tables: dict[str, pd.DataFrame], category: str,
                   metric: str, years: list[int], scale: float = 1.0) -> list[float | None]:
    df = tables.get(category)
    if df is None or metric not in df.columns:
        return [None] * len(years)
    out: list[float | None] = []
    for y in years:
        try:
            v = df.loc[y, metric]
        except KeyError:
            v = None
        out.append(None if v is None or pd.isna(v) else float(v) * scale)
    return out


def _add(specs: list[ChartSpec], spec: ChartSpec) -> None:
    # 没有任何有效数值的图不产出，避免 PDF 里出现空图
    if any(v is not None for s in spec.series for v in s["values"]):
        specs.append(spec)


def build_chart_specs(
    tables: dict[str, pd.DataFrame],
    frames: dict[str, pd.DataFrame],
    periods: list[str],
    source_ref: str,
    missing_matrix: list[dict] | None = None,
) -> list[ChartSpec]:
    """按架构文档第 9.2 节产出图表规格清单。"""
    years = [int(y) for y in periods]
    labels = [str(y) for y in years]
    inc, bs, cf = frames["IS"], frames["BS"], frames["CF"]
    specs: list[ChartSpec] = []
    note = "数据来源：" + source_ref + "；金额单位以图题标注；缺失值留白"

    def series(name: str, values: list[float | None], axis: str = "left") -> dict:
        return {"name": name, "values": values, "axis": axis}

    # 1 核心经营趋势
    _add(specs, ChartSpec("core_trend", "营业收入 / 净利润 / 经营现金流趋势", "line", labels, [
        series("营业收入", _frame_values(inc, "营业收入", years)),
        series("净利润", _frame_values(inc, "净利润", years)),
        series("经营现金流净额", _frame_values(cf, "经营活动产生的现金流量净额", years)),
    ], config.DISPLAY_UNIT, note, source_ref))

    # 2 同比增速
    _add(specs, ChartSpec("growth", "营业收入与净利润同比增速", "bar", labels, [
        series("营业收入增速", _metric_values(tables, "成长能力", "营业收入增速", years, 100)),
        series("净利润增速", _metric_values(tables, "成长能力", "净利润增速", years, 100)),
    ], "%", note, source_ref))

    # 3 利润率趋势
    _add(specs, ChartSpec("margins", "毛利率 / 净利率 / ROE 趋势", "line", labels, [
        series("毛利率", _metric_values(tables, "盈利能力", "毛利率", years, 100)),
        series("净利率", _metric_values(tables, "盈利能力", "净利率", years, 100)),
        series("ROE", _metric_values(tables, "盈利能力", "ROE(净资产收益率)", years, 100)),
    ], "%", note, source_ref))

    # 4 资产结构
    ca = _frame_values(bs, "流动资产合计", years)
    ta = _frame_values(bs, "资产总计", years)
    nca = [None if a is None or t is None else t - a for a, t in zip(ca, ta)]
    _add(specs, ChartSpec("asset_structure", "资产结构（流动 / 非流动）", "stacked_bar", labels, [
        series("流动资产", ca), series("非流动资产", nca),
    ], config.DISPLAY_UNIT, note, source_ref))

    # 5 资本结构
    _add(specs, ChartSpec("capital_structure", "负债与所有者权益结构", "stacked_bar", labels, [
        series("负债合计", _frame_values(bs, "负债合计", years)),
        series("所有者权益", _frame_values(bs, "所有者权益(或股东权益)合计", years)),
    ], config.DISPLAY_UNIT, note, source_ref))

    # 6 收入到利润的瀑布（最新年度）
    if years:
        y = years[-1]
        steps = [
            ("营业收入", _frame_values(inc, "营业收入", [y])[0]),
            ("营业成本", _frame_values(inc, "营业成本", [y])[0]),
            ("销售费用", _frame_values(inc, "销售费用", [y])[0] if "销售费用" in inc.index else None),
            ("管理费用", _frame_values(inc, "管理费用", [y])[0] if "管理费用" in inc.index else None),
            ("财务费用", _frame_values(inc, "财务费用", [y])[0] if "财务费用" in inc.index else None),
            ("营业利润", _frame_values(inc, "营业利润", [y])[0]),
            ("净利润", _frame_values(inc, "净利润", [y])[0]),
        ]
        vals: list[float | None] = [steps[0][1]]
        for name, v in steps[1:5]:
            vals.append(None if v is None else -abs(v))
        vals.append(None)
        vals.append(steps[-1][1])
        cats = [s[0] for s in steps[:5]] + ["营业利润", "净利润"]
        _add(specs, ChartSpec("profit_waterfall", f"{y} 年收入到利润结构", "waterfall", cats, [
            series("金额", vals),
        ], config.DISPLAY_UNIT, note + "；成本费用以负向台阶表示", source_ref))

    # 7 三大现金流对比
    _add(specs, ChartSpec("cashflow_mix", "经营 / 投资 / 筹资现金流净额", "bar", labels, [
        series("经营活动", _frame_values(cf, "经营活动产生的现金流量净额", years)),
        series("投资活动", _frame_values(cf, "投资活动产生的现金流量净额", years, )),
        series("筹资活动", _frame_values(cf, "筹资活动产生的现金流量净额", years)),
    ], config.DISPLAY_UNIT, note, source_ref))

    # 8 净利润现金含量
    _add(specs, ChartSpec("cash_quality", "净利润现金含量（净现比）", "line", labels, [
        series("净利润现金含量", _metric_values(tables, "现金流", "净利润现金含量", years)),
        series("基准线 1", [1.0] * len(years)),
    ], "倍", note, source_ref))

    # 9 五维能力雷达（最新年度）
    if years:
        y = years[-1]
        caps = {"盈利": 0.30, "偿债": 4.0, "营运": 1.5, "成长": 0.30, "现金流": 2.0}
        picks = [
            ("盈利", "盈利能力", "ROE(净资产收益率)"),
            ("偿债", "偿债能力", "流动比率"),
            ("营运", "营运能力", "总资产周转率"),
            ("成长", "成长能力", "营业收入增速"),
            ("现金流", "现金流", "净利润现金含量"),
        ]
        vals = []
        for dim, cat, metric in picks:
            v = _metric_values(tables, cat, metric, [y])[0]
            vals.append(None if v is None else min(max(v, 0.0) / caps[dim], 1.0))
        _add(specs, ChartSpec("radar", f"{y} 年五维财务能力雷达", "radar",
                              [p[0] for p in picks], [series("归一值", vals)], "0-1 相对值",
                              note + "；各维按固定经验上限归一，仅用于同年跨维比较", source_ref))

    # 10 杜邦恒等校验
    _add(specs, ChartSpec("dupont_check", "杜邦分解 ROE 与直接计算 ROE", "line", labels, [
        series("ROE（分解乘积）", _metric_values(tables, "杜邦分解", "ROE(分解乘积)", years, 100)),
        series("ROE（直接计算）", _metric_values(tables, "杜邦分解", "ROE(直接计算)", years, 100)),
    ], "%", note, source_ref))

    # 11 杜邦三因子
    _add(specs, ChartSpec("dupont_drivers", "杜邦三因子趋势", "line", labels, [
        series("净利率", _metric_values(tables, "杜邦分解", "净利率", years, 100)),
        series("总资产周转率", _metric_values(tables, "杜邦分解", "总资产周转率", years), "right"),
        series("权益乘数", _metric_values(tables, "杜邦分解", "权益乘数", years), "right"),
    ], "% / 倍（双轴）", note, source_ref))

    # 12 周转率
    _add(specs, ChartSpec("turnover", "营运周转率趋势", "line", labels, [
        series("应收账款周转率", _metric_values(tables, "营运能力", "应收账款周转率", years)),
        series("存货周转率", _metric_values(tables, "营运能力", "存货周转率", years)),
        series("总资产周转率", _metric_values(tables, "营运能力", "总资产周转率", years)),
    ], "次", note, source_ref))

    # 13 应收 + 存货占资产比重
    ar = _frame_values(bs, "应收账款", years)
    inv = _frame_values(bs, "存货", years)
    ta_pct = []
    for a, i, t in zip(ar, inv, ta):
        parts = [v for v in (a, i) if v is not None]
        ta_pct.append(None if not parts or t in (None, 0) else sum(parts) / t * 100)
    _add(specs, ChartSpec("working_capital", "应收账款与存货占资产比重", "area", labels, [
        series("占比", ta_pct),
    ], "%", note, source_ref))

    # 14 数据质量热力图
    if missing_matrix:
        cats = [m["period"] for m in missing_matrix]
        rows: dict[str, list[float | None]] = {}
        for m in missing_matrix:
            for k, v in m["missing"].items():
                rows.setdefault(k, []).append(1.0 if v else 0.0)
        _add(specs, ChartSpec("quality_heatmap", "核心科目缺失情况", "heatmap", cats, [
            series(k, vals) for k, vals in rows.items()
        ], "1=缺失 / 0=齐备", note, source_ref))

    return specs


def render_chart(spec: ChartSpec, out_path: Path) -> Path:
    """按规格渲染一张静态 PNG。空值不入图；来源与单位写入图注。"""
    with _RENDER_LOCK:
        visualize.setup_chinese_font()
        fig, ax = plt.subplots(figsize=(9, 4.6))
        x = np.arange(len(spec.categories))
        right_axes: dict[str, object] = {}

        if spec.chart_type == "radar":
            plt.close(fig)
            return _render_radar(spec, out_path)
        if spec.chart_type == "heatmap":
            plt.close(fig)
            return _render_heatmap(spec, out_path)

        for s in spec.series:
            vals = _clean(s["values"])
            target = ax
            if s.get("axis") == "right":
                if "right" not in right_axes:
                    right_axes["right"] = ax.twinx()
                target = right_axes["right"]  # type: ignore[assignment]
            style = {"line": lambda: target.plot(x, vals, "o-", linewidth=2, label=s["name"]),
                     "area": lambda: (target.fill_between(x, np.nan_to_num(vals), alpha=0.35),
                                      target.plot(x, vals, "-", linewidth=2, label=s["name"])),
                     "bar": lambda: target.bar(x + _bar_offset(spec, s),
                                               np.nan_to_num(vals), width=0.8 / max(1, len(spec.series)),
                                               label=s["name"]),
                     "stacked_bar": None,
                     "waterfall": None}
            fn = style.get(spec.chart_type)
            if fn is not None:
                fn()

        if spec.chart_type == "stacked_bar":
            bottom = np.zeros(len(x))
            for s in spec.series:
                vals = np.nan_to_num(_clean(s["values"]))
                ax.bar(x, vals, bottom=bottom, label=s["name"])
                bottom += vals
        elif spec.chart_type == "waterfall":
            vals = _clean(spec.series[0]["values"])
            running = 0.0
            for i, v in enumerate(vals):
                if math.isnan(v):
                    continue
                if i == 0 or i == len(vals) - 1:
                    ax.bar(i, v, color="#4C78A8")
                else:
                    ax.bar(i, v, bottom=running, color="#E45756" if v < 0 else "#59A14F")
                    running += v

        ax.set_xticks(x)
        ax.set_xticklabels(spec.categories, rotation=0 if len(x) <= 8 else 40, ha="right" if len(x) > 8 else "center")
        ax.set_ylabel(spec.unit)
        ax.set_title(spec.title)
        ax.grid(alpha=0.25)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="upper left", fontsize=9)
        if "right" in right_axes:
            right_axes["right"].set_ylabel("倍 / 次")  # type: ignore[attr-defined]
        fig.text(0.01, 0.012, f"{spec.note}", fontsize=8, color="#666666")
        fig.tight_layout(rect=(0, 0.045, 1, 1))
        fig.savefig(out_path, dpi=config.CHART_DPI)
        plt.close(fig)
    return out_path


def _bar_offset(spec: ChartSpec, s: dict) -> float:
    """分组柱的横向偏移，避免多系列重叠。"""
    idx = spec.series.index(s)
    n = max(1, len(spec.series))
    return (idx - (n - 1) / 2) * (0.8 / n)


def _render_radar(spec: ChartSpec, out_path: Path) -> Path:
    visualize.setup_chinese_font()
    labels = spec.categories
    vals = _clean(spec.series[0]["values"])
    vals = np.nan_to_num(vals)
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    closed_v = list(vals) + [vals[0]]
    closed_a = angles + [angles[0]]
    fig = plt.figure(figsize=(6.2, 5.4))
    ax = fig.add_subplot(111, polar=True)
    ax.plot(closed_a, closed_v, "o-", linewidth=2)
    ax.fill(closed_a, closed_v, alpha=0.25)
    ax.set_xticks(angles)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1)
    ax.set_title(spec.title)
    fig.text(0.01, 0.012, spec.note, fontsize=8, color="#666666")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(out_path, dpi=config.CHART_DPI)
    plt.close(fig)
    return out_path


def _render_heatmap(spec: ChartSpec, out_path: Path) -> Path:
    visualize.setup_chinese_font()
    matrix = np.array([np.nan_to_num(_clean(s["values"])) for s in spec.series])
    fig, ax = plt.subplots(figsize=(9, max(2.6, 0.5 * len(spec.series) + 1.8)))
    ax.imshow(matrix, cmap="YlOrRd", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(spec.categories)))
    ax.set_xticklabels(spec.categories)
    ax.set_yticks(range(len(spec.series)))
    ax.set_yticklabels([s["name"] for s in spec.series], fontsize=9)
    ax.set_title(spec.title)
    fig.text(0.01, 0.012, spec.note, fontsize=8, color="#666666")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(out_path, dpi=config.CHART_DPI)
    plt.close(fig)
    return out_path
