#!/usr/bin/env python3
"""读取 AKShare 拉取的真实财报，跑完整分析流程并产出图表 + Excel 报告。

与 run_demo_analysis.py 的区别仅在数据源（data/raw/ 而非 data/demo/）与产物文件名前缀。
演示数据与真实财报结构完全相同，共用 src/io_utils.py 的加载与分析模块，无适配层。
  - 金额从「元」换算成「亿元」展示（比率是比值，不受单位影响）；
  - 真实财报「期末现金 ≠ 货币资金」属正常口径差异，只提示不中断；
  - 产物加股票代码前缀，避免覆盖演示分析的结果。

用法（在项目根目录）：
    .venv/bin/python scripts/run_real_analysis.py                # 默认 600519，近 10 年
    .venv/bin/python scripts/run_real_analysis.py 000001         # 指定股票代码
    .venv/bin/python scripts/run_real_analysis.py 600519 -n 5    # 只看近 5 年
    .venv/bin/python scripts/run_real_analysis.py 600519 --all   # 看全部年份

若 data/raw/ 还没有该股票数据，先执行：
    .venv/bin/python scripts/fetch_akshare.py 600519
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config, ratios, reports, visualize
from src.io_utils import load_all, check_balance_identity, check_cash_ties

YI = 1e8  # 元 → 亿元
UNIT = "亿元"


def hr(title: str):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def parse_args():
    p = argparse.ArgumentParser(description="真实财报数据分析（数据需先用 fetch_akshare.py 拉取）")
    p.add_argument("code", nargs="?", default="600519", help="6 位股票代码，默认 600519 贵州茅台")
    p.add_argument("-n", "--years", type=int, default=10, help="展示最近 N 年，默认 10")
    p.add_argument("--all", action="store_true", help="展示全部年份（覆盖 -n）")
    return p.parse_args()


def check_raw_files(code: str) -> bool:
    """确认三张原始报表都在，缺失则给出明确指引。"""
    needed = [config.RAW_DIR / f"{code}_{s}.csv" for s in ("income", "balance", "cashflow")]
    missing = [f.name for f in needed if not f.exists()]
    if missing:
        print(f"✗ 缺少真实数据文件：{', '.join(missing)}")
        print(f"请先执行：.venv/bin/python scripts/fetch_akshare.py {code}")
        return False
    return True


def main() -> int:
    args = parse_args()
    code = args.code.strip()
    if not check_raw_files(code):
        return 1

    hr(f"① 加载真实数据 {code}（新浪财报 · 来源 data/raw/）")
    try:
        inc_y, bs_y, cf_y = load_all(source="real", code=code)  # 原始单位：元
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"✗ 数据加载失败：{e}")
        return 1
    print(f"利润表 {inc_y.shape}，资产负债表 {bs_y.shape}，现金流量表 {cf_y.shape}")
    all_years = sorted(set(inc_y.columns) & set(bs_y.columns) & set(cf_y.columns))
    years = all_years if args.all else all_years[-args.years:]
    print(f"三表共有年份 {len(all_years)} 个（{all_years[0]}–{all_years[-1]}），本次展示 {len(years)} 年：{years}")

    hr("② 勾稽校验")
    bal = check_balance_identity(bs_y)
    cash = check_cash_ties(cf_y, bs_y)
    print("资产负债表：资产 = 负债 + 所有者权益")
    print(bal.loc[years].to_string())
    assert bal["是否平衡"].all(), "✗ 资产负债表不平衡，数据可能有误！"
    print("✓ 资产负债表全部平衡")
    print("\n现金流量表期末现金 vs 资产负债表货币资金")
    print(cash.loc[years].to_string())
    print("提示：真实财报「期末现金及现金等价物」通常不等于「货币资金」")
    print("      （货币资金含受限资金/保证金等），此为正常口径差异，不影响比率分析。")

    hr("③ 换算金额单位（元 → 亿元）")
    inc = inc_y / YI
    bs = bs_y / YI
    cf = cf_y / YI
    print(f"比率是比值，单位换算不影响结果；报告与图表金额以「{UNIT}」展示。")

    hr("④ 财务比率（展示最近若干年）")
    summary = ratios.summary(inc, bs, cf)
    for name, df in summary.items():
        print(f"\n--- {name} ---")
        print(df.loc[years].round(4).to_string())

    hr("⑤ 绘制图表")
    font = visualize.setup_chinese_font()
    print(f"中文字体：{font}")
    trend_path = config.OUTPUT_DIR / f"{code}_趋势分析.png"
    radar_path = config.OUTPUT_DIR / f"{code}_能力雷达图.png"
    print("趋势图：", visualize.plot_trend(
        inc, bs, cf, out_path=trend_path, years=years,
        title=f"{code} 经营趋势（{UNIT}）", amount_unit=UNIT,
    ))
    print("雷达图：", visualize.plot_radar(
        summary, years[-1], out_path=radar_path, title=f"{code} {years[-1]} 年财务能力雷达",
    ))

    hr("⑥ 生成 Excel 报告")
    report_path = config.OUTPUT_DIR / f"{code}_财务分析报告.xlsx"
    print("报告：", reports.build_report(
        inc, bs, cf, summary, out_path=report_path, amount_unit=UNIT,
    ))

    hr("完成 ✓")
    print(f"所有产物在：{config.OUTPUT_DIR}（均带 {code} 前缀，未覆盖演示数据）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
