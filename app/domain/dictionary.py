"""标准科目词典：别名归一、置信度映射、到现有 ratios.py 的 legacy 名称映射。

设计要点：
- item_key 是引擎唯一识别的编码；label 是标准中文名；legacy 是 src/ratios.py
  期望的科目名（保持不变，使 26 项指标可原样复用）。
- 行业科目差异通过 aliases 处理；口径不同的科目（如营业总收入 vs 营业收入、
  归母净利润 vs 净利润）绝不互相归并。
- 新增科目 / 行业只需加一条 ItemSpec，不改分析引擎。
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ItemSpec:
    key: str
    label: str
    legacy: str                 # "" 表示现有比率引擎不使用该科目
    statement: str              # BS / IS / CF
    aliases: tuple[str, ...] = ()


ITEMS: tuple[ItemSpec, ...] = (
    # ── 利润表 ──
    ItemSpec("total_revenue", "营业总收入", "", "IS", ("营业总收入", "总收入")),
    ItemSpec("revenue", "营业收入", "营业收入", "IS", ("营业收入", "主营业务收入")),
    ItemSpec("cogs", "营业成本", "营业成本", "IS", ("营业成本", "主营业务成本")),
    ItemSpec("selling_exp", "销售费用", "", "IS", ("销售费用", "营业费用")),
    ItemSpec("admin_exp", "管理费用", "", "IS", ("管理费用",)),
    ItemSpec("finance_exp", "财务费用", "", "IS", ("财务费用",)),
    ItemSpec("rd_exp", "研发费用", "", "IS", ("研发费用",)),
    ItemSpec("operating_profit", "营业利润", "营业利润", "IS", ("营业利润",)),
    ItemSpec("total_profit", "利润总额", "", "IS", ("利润总额",)),
    ItemSpec("tax_exp", "所得税费用", "", "IS", ("所得税费用", "减:所得税", "减：所得税")),
    ItemSpec("net_profit", "净利润", "净利润", "IS", ("净利润", "五、净利润")),
    ItemSpec("parent_net_profit", "归母净利润", "", "IS",
             ("归属于母公司所有者的净利润", "归属于母公司的净利润",
              "归属于母公司股东的净利润", "归属于母公司所有者权益的净利润")),
    # ── 资产负债表 ──
    ItemSpec("cash", "货币资金", "货币资金", "BS", ("货币资金",)),
    ItemSpec("ar", "应收账款", "应收账款", "BS", ("应收账款",)),
    ItemSpec("inventory", "存货", "存货", "BS", ("存货",)),
    ItemSpec("current_assets", "流动资产合计", "流动资产合计", "BS",
             ("流动资产合计", "流动资产总计")),
    ItemSpec("total_assets", "资产总计", "资产总计", "BS",
             ("资产总计", "资产合计", "资产总额")),
    ItemSpec("current_liab", "流动负债合计", "流动负债合计", "BS",
             ("流动负债合计", "流动负债总计")),
    ItemSpec("total_liab", "负债合计", "负债合计", "BS", ("负债合计", "负债总计")),
    ItemSpec("equity", "所有者权益合计", "所有者权益(或股东权益)合计", "BS",
             ("所有者权益(或股东权益)合计", "所有者权益合计", "股东权益合计",
              "股东权益", "所有者权益")),
    ItemSpec("total_liab_equity", "负债和所有者权益总计",
             "负债和所有者权益(或股东权益)总计", "BS",
             ("负债和所有者权益(或股东权益)总计", "负债及股东权益总计",
              "负债与所有者权益总计", "负债和所有者权益总计", "负债及所有者权益总计")),
    ItemSpec("parent_equity", "归母股东权益", "", "BS",
             ("归属于母公司股东权益合计", "归属于母公司所有者权益合计")),
    # 常见但当前指标不使用的科目：纳入词典以避免映射确认页出现噪音，同时保留事实供扩展。
    ItemSpec("fixed_assets", "固定资产", "", "BS",
             ("固定资产", "固定资产合计", "固定资产净额")),
    ItemSpec("intangible_assets", "无形资产", "", "BS", ("无形资产",)),
    ItemSpec("retained_earnings", "未分配利润", "", "BS", ("未分配利润",)),
    # ── 现金流量表 ──
    ItemSpec("cfo", "经营活动产生的现金流量净额", "经营活动产生的现金流量净额", "CF",
             ("经营活动产生的现金流量净额", "经营活动现金流量净额")),
    ItemSpec("cfi", "投资活动产生的现金流量净额", "", "CF",
             ("投资活动产生的现金流量净额", "投资活动现金流量净额")),
    ItemSpec("cff", "筹资活动产生的现金流量净额", "", "CF",
             ("筹资活动产生的现金流量净额", "筹资活动现金流量净额")),
    ItemSpec("net_cash_increase", "现金及现金等价物净增加额", "", "CF",
             ("现金及现金等价物净增加额",)),
    ItemSpec("begin_cash", "期初现金及现金等价物余额", "", "CF",
             ("期初现金及现金等价物余额",)),
    ItemSpec("end_cash", "期末现金及现金等价物余额", "期末现金及现金等价物余额", "CF",
             ("期末现金及现金等价物余额",)),
)

# 与 src/io_utils.py CORE_ITEMS 完全一致：legacy 视图必须补齐这些行，
# 否则 ratios.py 的 item() 会抛 KeyError。缺值一律 NaN，不伪造数据。
CORE_LEGACY_ITEMS: tuple[str, ...] = (
    "营业收入", "营业成本", "营业利润", "净利润",
    "货币资金", "应收账款", "存货", "流动资产合计", "资产总计",
    "流动负债合计", "负债合计", "所有者权益(或股东权益)合计",
    "负债和所有者权益(或股东权益)总计",
    "经营活动产生的现金流量净额", "期末现金及现金等价物余额",
)

# 新浪接口与用户表格里的元数据列，不是财务科目。
META_LABELS: frozenset[str] = frozenset({
    "报告日", "报告日期", "日期", "报表日期", "公告日期", "会计期间",
    "币种", "类型", "数据源", "是否审计", "更新日期", "单位", "序号", "备注",
    "项目", "科目", "科目名称", "项目名称", "指标", "报告期",
})

ROLE_HINTS: dict[str, tuple[str, ...]] = {
    "BS": ("资产总计", "负债合计", "所有者权益", "流动资产", "货币资金", "股东权益", "存货"),
    "IS": ("营业收入", "营业成本", "净利润", "营业利润", "利润总额", "销售费用"),
    "CF": ("经营活动产生的现金流量净额", "投资活动产生的现金流量净额",
           "筹资活动产生的现金流量净额", "期末现金及现金等价物余额"),
}

# 低置信度自动采纳阈值；低于此值必须由用户在映射确认页指定。
AUTO_ACCEPT_THRESHOLD = 0.88
SUGGEST_THRESHOLD = 0.45
IMPORTANT_LABEL_WORDS = ("收入", "利润", "资产", "负债", "现金", "权益", "费用", "成本", "存货")

BY_KEY: dict[str, ItemSpec] = {s.key: s for s in ITEMS}
LEGACY_BY_KEY: dict[str, str] = {s.key: s.legacy for s in ITEMS if s.legacy}


def normalize_label(raw: object) -> str:
    """统一全半角、空白与常见前缀，便于精确/模糊匹配。"""
    s = str(raw).strip()
    s = s.replace("（", "(").replace("）", ")").replace("：", ":").replace(" ", "")
    s = re.sub(r"^(其中:?|减:?|加:?|[一二三四五六七八九十][、.])", "", s)
    s = re.sub(r"\((元|万元|千元|亿元)\)$", "", s)
    return s


_INDEX: dict[str, ItemSpec] = {}
for _spec in ITEMS:
    for _alias in (_spec.label, *_spec.aliases):
        _INDEX[normalize_label(_alias)] = _spec
_INDEX_NORMS = tuple(_INDEX)


def map_label(raw: object) -> tuple[str | None, float, str]:
    """返回 (item_key, confidence, 匹配到的标准名)。元数据列返回 (None, 0, 'meta')。"""
    norm = normalize_label(raw)
    if not norm or norm in META_LABELS:
        return None, 0.0, "meta"
    spec = _INDEX.get(norm)
    if spec is not None:
        return spec.key, 1.0, norm
    close = difflib.get_close_matches(norm, _INDEX_NORMS, n=1, cutoff=AUTO_ACCEPT_THRESHOLD)
    if close:
        matched = close[0]
        ratio = difflib.SequenceMatcher(None, norm, matched).ratio()
        return _INDEX[matched].key, round(ratio, 3), matched
    return None, 0.0, ""


def suggest(raw: object, limit: int = 3) -> list[dict[str, object]]:
    """给映射确认页的候选标准科目（不自动采纳）。"""
    norm = normalize_label(raw)
    if not norm or norm in META_LABELS:
        return []
    matches = difflib.get_close_matches(norm, _INDEX_NORMS, n=limit, cutoff=SUGGEST_THRESHOLD)
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for m in matches:
        spec = _INDEX[m]
        if spec.key in seen:
            continue
        seen.add(spec.key)
        out.append({
            "item_key": spec.key,
            "label": spec.label,
            "score": round(difflib.SequenceMatcher(None, norm, m).ratio(), 3),
        })
    return out


def guess_role(labels: list[object]) -> str:
    """按科目特征词给文件推测报表角色，返回结果由用户在页面确认。"""
    norms = [normalize_label(x) for x in labels]
    scores = {role: sum(1 for w in words if any(w in n for n in norms))
              for role, words in ROLE_HINTS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "BS"


def is_important_label(raw: object) -> bool:
    """只把可能关键的低置信科目暴露到确认页，避免几百条噪音。"""
    s = normalize_label(raw)
    return any(w in s for w in IMPORTANT_LABEL_WORDS)
