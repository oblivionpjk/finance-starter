#!/usr/bin/env python3
"""环境自检：确认依赖、字体、路径都就绪。装完依赖先跑这个。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

print("Python:", sys.version.split()[0])

required = {
    "pandas": "pandas",
    "numpy": "numpy",
    "matplotlib": "matplotlib",
    "openpyxl": "openpyxl",
}
optional = {"akshare": "akshare"}

all_required_ok = True
for label, mod in required.items():
    try:
        m = __import__(mod)
        print(f"  ✓ {label:<12} {getattr(m, '__version__', 'ok')}  (必需)")
    except Exception as e:
        print(f"  ✗ {label:<12} 未安装（{e.__class__.__name__}）  (必需)")
        all_required_ok = False

for label, mod in optional.items():
    try:
        m = __import__(mod)
        print(f"  ✓ {label:<12} {getattr(m, '__version__', 'ok')}  (可选)")
    except Exception:
        print(f"  - {label:<12} 未安装  (可选，拉真实数据才需要)")

try:
    from src import config
    print("  ✓ 项目路径      ", config.ROOT)
except Exception as e:
    print("  ✗ 项目路径导入失败", e)
    all_required_ok = False

print("\n结论：", "环境就绪 ✓" if all_required_ok else "有必需依赖缺失，请看 README 安装")
sys.exit(0 if all_required_ok else 1)
