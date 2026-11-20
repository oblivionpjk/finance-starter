"""A 股财务数据源适配器。

- mock：读 data/raw/ 下的离线快照，本机无条件可跑，也是端到端回归基线；
- akshare：在线抓新浪财经口径三大报表，免费源不稳定时由编排层转成明确错误。

新增数据源只需实现 FinancialSource 并 register_source()，编排层不改。
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd

from app import config

INDICATORS = (("利润表", "IS", "income"),
              ("资产负债表", "BS", "balance"),
              ("现金流量表", "CF", "cashflow"))


class FinancialSource(Protocol):
    name: str
    online: bool          # 是否依赖外部在线接口；自动补录简称表仅对在线源成功取数后触发

    def fetch(self, code: str) -> dict[str, pd.DataFrame]: ...


class LocalSnapshotMiss(Exception):
    """本地离线快照未收录该代码；与在线源故障区分，便于前端给出对应引导。"""

    def __init__(self, code: str, missing: list[str]) -> None:
        self.code = code
        self.missing = missing
        super().__init__(f"本地快照未收录 {code}：缺少 {', '.join(missing)}")


class OnlineCodeNotFound(Exception):
    """在线源按该代码查无三大报表（代码无效或已退市）。

    与「数据源故障」区分：前者重试无意义，需核对代码；后者可稍后重试。
    cause 保留底层异常类型，in_name_table 表示证券简称表是否收录该代码，
    两者供编排层生成面向用户的准确原因。
    """

    def __init__(self, code: str, cause: Exception, in_name_table: bool) -> None:
        self.code = code
        self.cause = cause
        self.in_name_table = in_name_table
        super().__init__(f"在线数据源查无 {code} 的财报（{type(cause).__name__}）")


def has_local_statements(code: str) -> bool:
    """该代码的三大报表是否都在本地快照中，供输入阶段预警使用。"""
    return all((config.RAW_DIR / f"{code}_{suffix}.csv").exists()
               for _, _, suffix in INDICATORS)


class MockFileSource:
    """离线快照源：结构与在线接口一致（报告日 × 科目宽表）。"""
    name = "mock"
    online = False
    label = "本地快照（离线）"

    def fetch(self, code: str) -> dict[str, pd.DataFrame]:
        out: dict[str, pd.DataFrame] = {}
        missing: list[str] = []
        for _, st, suffix in INDICATORS:
            path = config.RAW_DIR / f"{code}_{suffix}.csv"
            if not path.exists():
                missing.append(path.name)
                continue
            out[st] = pd.read_csv(path, dtype={"报告日": str})
        if missing:
            raise LocalSnapshotMiss(code, missing)
        return out


class AkShareSource:
    """在线免费源。接口字段可能变动，异常由编排层包装为结构化错误。"""
    name = "akshare"
    online = True
    label = "AKShare / 新浪财经（在线）"

    def fetch(self, code: str) -> dict[str, pd.DataFrame]:
        import akshare as ak
        symbol = f"sh{code}" if code.startswith("6") else f"sz{code}"
        out: dict[str, pd.DataFrame] = {}
        try:
            for indicator, st, _ in INDICATORS:
                out[st] = ak.stock_financial_report_sina(symbol=symbol, indicator=indicator)
        except Exception as exc:
            # akshare 对无效 / 退市代码拿到 result.data=None，内部读 report_date 时
            # 抛 TypeError: 'NoneType' object is not subscriptable。这是明确的
            # 「查无此股」信号；超时、连接失败等仍是数据源故障，交由编排层重试提示。
            if isinstance(exc, TypeError) and "NoneType" in str(exc):
                from app.services import names
                in_table = names.lookup(code) is not None
                raise OnlineCodeNotFound(code, exc, in_table) from exc
            raise
        return out


SOURCES: dict[str, FinancialSource] = {}


def register_source(source: FinancialSource) -> None:
    SOURCES[source.name] = source


def get_source(name: str | None = None) -> FinancialSource:
    key = name or config.DEFAULT_SOURCE
    if key not in SOURCES:
        raise KeyError(f"未注册的数据源：{key}；可用：{', '.join(SOURCES)}")
    return SOURCES[key]


def list_sources() -> list[dict[str, str]]:
    return [{"name": s.name, "label": getattr(s, "label", s.name)} for s in SOURCES.values()]


register_source(MockFileSource())
register_source(AkShareSource())
