"""数据加载与勾稽校验。

全项目统一使用真实财报的原始结构：CSV 是「报告日 × 科目」宽表（新浪财经口径），
金额单位为元。演示数据与 akshare 拉取的真实数据格式完全相同，共用同一套加载逻辑，
不存在字段映射/适配层。加载函数把它转成分析所需的「科目 × 年份」结构。
"""
from pathlib import Path

import pandas as pd

from . import config

# 不同行业标准科目名差异：加载时归一到统一口径（标准名 → 候选列名，按优先级）。
# 一般企业用「所有者权益(或股东权益)…」，金融业用「股东权益 / 归属于母公司股东的权益」
# 与「负债及股东权益总计」。取第一个存在且数值非空的候选，保证跨行业可比。
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "所有者权益(或股东权益)合计": (
        "所有者权益(或股东权益)合计", "股东权益", "归属于母公司股东的权益",
    ),
    "负债和所有者权益(或股东权益)总计": (
        "负债和所有者权益(或股东权益)总计", "负债及股东权益总计",
    ),
}

# 新浪接口附带的元数据列，非财务科目，转置前剔除
META_COLUMNS = ("数据源", "是否审计", "公告日期", "币种", "类型", "更新日期")

# 分析模块所需的核心科目。不同行业报表科目集合不同（如银行无「流动资产合计」），
# 统一补齐这些行为 NaN，保证所有来源暴露同一科目视图、比率模块不会因缺列报错。
# 不伪造数值：缺失科目的比率自然为 NaN。
CORE_ITEMS = (
    "营业收入", "营业成本", "营业利润", "净利润",
    "货币资金", "应收账款", "存货", "流动资产合计", "资产总计",
    "流动负债合计", "负债合计", "所有者权益(或股东权益)合计",
    "负债和所有者权益(或股东权益)总计",
    "经营活动产生的现金流量净额", "期末现金及现金等价物余额",
)


def load_statement(path: Path | str) -> pd.DataFrame:
    """读一张「报告日 × 科目」宽表，转成「科目 × 年份」结构。

    - 只保留年报（报告日以 1231 结尾）；同一年多条取最后一条；
    - 报告日前 4 位作为年份；列名做行业别名归一；剔除元数据列；
    - 返回 index=科目、columns=年份（int）、值为数值（元）的 DataFrame。
    """
    raw = pd.read_csv(path, dtype={"报告日": str})
    annual = raw[raw["报告日"].str.endswith("1231")].copy()
    if annual.empty:
        raise ValueError(f"{Path(path).name} 中没有年报数据（报告日以 1231 结尾）")

    annual["年份"] = annual["报告日"].str[:4].astype(int)
    annual = annual.drop_duplicates(subset="年份", keep="last").set_index("年份")
    annual = annual.sort_index()
    annual = annual.drop(columns=[c for c in META_COLUMNS if c in annual.columns])

    # 行业科目归一：对每个标准名，挑「存在且数值非空」最多的候选列；
    # 收集到字典后一次性 concat，避免逐列插入导致 DataFrame 碎片化。
    add: dict[str, pd.Series] = {}
    drop: list[str] = []
    for standard, candidates in COLUMN_ALIASES.items():
        present = [c for c in candidates if c in annual.columns]
        if not present:
            continue
        chosen = max(present, key=lambda c: pd.to_numeric(annual[c], errors="coerce").notna().sum())
        if standard != chosen:
            drop.append(chosen)
            add[standard] = pd.to_numeric(annual[chosen], errors="coerce")
    if drop:
        annual = annual.drop(columns=drop)
    if add:
        annual = pd.concat([annual, pd.DataFrame(add)], axis=1)

    out = annual.T.apply(pd.to_numeric, errors="coerce").astype(float)
    # 补齐核心科目（缺失填 NaN，不伪造数据），保持原有科目顺序在前
    for name in CORE_ITEMS:
        if name not in out.index:
            out.loc[name] = float("nan")
    out.index.name = "项目"
    return out


def item(df: pd.DataFrame, name: str) -> pd.Series:
    """取单个报表项目，找不到时给出清晰报错。"""
    if name not in df.index:
        raise KeyError(f"报表中没有项目「{name}」；可用项目：{list(df.index)}")
    return df.loc[name]


def check_balance_identity(bs: pd.DataFrame) -> pd.DataFrame:
    """校验「资产 = 负债 + 所有者权益」，返回逐年差额表。"""
    total = item(bs, "负债和所有者权益(或股东权益)总计")
    diff = item(bs, "资产总计") - total
    result = pd.DataFrame({
        "资产总计": item(bs, "资产总计"),
        "负债+权益": total,
        "差额(应为0)": diff,
    })
    result["是否平衡"] = result["差额(应为0)"].abs().lt(1e-6)
    return result


def check_cash_ties(cf: pd.DataFrame, bs: pd.DataFrame) -> pd.DataFrame:
    """校验现金流量表期末现金 = 资产负债表货币资金。"""
    result = pd.DataFrame({
        "期末现金(现金流量表)": item(cf, "期末现金及现金等价物余额"),
        "货币资金(资产负债表)": item(bs, "货币资金"),
    })
    result["差额(应为0)"] = result["期末现金(现金流量表)"] - result["货币资金(资产负债表)"]
    result["是否一致"] = result["差额(应为0)"].abs().lt(1e-6)
    return result


def load_all(source: str = "demo", code: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """一次性加载三大报表，演示数据与真实数据走完全相同的路径。

    source="demo"：读 data/demo/ 下的演示数据；
    source="real"：读 data/raw/{code}_*.csv，code 为 6 位股票代码。
    """
    if source == "demo":
        paths = (config.DEMO_DIR / "income_statement.csv",
                 config.DEMO_DIR / "balance_sheet.csv",
                 config.DEMO_DIR / "cash_flow.csv")
    elif source == "real":
        if not code:
            raise ValueError("source='real' 时必须提供股票代码 code")
        paths = (config.RAW_DIR / f"{code}_income.csv",
                 config.RAW_DIR / f"{code}_balance.csv",
                 config.RAW_DIR / f"{code}_cashflow.csv")
        missing = [p.name for p in paths if not p.exists()]
        if missing:
            raise FileNotFoundError(f"缺少真实数据 {', '.join(missing)}，请先运行 fetch_akshare.py {code}")
    else:
        raise ValueError(f"未知数据源：{source}，应为 'demo' 或 'real'")

    return tuple(load_statement(p) for p in paths)
