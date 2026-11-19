"""可视化：自动处理中文字体，产出趋势图与能力雷达图。"""
import matplotlib
matplotlib.use("Agg")  # 无窗口后端，服务器/脚本环境也能出图
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from . import config
from .io_utils import item


def setup_chinese_font() -> str:
    """从候选字体里挑第一个系统已安装的，返回字体名。"""
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in config.CN_FONTS:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    # 都找不到时保持默认（中文可能显示为方块，但图仍可产出）
    plt.rcParams["axes.unicode_minus"] = False
    return "default"


def plot_trend(inc, bs, cf, out_path=None) -> str:
    """收入 / 净利润 / 经营现金流 三年趋势 + 毛利率。"""
    setup_chinese_font()
    years = list(inc.columns)
    revenue = item(inc, "营业收入")
    net = item(inc, "净利润")
    cfo = item(cf, "经营活动产生的现金流量净额")
    margin = (revenue - item(inc, "营业成本")) / revenue

    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.plot(years, revenue, "o-", label="营业收入", linewidth=2)
    ax1.plot(years, net, "s-", label="净利润", linewidth=2)
    ax1.plot(years, cfo, "^-", label="经营现金流净额", linewidth=2)
    ax1.set_ylabel("金额（万元）")
    ax1.set_xlabel("年度")
    ax1.set_title("经营趋势（演示数据 · 虚构公司）")
    ax1.set_xticks(years)
    ax1.set_xticklabels([str(y) for y in years])
    ax1.grid(alpha=0.3)

    ax2 = ax1.twinx()
    ax2.plot(years, margin, "D--", color="tab:red", label="毛利率（右轴）", linewidth=2)
    ax2.set_ylabel("毛利率")
    ax2.set_ylim(0, 1)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    fig.tight_layout()

    out_path = out_path or config.TREND_PNG
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return str(out_path)


def plot_radar(ratio_summary: dict, year: int, out_path=None) -> str:
    """单年度五维能力雷达图（比率越大越好，已做正向化）。"""
    setup_chinese_font()
    prof = ratio_summary["盈利能力"]
    solv = ratio_summary["偿债能力"]
    oper = ratio_summary["营运能力"]
    grow = ratio_summary["成长能力"]

    # 各维度取一个代表性指标，并做量纲归一到 0-1（相对量，非绝对水平）
    # 比率表结构：行=年份，列=指标名，故用 .loc[年份, 指标]
    def val(df, metric):
        return float(df.loc[year, metric])

    raw = {
        "盈利": val(prof, "ROE(净资产收益率)"),
        "偿债": val(solv, "流动比率"),
        "营运": val(oper, "总资产周转率"),
        "成长": 0.0 if pd.isna(grow.loc[year, "营业收入增速"]) else val(grow, "营业收入增速"),
        "现金流": val(ratio_summary["现金流"], "净利润现金含量"),
    }
    # 用固定的经验上限归一，便于跨年可比
    caps = {"盈利": 0.30, "偿债": 4.0, "营运": 1.5, "成长": 0.30, "现金流": 2.0}
    vals = [min(raw[k] / caps[k], 1.0) for k in raw]
    labels = list(raw)
    angles = [i * 2 * 3.141592653589793 / len(labels) for i in range(len(labels))]
    vals_closed = vals + [vals[0]]
    angles_closed = angles + [angles[0]]

    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, polar=True)
    ax.plot(angles_closed, vals_closed, "o-", linewidth=2)
    ax.fill(angles_closed, vals_closed, alpha=0.25)
    ax.set_xticks(angles)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1)
    ax.set_title(f"{year} 年财务能力雷达（演示数据）")
    fig.tight_layout()

    out_path = out_path or config.RADAR_PNG
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return str(out_path)
