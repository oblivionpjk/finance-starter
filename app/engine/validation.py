"""校验网关：进入分析引擎前的强制关卡。

阻断项（block）：三表不齐、无共同年度期间、资产负债表不平衡、单位/币种不一致。
提示项（warn/info）：现金勾稽差异、核心科目缺失、期间被排除等。
"""
from __future__ import annotations

from app.domain.model import Dataset, QualityIssue

STATEMENTS = {"BS": "资产负债表", "IS": "利润表", "CF": "现金流量表"}


def validate(dataset: Dataset) -> list[QualityIssue]:
    issues: list[QualityIssue] = list(dataset.quality)

    for st, label in STATEMENTS.items():
        if not dataset.periods(st):
            issues.append(QualityIssue("block", "MISSING_STATEMENT",
                                       f"缺少{label}数据，无法进行分析",
                                       "请确认三张报表已全部上传或数据源返回完整"))

    sets = [set(dataset.periods(st)) for st in STATEMENTS]
    common = sorted(set.intersection(*sets)) if all(sets) else []
    if not common:
        issues.append(QualityIssue("block", "NO_COMMON_PERIOD",
                                   "三大报表没有共同的年度报告期",
                                   "跨期比较要求同一报告期、同一报表范围"))

    # 资产 = 负债 + 所有者权益（严格校验，容差随量级自适应）
    for p in common:
        assets = dataset.value("total_assets", p, "BS")
        total = dataset.value("total_liab_equity", p, "BS")
        liab = dataset.value("total_liab", p, "BS")
        equity = dataset.value("equity", p, "BS")
        if total is None and liab is not None and equity is not None:
            total = liab + equity
        if assets is None or total is None:
            issues.append(QualityIssue("warn", "BALANCE_UNVERIFIABLE",
                                       f"{p[:4]} 年缺少资产或负债权益科目，无法校验平衡",
                                       "资产总计 / 负债和所有者权益总计"))
            continue
        diff = assets - total
        tol = max(1.0, abs(assets) * 1e-6)
        if abs(diff) > tol:
            issues.append(QualityIssue("block", "BALANCE_MISMATCH",
                                       f"{p[:4]} 年资产总计与负债+权益相差 {diff:,.2f} 元",
                                       f"资产={assets:,.2f}，负债+权益={total:,.2f}；请检查报表或单位设置"))

    # 期末现金 vs 货币资金：真实财报常因受限资金不等，只提示不中断
    for p in common:
        end_cash = dataset.value("end_cash", p, "CF")
        cash = dataset.value("cash", p, "BS")
        if end_cash is None or cash is None:
            continue
        diff = end_cash - cash
        if abs(diff) > max(1.0, abs(cash) * 1e-6):
            issues.append(QualityIssue("info", "CASH_TIE_DIFF",
                                       f"{p[:4]} 年期末现金与货币资金相差 {diff:,.2f} 元",
                                       "货币资金可能含受限资金/保证金，属常见口径差异，仅作提示"))

    # 核心科目缺失：相关指标会是 NaN，需在报告里显式说明
    required = ("revenue", "net_profit", "total_assets", "total_liab", "equity", "cfo")
    missing = [
        f"{dic_label(key)}" for key in required
        if all(dataset.value(key, p, st) is None
               for p in common for st in (key_statement(key),))
    ]
    if missing:
        issues.append(QualityIssue("warn", "CORE_ITEM_MISSING",
                                   "部分核心科目缺失，相关指标将显示为「—」",
                                   "、".join(missing)))

    if has_block(issues):
        return issues
    issues.append(QualityIssue("info", "VALIDATION_PASSED",
                               f"校验通过：{len(common)} 个可比年度报告期",
                               "、".join(p[:4] for p in common)))
    return issues


def key_statement(key: str) -> str:
    return {"revenue": "IS", "net_profit": "IS", "cfo": "CF"}.get(key, "BS")


def dic_label(key: str) -> str:
    from app.domain.dictionary import BY_KEY
    return BY_KEY[key].label


def has_block(issues: list[QualityIssue]) -> bool:
    return any(i.level == "block" for i in issues)
