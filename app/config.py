"""全局配置：表驱动的可扩展点，环境变量可覆盖。

扩展方式：
- 新增支持市场 → 在 MARKET_RULES 里把 enabled 改为 True（并补数据源适配器）；
- 新增上传格式 → 在 adapters/upload.py 注册解析器；
- 新增数据源 → 在 adapters/sources.py 注册 FinancialSource；
- 新增证券简称来源 → 在 services/names.py 注册 NameResolver；
- 新增报告格式 / 叙述器 / 存储后端 → 替换对应注册表里的实现。
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DEMO_DIR = DATA_DIR / "demo"
WEB_DIR = ROOT / "web"

TZ = ZoneInfo("Asia/Shanghai")


def env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def now() -> datetime:
    return datetime.now(TZ)


def now_str() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


# ── 留存策略：上传的原始报表只允许在当前页面会话内存在 ──
# 会话目录建在系统临时目录，不落在项目仓库，也不写数据库。
SESSION_ROOT = Path(env_str(
    "FINANCE_SESSION_ROOT",
    str(Path(tempfile.gettempdir()) / "finance-starter-sessions"),
))
SESSION_TTL_SECONDS = env_int("FINANCE_SESSION_TTL", 1800)      # 兜底过期清理
SESSION_SWEEP_SECONDS = env_int("FINANCE_SESSION_SWEEP", 60)

# ── 上传约束 ──
MAX_UPLOAD_BYTES = env_int("FINANCE_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
ALLOWED_UPLOAD_SUFFIXES = (".xlsx", ".xls", ".csv")

# ── 金额单位：内部一律存「元」，展示层统一换算为亿元 ──
AMOUNT_UNITS: dict[str, float] = {"元": 1.0, "万元": 1e4, "亿元": 1e8}
DEFAULT_UPLOAD_UNIT = "元"          # 页面显式选择，不做隐式假设
DISPLAY_UNIT = "亿元"
YI = 1e8

# ── 数据源与分析参数 ──
# mock：读 data/raw/ 下的离线快照（本机演示/回归，免费源不稳定时也能跑）
# akshare：在线抓取新浪财经口径三大报表
DEFAULT_SOURCE = env_str("FINANCE_SOURCE", "mock")
DEFAULT_PERIODS = env_int("FINANCE_DEFAULT_PERIODS", 10)
CHART_DPI = env_int("FINANCE_CHART_DPI", 150)
SERVER_HOST = env_str("FINANCE_HOST", "127.0.0.1")
SERVER_PORT = env_int("FINANCE_PORT", 8000)

# ── 证券简称：只用于展示，不参与任何指标计算 ──
# 本地快照覆盖沪深 A 股全表，离线可用且保证确定性模板报告逐字可复现；
# 查不到简称时只显示 6 位代码，绝不能阻断分析。
COMPANY_NAMES_PATH = Path(env_str(
    "FINANCE_COMPANY_NAMES", str(DATA_DIR / "company_names.json"),
))
# 本地表未命中时是否允许再查在线免费接口（默认关闭，避免免费源不稳定拖慢请求）。
NAME_ONLINE_FALLBACK = env_int("FINANCE_NAME_ONLINE_FALLBACK", 0)
# 自动补录：用在线源成功取到某代码财报、但本地简称表缺该代码时，
# 自动查在线简称并原子补写进本地全表（默认开启；仅在线源成功取数后触发）。
NAME_BACKFILL_ONLINE = env_int("FINANCE_NAME_BACKFILL_ONLINE", 1)

# ── 报告 ──
REPORT_TITLE = "财务分析报告"
NARRATOR = env_str("FINANCE_NARRATOR", "template")   # 当前只实现确定性模板
DISCLAIMER = (
    "本报告基于公开财报数据或用户上传数据与量化计算生成，仅供参考，不构成投资建议。"
    "市场有风险，投资需谨慎。上传数据由用户提供，系统未做外部核验。"
)


@dataclass(frozen=True)
class MarketRule:
    """证券市场规则。enabled=False 表示暂不开放，但规则已留好扩展位。"""
    code: str
    label: str
    prefixes: tuple[str, ...]
    enabled: bool = True


# 当前仅沪深 A 股；其余市场保留配置，启用后按数据源能力逐步放开。
MARKET_RULES: tuple[MarketRule, ...] = (
    MarketRule("SH", "上海证券交易所 A 股", ("600", "601", "603", "605", "688"), True),
    MarketRule("SZ", "深圳证券交易所 A 股", ("000", "001", "002", "003", "300", "301"), True),
    MarketRule("BJ", "北京证券交易所", ("43", "83", "87", "88"), False),
    MarketRule("SH_B", "沪市 B 股", ("900",), False),
    MarketRule("SZ_B", "深市 B 股", ("200",), False),
)

# 同一个 6 位数字串可能对应不同证券类型，需在报告与结果页显式说明核对口径。
AMBIGUOUS_CODES: dict[str, str] = {
    "000001": "该数字串既用于深市个股，也常被用作上证指数代码；本系统按沪深 A 股个股处理，"
              "并以「能否取得对应个股三大报表」作为二次确认。",
}
