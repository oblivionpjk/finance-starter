#!/usr/bin/env python3
"""主入口：加载演示三大报表 → 勾稽校验 → 算比率 → 出图 → 出 Excel 报告。

用法（在项目根目录）：
    .venv/bin/python scripts/run_demo_analysis.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config, ratios, reports, visualize
from src.io_utils import load_all, check_balance_identity, check_cash_ties

YI = 1e8  # 元 → 亿元
UNIT = "亿元"


def hr(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main():
    hr("① 加载演示数据（虚构公司，与真实财报同结构，单位元）")
    inc_y, bs_y, cf_y = load_all(source="demo")
    print(f"利润表 {inc_y.shape}，资产负债表 {bs_y.shape}，现金流量表 {cf_y.shape}")
    print(f"年度：{list(inc_y.columns)}")

    hr("② 勾稽校验")
    bal = check_balance_identity(bs_y)
    cash = check_cash_ties(cf_y, bs_y)
    print(bal.to_string())
    print()
    print(cash.to_string())
    assert bal["是否平衡"].all(), "资产负债表不平衡！"
    assert cash["是否一致"].all(), "期末现金与货币资金不一致！"
    print("✓ 全部勾稽通过")

    hr("③ 换算金额单位（元 → 亿元）")
    inc, bs, cf = inc_y / YI, bs_y / YI, cf_y / YI
    print(f"比率为比值不受影响；报告与图表金额以「{UNIT}」展示。")

    hr("④ 财务比率")
    summary = ratios.summary(inc, bs, cf)
    for name, df in summary.items():
        print(f"\n--- {name} ---")
        print(df.round(4).to_string())

    hr("⑤ 绘制图表")
    font = visualize.setup_chinese_font()
    print(f"中文字体：{font}")
    print("趋势图：", visualize.plot_trend(inc, bs, cf, amount_unit=UNIT))
    last_year = inc.columns[-1]
    print("雷达图：", visualize.plot_radar(summary, last_year))

    hr("⑥ 生成 Excel 报告")
    print("报告：", reports.build_report(inc, bs, cf, summary, amount_unit=UNIT))

    hr("完成 ✓")
    print(f"所有产物在：{config.OUTPUT_DIR}")


if __name__ == "__main__":
    main()
