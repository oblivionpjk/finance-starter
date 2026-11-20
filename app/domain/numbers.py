"""数字登记与一致性校验。

红线：报告里的每个数字都必须由分析引擎结果注入，叙述器/渲染器不得自己产生数字。
所有格式化数值都带小数点，结构数字（年份、章节号、页码）不带小数点，
因此校验器用「含小数点的数值 token」做确定性比对，不会误报也不会漏报。
"""
from __future__ import annotations

import math
import re

from app import config

SIGNIFICANT = re.compile(r"\d+\.\d+")


class NumberRegistry:
    """记录本次报告允许出现的全部数值 token。"""

    def __init__(self) -> None:
        self.tokens: set[str] = set()

    def _register(self, token: str) -> str:
        # 校验器抽取的是无符号数值（负号属于文本修饰），白名单同样去符号，
        # 否则 -0.26% 会登记 "-0.26" 而文本抽取 "0.26"，产生假阳性。
        self.tokens.add(token.lstrip("-"))
        return token

    def amount(self, value: float | None, digits: int = 2,
               unit: str = config.DISPLAY_UNIT) -> str:
        if value is None or _is_nan(value):
            return "—"
        return f"{self._register(f'{float(value):.{digits}f}')} {unit}"

    def pct(self, value: float | None, digits: int = 2) -> str:
        """输入为比值（0.15 → 15.00%）。"""
        if value is None or _is_nan(value):
            return "—"
        return f"{self._register(f'{float(value) * 100:.{digits}f}')}%"

    def ratio(self, value: float | None, digits: int = 2) -> str:
        if value is None or _is_nan(value):
            return "—"
        return self._register(f"{float(value):.{digits}f}")

    def pp(self, value: float | None, digits: int = 2) -> str:
        """百分点变化，输入为比值差。"""
        if value is None or _is_nan(value):
            return "—"
        return f"{self._register(f'{float(value) * 100:.{digits}f}')} 个百分点"

    def literal(self, token: str) -> str:
        return self._register(token)


def _is_nan(value: object) -> bool:
    try:
        return bool(math.isnan(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def verify(document, registry: NumberRegistry) -> tuple[bool, list[str]]:
    """返回 (是否全部可溯源, 未登记数值列表)。"""
    found = set(SIGNIFICANT.findall(document.all_text()))
    unknown = sorted(found - registry.tokens)
    return not unknown, unknown
