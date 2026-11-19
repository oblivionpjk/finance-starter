"""数据加载与勾稽校验。"""
from os import PathLike

import pandas as pd
from . import config


def load_statement(path: PathLike) -> pd.DataFrame:
    """读取一张报表 CSV：第一列为项目名，其余列为期间（年份）。"""
    df = pd.read_csv(path, dtype={"项目": str})
    df = df.set_index("项目")
    # 列名是年份（字符串），转成整数索引便于排序
    df.columns = [int(c) for c in df.columns]
    df = df.sort_index(axis=1)
    return df.astype(float)


def item(df: pd.DataFrame, name: str) -> pd.Series:
    """取单个报表项目，找不到时给出清晰报错。"""
    if name not in df.index:
        raise KeyError(f"报表中没有项目「{name}」；可用项目：{list(df.index)}")
    return df.loc[name]


def check_balance_identity(bs: pd.DataFrame) -> pd.DataFrame:
    """校验「资产 = 负债 + 所有者权益」，返回逐年差额表。"""
    diff = item(bs, "资产总计") - item(bs, "负债和所有者权益总计")
    result = pd.DataFrame({
        "资产总计": item(bs, "资产总计"),
        "负债+权益": item(bs, "负债和所有者权益总计"),
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


def load_all() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """一次性加载演示三大报表。"""
    return (
        load_statement(config.INCOME_CSV),
        load_statement(config.BALANCE_CSV),
        load_statement(config.CASHFLOW_CSV),
    )
