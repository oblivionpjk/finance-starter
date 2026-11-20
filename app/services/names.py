"""证券简称解析：6 位代码 → 公司名称（仅展示层使用）。

设计约束：
- 名称只进报告标题、数据说明、界面与下载文件名，绝不参与指标计算；
- 本地全量快照优先，保证离线可用且确定性模板报告逐字可复现；
- 本地快照按文件指纹自动重载，刷新后无需重启服务即可看到新增编码与更名；
- 任何解析器异常或未命中都只返回 None，分析主链路不因此中断；
- 新增名称来源只需实现 NameResolver 并 register_name_resolver()，编排层不改。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from app import config


def normalize_name(name: object) -> str:
    """统一简称：全角字母转半角、去掉排版空格、去掉小数点。

    去掉小数点是为了避免极少数简称里出现形如 1.2 的片段，被报告的数字
    一致性校验（扫描含小数点的数值）当成未登记数字。
    """
    text = unicodedata.normalize("NFKC", str(name)).strip()
    text = re.sub(r"\s+", "", text)
    return text.replace(".", "")


@dataclass(frozen=True)
class NameInfo:
    code: str
    name: str
    source: str            # 名称来源，报告与界面均需标注以便审计


class NameResolver(Protocol):
    name: str

    def resolve(self, code: str) -> tuple[str, str] | None:
        """返回 (证券简称, 来源说明)；未命中或不可用返回 None。"""
        ...


class LocalNameResolver:
    """读 data/company_names.json 离线全量快照。

    按文件指纹（修改时间 + 大小）自动重载：刷新脚本重写快照后，运行中的服务
    无需重启即可看到新增编码与更名结果。读取失败不固化失败态，下一次请求会
    重试，避免半截文件被永久缓存成「全表为空」。
    """
    name = "local"

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.COMPANY_NAMES_PATH
        self._data: dict | None = None
        self._fingerprint: tuple[int, int] | None = None

    def _signature(self) -> tuple[int, int] | None:
        try:
            st = self.path.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def _load(self) -> dict:
        sig = self._signature()
        if self._data is not None and sig == self._fingerprint:
            return self._data
        parsed: dict = {}
        good = False
        if sig is not None:
            try:
                candidate = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict) and isinstance(candidate.get("names"), dict):
                    parsed = candidate
                    good = True
            except (OSError, ValueError):
                pass
        self._data = parsed
        self._fingerprint = sig if good else None   # 失败态留空，下轮重试
        return self._data

    def resolve(self, code: str) -> tuple[str, str] | None:
        data = self._load()
        hit = (data.get("names") or {}).get(code)
        if not hit:
            return None
        source = f"本地证券简称表（{data.get('as_of', '日期未知')} 快照）"
        backfilled = data.get("backfilled") or {}
        if code in backfilled:
            source += f"；{code} 于 {backfilled[code]} 在线补录"
        return normalize_name(hit), source


class AkShareNameResolver:
    """在线补充：本地表未命中且配置开启时才调用，失败后本次进程不重试。"""
    name = "akshare"

    def __init__(self) -> None:
        self._table: dict[str, str] | None = None

    def resolve(self, code: str) -> tuple[str, str] | None:
        if self._table is None:
            try:
                import akshare as ak
                df = ak.stock_info_a_code_name()
                self._table = {
                    str(c).strip().zfill(6): normalize_name(n)
                    for c, n in zip(df["code"], df["name"])
                }
            except Exception:
                self._table = {}
        hit = self._table.get(code)
        return (hit, "AKShare 在线证券简称接口") if hit else None


# 解析顺序即优先级；在线补充默认关闭，避免免费源不稳定拖慢每次请求。
RESOLVERS: list[NameResolver] = [LocalNameResolver()]
if config.NAME_ONLINE_FALLBACK:
    RESOLVERS.append(AkShareNameResolver())


def register_name_resolver(resolver: NameResolver, *, first: bool = False) -> None:
    if first:
        RESOLVERS.insert(0, resolver)
    else:
        RESOLVERS.append(resolver)


def lookup(code: str | None) -> NameInfo | None:
    value = (code or "").strip()
    if not re.fullmatch(r"\d{6}", value):
        return None
    for resolver in RESOLVERS:
        try:
            hit = resolver.resolve(value)
        except Exception:
            hit = None                       # 单个来源失败不影响分析主链路
        if hit and hit[0]:
            return NameInfo(value, hit[0], hit[1])
    return None


def display_subject(code: str, info: NameInfo | None = None) -> str:
    """展示名：有简称时「贵州茅台（600519）」，否则退回原标识。"""
    return f"{info.name}（{code}）" if info and info.name else code


def describe(code: str | None) -> dict:
    """供接口层返回的名称信息（上传入口无代码，不调用本函数）。"""
    value = (code or "").strip()
    info = lookup(value)
    return {
        "code": value,
        "company_name": info.name if info else None,
        "name_source": info.source if info else "",
        "display_name": display_subject(value, info),
        # 前端据此区分「代码不在沪深 A 股名单（需核对）」与
        # 「有名称但本地无财报（可切换在线源）」两种提示
        "in_name_table": info is not None,
    }


# ── 在线取数成功后的简称表自动补录 ──
# 触发前提由编排层保证：仅在线源成功取得完整三大报表后调用，绝不给「查无此股」
# 的代码补录。本模块只负责「取在线名称 → 原子补写 → 失败静默」，不判断财报。

@dataclass(frozen=True)
class BackfillResult:
    code: str
    added: bool                 # 是否真的写入了本地全表
    name: str | None            # 本次补入 / 已存在的名称
    reason: str                 # added / already_present / lookup_failed / invalid_code / write_failed

    def as_dict(self) -> dict:
        return {"code": self.code, "added": self.added,
                "name": self.name, "reason": self.reason}


def fetch_online_name(code: str) -> str | None:
    """从 AKShare 全表简称接口取单个代码名称；失败返回 None。

    独立函数而非复用 AkShareNameResolver：后者失败后会在实例内固化空表，
    补录是低频动作，这里不做跨请求缓存，保证每次补录都拿到最新在线结果。
    """
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        for raw_code, raw_name in zip(df["code"], df["name"]):
            if str(raw_code).strip().zfill(6) == code:
                value = normalize_name(raw_name)
                return value or None
    except Exception:
        return None
    return None


def backfill_name(code: str, *, name_lookup: Callable[[str], str | None] | None = None,
                  path: Path | None = None) -> BackfillResult:
    """在线源取数成功后，把本地全表缺失的代码连同名称原子补写进全表。

    - 只增不覆盖：已存在的代码直接返回 already_present，避免手动更名被在线旧名冲掉；
    - 原子写入：同目录临时文件 + os.replace，读取方按指纹重载，无需重启服务；
    - 全程静默：任何异常都返回 added=False，绝不阻断主分析链路。
    """
    value = (code or "").strip()
    if not re.fullmatch(r"\d{6}", value):
        return BackfillResult(value, False, None, "invalid_code")
    if not config.NAME_BACKFILL_ONLINE:
        return BackfillResult(value, False, None, "lookup_failed")

    target = path or config.COMPANY_NAMES_PATH
    lookup_fn = name_lookup or fetch_online_name
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        table = payload.get("names")
        if not isinstance(table, dict):
            return BackfillResult(value, False, None, "write_failed")
        if value in table:
            return BackfillResult(value, False, normalize_name(table[value]), "already_present")

        raw_name = lookup_fn(value)
        name = normalize_name(raw_name) if raw_name else ""
        if not name:
            return BackfillResult(value, False, None, "lookup_failed")

        table[value] = name
        payload["names"] = dict(sorted(table.items()))
        payload["count"] = len(table)
        backfilled = payload.get("backfilled")
        if not isinstance(backfilled, dict):
            backfilled = {}
        backfilled[value] = config.now().date().isoformat()
        payload["backfilled"] = backfilled

        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
        os.replace(tmp, target)
        return BackfillResult(value, True, name, "added")
    except Exception:
        return BackfillResult(value, False, None, "write_failed")
