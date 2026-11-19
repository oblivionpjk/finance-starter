#!/usr/bin/env python3
"""按需：用 AKShare 拉 A 股上市公司真实财务数据，落到 data/raw/。

这是「进阶」脚本，入门分析不必依赖它。免费接口可能变动或限流，
失败时会给出明确提示，不会影响演示分析流程。

用法：
    .venv/bin/python scripts/fetch_akshare.py 600519
    .venv/bin/python scripts/fetch_akshare.py 000001
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import config


def fetch(code: str) -> int:
    try:
        import akshare as ak
    except ImportError:
        print("未安装 akshare，请运行：.venv/bin/python -m pip install akshare")
        return 2

    # 新浪接口用带市场前缀的代码：6 开头为沪市 sh，其余为深市 sz
    symbol = f"sh{code}" if code.startswith("6") else f"sz{code}"
    print(f"正在拉取 {code} 的财务数据（数据源可能变动，失败请稍后重试）...")
    pulled = 0
    # 新版 akshare 签名：stock_financial_report_sina(symbol=代码, indicator=报表名)
    for indicator, filename, label in (
        ("利润表", "income", "利润表"),
        ("资产负债表", "balance", "资产负债表"),
        ("现金流量表", "cashflow", "现金流量表"),
    ):
        try:
            df = ak.stock_financial_report_sina(symbol=symbol, indicator=indicator)
            df.to_csv(config.RAW_DIR / f"{code}_{filename}.csv", index=False, encoding="utf-8-sig")
            print(f"  ✓ {label} {df.shape} → data/raw/{code}_{filename}.csv")
            pulled += 1
        except Exception as e:
            print(f"  ✗ {label}拉取失败：{e}")

    print(f"\n共拉取 {pulled}/3 张表，文件在 {config.RAW_DIR}")
    print("提示：真实报表字段与演示数据不同，套用比率模块前需先做字段映射。")
    return 0 if pulled else 1


if __name__ == "__main__":
    code = sys.argv[1].strip() if len(sys.argv) > 1 else "600519"
    sys.exit(fetch(code))
