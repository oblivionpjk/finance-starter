"""确定性洞察规则：阈值 + 趋势组合 → 结论标签。

只使用 AnalysisResult 里的数值，全部数字经 NumberRegistry 格式化，
不接语言模型、不做主观预测、不输出投资建议。
"""
from __future__ import annotations

import math

import pandas as pd

from app.domain.model import Insight, QualityIssue
from app.domain.numbers import NumberRegistry


def _v(df: pd.DataFrame, year: str, metric: str) -> float | None:
    try:
        value = df.loc[int(year), metric]
    except (KeyError, ValueError, TypeError):
        return None
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def build_insights(
    tables: dict[str, pd.DataFrame],
    frames: dict[str, pd.DataFrame],
    periods: list[str],
    quality: list[QualityIssue],
    reg: NumberRegistry,
) -> list[Insight]:
    out: list[Insight] = []
    if not periods:
        return out
    latest, prev = periods[-1], (periods[-2] if len(periods) > 1 else None)
    growth, prof = tables["成长能力"], tables["盈利能力"]
    solv, oper, cash, dupont = (tables["偿债能力"], tables["营运能力"],
                                tables["现金流"], tables["杜邦分解"])

    # 规模与增长
    rev = _v_frames(frames["IS"], "营业收入", latest)
    net = _v_frames(frames["IS"], "净利润", latest)
    rev_g, net_g = _v(growth, latest, "营业收入增速"), _v(growth, latest, "净利润增速")
    out.append(Insight(
        f"{latest} 年营业收入 {reg.amount(rev)}、净利润 {reg.amount(net)}；"
        f"同比增速分别为 {reg.pct(rev_g)} 与 {reg.pct(net_g)}。",
        refs=("营业收入", "净利润", "成长能力"),
    ))
    if prev and rev_g is not None and net_g is not None:
        if net_g > rev_g:
            out.append(Insight("净利润增速高于营业收入增速，利润弹性主要来自利润率或费用端变化。",
                               refs=("成长能力",)))
        elif net_g < 0 <= (rev_g or 0):
            out.append(Insight("营业收入增长但净利润同比下降，需关注成本、费用或减值项的影响。",
                               "warn", ("成长能力",)))

    # 盈利能力
    gm, nm, roe = (_v(prof, latest, "毛利率"), _v(prof, latest, "净利率"),
                   _v(prof, latest, "ROE(净资产收益率)"))
    out.append(Insight(
        f"盈利指标：毛利率 {reg.pct(gm)}、净利率 {reg.pct(nm)}、ROE {reg.pct(roe)}。",
        refs=("盈利能力",),
    ))
    if prev:
        gm_prev = _v(prof, prev, "毛利率")
        if gm is not None and gm_prev is not None:
            delta = gm - gm_prev
            word = "上升" if delta > 0 else "下降"
            out.append(Insight(f"毛利率较上年{word} {reg.pp(abs(delta))}。",
                               "warn" if delta < -0.03 else "info", ("盈利能力",)))

    # 偿债与资本结构
    dr, cr = _v(solv, latest, "资产负债率"), _v(solv, latest, "流动比率")
    out.append(Insight(f"资产负债率 {reg.pct(dr)}，流动比率 {reg.ratio(cr)}。",
                       refs=("偿债能力",)))
    if dr is not None and dr > 0.7:
        out.append(Insight("资产负债率高于 70%，杠杆水平偏高，偿债指标需结合行业特性判断。",
                           "warn", ("偿债能力",)))

    # 营运效率
    tat = _v(oper, latest, "总资产周转率")
    out.append(Insight(f"总资产周转率 {reg.ratio(tat)} 次。", refs=("营运能力",)))

    # 现金流质量
    cq = _v(cash, latest, "净利润现金含量")
    cfo = _v_frames(frames["CF"], "经营活动产生的现金流量净额", latest)
    out.append(Insight(f"经营活动现金流净额 {reg.amount(cfo)}，净利润现金含量 {reg.ratio(cq)}。",
                       refs=("现金流",)))
    if cq is not None and cq < 1:
        out.append(Insight("净利润现金含量低于 1，当期利润的现金回收弱于账面利润，需核查应收与存货变动。",
                           "warn", ("现金流",)))

    # 杜邦恒等性（分解乘积 vs 直接计算）
    d1, d2 = _v(dupont, latest, "ROE(分解乘积)"), _v(dupont, latest, "ROE(直接计算)")
    if d1 is not None and d2 is not None:
        diff = abs(d1 - d2)
        out.append(Insight(
            f"杜邦分解校验：分解乘积 {reg.pct(d1)}，直接计算 {reg.pct(d2)}，"
            f"差异 {reg.pct(diff)}。",
            "info" if diff < 1e-6 else "warn", ("杜邦分解",),
        ))

    # 数据质量条目转成可读提示
    for q in quality:
        if q.level == "warn":
            out.append(Insight(f"数据质量：{q.message}。", "warn", (q.code,)))
    return out


def _v_frames(frame: pd.DataFrame, label: str, year: str) -> float | None:
    try:
        value = frame.loc[label, int(year)]
    except (KeyError, ValueError, TypeError):
        return None
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)
