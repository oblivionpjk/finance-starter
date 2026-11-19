"""财务比率计算：偿债 / 盈利 / 营运 / 成长 / 现金流 + 杜邦分解。

所有函数返回以年份为索引的 Series，单位设为 -1 表示百分比，-2 表示倍数/次。
口径说明见 README「指标口径」一节。
"""
import pandas as pd

from .io_utils import item


def _div(a: pd.Series, b: pd.Series) -> pd.Series:
    """安全除法：分母为 0 时结果为 NaN，不抛异常。"""
    return a.div(b.replace(0, float("nan")))


def solvency(bs: pd.DataFrame, cf: pd.DataFrame) -> pd.DataFrame:
    """偿债能力。"""
    ca = item(bs, "流动资产合计")
    cl = item(bs, "流动负债合计")
    inv = item(bs, "存货")
    cash = item(bs, "货币资金")
    liab = item(bs, "负债合计")
    equity = item(bs, "所有者权益(或股东权益)合计")
    cfo = item(cf, "经营活动产生的现金流量净额")
    out = pd.DataFrame({
        "流动比率": _div(ca, cl),
        "速动比率": _div(ca - inv, cl),
        "现金比率": _div(cash, cl),
        "资产负债率": _div(liab, item(bs, "资产总计")),
        "产权比率": _div(liab, equity),
        "经营现金流/负债": _div(cfo, liab),
    })
    # 注：演示数据未单列利息费用，故不计算「利息保障倍数」
    return out


def profitability(inc: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """盈利能力。"""
    revenue = item(inc, "营业收入")
    net = item(inc, "净利润")
    out = pd.DataFrame({
        "毛利率": _div(revenue - item(inc, "营业成本"), revenue),
        "营业利润率": _div(item(inc, "营业利润"), revenue),
        "净利率": _div(net, revenue),
        "ROE(净资产收益率)": _div(net, item(bs, "所有者权益(或股东权益)合计")),
        "ROA(总资产收益率)": _div(net, item(bs, "资产总计")),
    })
    return out


def operation(inc: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """营运能力（周转次数）。平均余额用期初期末均值，首年无期初则退回期末。"""
    def avg(series: pd.Series) -> pd.Series:
        shifted = series.shift(1)
        first = series.index[0]
        shifted.loc[first] = series.loc[first]
        return (series + shifted) / 2

    revenue = item(inc, "营业收入")
    out = pd.DataFrame({
        "应收账款周转率": _div(revenue, avg(item(bs, "应收账款"))),
        "存货周转率": _div(item(inc, "营业成本"), avg(item(bs, "存货"))),
        "总资产周转率": _div(revenue, avg(item(bs, "资产总计"))),
    })
    return out


def growth(inc: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """成长能力（同比增速）。"""
    def yoy(series: pd.Series) -> pd.Series:
        return series.pct_change()

    out = pd.DataFrame({
        "营业收入增速": yoy(item(inc, "营业收入")),
        "净利润增速": yoy(item(inc, "净利润")),
        "总资产增速": yoy(item(bs, "资产总计")),
        "净资产增速": yoy(item(bs, "所有者权益(或股东权益)合计")),
    })
    out.iloc[0] = float("nan")  # 首年无同比基数
    return out


def cashflow(cf: pd.DataFrame, inc: pd.DataFrame) -> pd.DataFrame:
    """现金流质量。"""
    cfo = item(cf, "经营活动产生的现金流量净额")
    out = pd.DataFrame({
        "经营现金流净额": cfo,
        "净利润现金含量": _div(cfo, item(inc, "净利润")),
        "经营现金流/营收": _div(cfo, item(inc, "营业收入")),
    })
    return out


def dupont(inc: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """杜邦分解：ROE = 净利率 × 总资产周转率 × 权益乘数。"""
    net = item(inc, "净利润")
    revenue = item(inc, "营业收入")
    assets = item(bs, "资产总计")
    equity = item(bs, "所有者权益(或股东权益)合计")
    out = pd.DataFrame({
        "净利率": _div(net, revenue),
        "总资产周转率": _div(revenue, assets),
        "权益乘数": _div(assets, equity),
        "ROE(分解乘积)": _div(net, revenue) * _div(revenue, assets) * _div(assets, equity),
        "ROE(直接计算)": _div(net, equity),
    })
    return out


def summary(inc: pd.DataFrame, bs: pd.DataFrame, cf: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """汇总所有比率，返回 {类别: DataFrame}。"""
    return {
        "偿债能力": solvency(bs, cf),
        "盈利能力": profitability(inc, bs),
        "营运能力": operation(inc, bs),
        "成长能力": growth(inc, bs),
        "现金流": cashflow(cf, inc),
        "杜邦分解": dupont(inc, bs),
    }
