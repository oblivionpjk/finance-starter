"""标的身份校验：6 位代码 → 市场 + 证券类型口径。

当前仅启用沪深 A 股；其余市场规则已在 config.MARKET_RULES 预留，
启用后只需补对应数据源适配器，校验逻辑不改。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app import config
from app.errors import AnalysisError


@dataclass(frozen=True)
class SubjectInfo:
    code: str
    market: str
    market_label: str
    note: str
    statement_scope: str = "consolidated"


def resolve(code: str | None) -> SubjectInfo:
    value = (code or "").strip()
    if not re.fullmatch(r"\d{6}", value):
        raise AnalysisError("INVALID_CODE",
                            "股票代码必须是 6 位数字",
                            f"收到：{value!r}")
    for rule in config.MARKET_RULES:
        if value.startswith(rule.prefixes):
            if not rule.enabled:
                raise AnalysisError(
                    "MARKET_NOT_ENABLED",
                    f"{value} 属于{rule.label}，当前版本尚未开放",
                    "市场规则已在配置中预留，启用并接入数据源后即可支持",
                )
            return SubjectInfo(
                code=value, market=rule.code, market_label=rule.label,
                note=config.AMBIGUOUS_CODES.get(value, ""),
            )
    raise AnalysisError("UNKNOWN_MARKET",
                        f"无法识别 {value} 所属的沪深 A 股代码段",
                        "当前支持 600/601/603/605/688（沪市）与 000/001/002/003/300/301（深市）")
