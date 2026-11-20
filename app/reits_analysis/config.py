"""REITs 分析模块配置与「数据维度」注册表。

扩展点（本期只实现 quote 维度，其余维度留位）：
    1. 在 DIMENSIONS 中把目标维度 implemented 改为 True（或新增 DimensionSpec）；
    2. 写一个解析器，把新 Excel 解析成该维度的数据集，并调用
       parser.register_parser(dim_key, fn)；
    3. 可选：在 metrics.register_provider(dim_key, fn) 注册指标提供者，
       在 report.register_section(dim_key, fn) 注册报告章节提供者，
       在 charts.register_charts(dim_key, fn) 注册图片生成者。
    service / API / 页面均按 capabilities 与 datasets 动态渲染，无需改动。

所有口径写死为确定性规则，不做运行时猜测。
"""
from __future__ import annotations

from dataclasses import dataclass

# ── 重点标的与对标口径 ──
BENCHMARK_CODE = "508002"          # 华安百联消费 REIT
BENCHMARK_NAME = "华安百联消费REIT"
TRADING_DAYS_PER_YEAR = 252        # 年化波动率
YTD_BASE_MODE = "prev_year_last"   # 上年最后一个交易日；实测可复现集团报告 -19.25%
YTD_BASE_ALTERNATIVE = "first_day" # 可选：区间首个交易日

# ── 价格口径：系统固定标注，不再逐次人工确认 ──
# WIND 日行情模板的价格列只写「简称['代码]」，无口径字样；
# 按模板约定为未复权收盘价，并用集团报告披露的年初至今跌幅反算交叉验证（见报告第 5 节）。
PRICE_FIELD = "unadjusted_close"
PRICE_UNIT = "CNY"
PRICE_BASIS = {
    "field": PRICE_FIELD,
    "unit": PRICE_UNIT,
    "label": "未复权收盘价（元）",
    "source": "WIND 日行情导出模板：价格列表头仅标注「简称['代码]」，未写口径字样。",
    "basis": "按该模板约定解释为未复权收盘价；已用集团报告披露的年初至今跌幅对原始行情反算交叉验证，结果一致（见报告第 5 节）。",
    "extension": "WIND 换模板或改用其他数据源时，由新解析器在注册时声明口径，不恢复逐次确认。",
}

# ── 市场规则：WIND 表头代码前缀 ──
REIT_MARKET_PREFIXES = (
    ("SH", ("508", "509")),
    ("SZ", ("180", "181")),
)

# ── 解析规则 ──
CODE_HEADER_REGEX = r"\['(\d{6})"          # 例：华安百联消费REIT['508002]
SOURCE_NOTE_KEYWORDS = ("数据来源", "Source:", "source:")
MIN_COMMON_DAYS = 20                        # 公共窗口过短则告警
LISTING_DAY_AMOUNT_SPIKE_RATIO = 5.0        # 上市首日成交额 > 后续 10 日中位数的 N 倍 → info 标记
MAX_SHEETS = 40                             # 防御异常工作簿

# ── 集团报告对照值：人工摘录自 PDF 第三部分，仅用于差异说明，绝不参与计算 ──
PDF_REPORT_REFERENCE = {
    "as_of": "2026-11-16",
    "values": [
        {"code": BENCHMARK_CODE, "name": BENCHMARK_NAME, "field": "收盘价(元)",
         "report_value": 2.33, "note": "疑似基金净值/口径混淆或错填"},
        {"code": "180601", "name": "华夏华润消费REIT", "field": "收盘价(元)",
         "report_value": 4.00, "note": "疑似基金净值/口径混淆或错填"},
        {"code": BENCHMARK_CODE, "name": BENCHMARK_NAME, "field": "年初至今涨跌幅(%)",
         "report_value": -19.25, "note": "与 WIND 原值重算结果一致（四舍五入差异）"},
    ],
}

