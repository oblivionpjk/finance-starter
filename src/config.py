"""项目路径与全局配置。所有路径基于本文件位置计算，换目录也能跑。"""
from pathlib import Path

# 项目根目录（src 的上一级）
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
DEMO_DIR = DATA_DIR / "demo"
RAW_DIR = DATA_DIR / "raw"
OUTPUT_DIR = ROOT / "output"
NOTEBOOK_DIR = ROOT / "notebooks"

# 演示数据文件
INCOME_CSV = DEMO_DIR / "income_statement.csv"
BALANCE_CSV = DEMO_DIR / "balance_sheet.csv"
CASHFLOW_CSV = DEMO_DIR / "cash_flow.csv"

# 输出文件
REPORT_XLSX = OUTPUT_DIR / "财务分析报告.xlsx"
TREND_PNG = OUTPUT_DIR / "趋势分析.png"
RADAR_PNG = OUTPUT_DIR / "能力雷达图.png"

# 中文字体候选（macOS / Windows / Linux 常见字体），绘图时自动挑选第一个可用的
CN_FONTS = [
    "PingFang SC", "Heiti SC", "Microsoft YaHei", "SimHei",
    "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Arial Unicode MS",
]

for _d in (OUTPUT_DIR, RAW_DIR):
    _d.mkdir(parents=True, exist_ok=True)