# ── 产物文件名（不含会话目录）──
ARTIFACT_PDF = "REITs行情分析报告.pdf"
ARTIFACT_QUALITY_JSON = "解析与质量报告.json"
CHART_FILES = {
    "price_trend": "price_trend.png",
    "ytd_return": "ytd_return.png",
    "since_listing": "since_listing.png",
    "close_price": "close_price.png",
    "vol_return_scatter": "vol_return_scatter.png",
    "drawdown": "drawdown.png",
    "liquidity": "liquidity.png",
    "corr_heatmap": "corr_heatmap.png",
}

# ── 上传约束 ──
ALLOWED_SUFFIXES = (".xls", ".xlsx")
MAX_UPLOAD_BYTES = 100 * 1024 * 1024   # WIND 导出的 .xls 实测约 38MB，远高于 A 股报表上限


@dataclass(frozen=True)
class DimensionSpec:
    """一类可分析的数据内容。implemented=False 表示已预留但尚无解析器。"""

    key: str
    label: str
    implemented: bool
    description: str
    expected_columns: tuple[str, ...]
    pending_reason: str = ""


DIMENSIONS: dict[str, DimensionSpec] = {
    "quote": DimensionSpec(
        key="quote", label="日频行情（收盘价 / 成交金额）", implemented=True,
        description="12 只消费 REIT 的日频价格与成交额，可完成走势、涨跌幅、波动、回撤、流动性、相关性对标。",
        expected_columns=("日期", "简称['代码]", "成交金额(百万元)['代码]"),
    ),
    "distribution": DimensionSpec(
        key="distribution", label="分派率 / 可供分配金额", implemented=False,
        description="年化现金分派率与分派率横向对比。",
        expected_columns=("代码", "可供分配金额", "报告期", "总份额"),
        pending_reason="本份 WIND Excel 无可供分配金额与总份额；需另传基金季报导出的 Excel。",
    ),
    "financial": DimensionSpec(
        key="financial", label="财务指标（营收 / EBITDA）", implemented=False,
        description="营业收入、EBITDA 及同比的横向对比。",
        expected_columns=("代码", "报告期", "营业收入", "EBITDA"),
        pending_reason="本份 WIND Excel 无财务字段；需另传基金季报导出的 Excel。",
    ),
    "operation": DimensionSpec(
        key="operation", label="运营指标（出租率 / 租金）", implemented=False,
        description="出租率、收缴率、租金单价的横向对比。",
        expected_columns=("代码", "报告期", "出租率", "收缴率", "租金单价"),
        pending_reason="本份 WIND Excel 无运营字段；需另传基金季报运营章节导出的 Excel。",
    ),
    "valuation": DimensionSpec(
        key="valuation", label="资产评估值", implemented=False,
        description="首发 / 2024 / 2025 估值及变化率对比。",
        expected_columns=("代码", "评估基准日", "评估值"),
        pending_reason="本份 WIND Excel 无评估字段；需另传评估报告导出的 Excel。",
    ),
    "index": DimensionSpec(
        key="index", label="大盘 / 指数对比序列", implemented=False,
        description="中证 REITs 全收益、沪深300、深证成指、国债指数对比曲线。",
        expected_columns=("日期", "指数名称", "收盘点位"),
        pending_reason="本份 WIND Excel 无指数序列；需另从 WIND 导出指数表。",
    ),
    "attachments": DimensionSpec(
        key="attachments", label="附加上传 Excel（结构概览）", implemented=True,
        description="任何未识别为专用维度的 Excel 都作为附加数据集保留，报告输出工作表结构与行数；具体指标待注册解析器后启用。",
        expected_columns=("任意表结构",),
    ),
}


def capability_payload() -> dict:
    """给前端的「已实现 / 可扩展」清单。"""
    return {
        "dimensions": [
            {
                "key": d.key, "label": d.label, "implemented": d.implemented,
                "description": d.description,
                "expected_columns": list(d.expected_columns),
                "pending_reason": d.pending_reason,
            }
            for d in DIMENSIONS.values()
        ],
        "benchmark": {"code": BENCHMARK_CODE, "name": BENCHMARK_NAME},
        "price_basis": dict(PRICE_BASIS),
        "allowed_suffixes": list(ALLOWED_SUFFIXES),
    }
