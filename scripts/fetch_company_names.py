#!/usr/bin/env python3
"""维护「6 位 A 股代码 → 证券简称」离线快照 data/company_names.json。

两种用法：
1. 在线全量刷新（新股上市、批量更名、退市）：
   .venv/bin/python scripts/fetch_company_names.py
2. 手动维护单条（在线源不可用时的新增 / 更名 / 退市）：
   .venv/bin/python scripts/fetch_company_names.py --set 301999 新股股份
   .venv/bin/python scripts/fetch_company_names.py --delete 000002

写入采用同目录临时文件 + 原子替换，运行中的服务按文件指纹自动重载，无需重启。
在线刷新失败时本地快照保持原样，不会被清空或写坏。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.services.names import normalize_name  # noqa: E402

OUT_PATH = config.COMPANY_NAMES_PATH
HINT_MANUAL = ("新增编码或更名可改用手动维护："
               ".venv/bin/python scripts/fetch_company_names.py --set 301999 新股股份")


def load_existing(path: Path = OUT_PATH) -> dict[str, str]:
    """读取旧快照的简称表；文件缺失或损坏时返回空表。"""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        names = parsed.get("names")
        return {str(k): str(v) for k, v in names.items()} if isinstance(names, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def write_atomic(payload: dict, path: Path = OUT_PATH) -> Path:
    """先写同目录临时文件再原子替换，避免读者拿到半截 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def diff_names(old: dict[str, str], new: dict[str, str]) -> dict[str, list[str]]:
    """按代码列出新增 / 更名 / 退出，供运维核对本次维护到底改了什么。"""
    return {
        "added": sorted(set(new) - set(old)),
        "changed": sorted(c for c in set(new) & set(old) if old[c] != new[c]),
        "removed": sorted(set(old) - set(new)),
    }


def report_diff(old: dict[str, str], names: dict[str, str],
                changes: dict[str, list[str]]) -> None:
    if old:
        print(f"变更：新增 {len(changes['added'])} / 更名 {len(changes['changed'])} / "
              f"退出 {len(changes['removed'])}")
        for code in changes["added"][:10]:
            print(f"  + {code} → {names[code]}")
        for code in changes["changed"][:10]:
            print(f"  ~ {code}: {old[code]} → {names[code]}")
        for code in changes["removed"][:10]:
            print(f"  - {code}（{old[code]}）")
        for key, label in (("added", "新增"), ("changed", "更名"), ("removed", "退出")):
            extra = len(changes[key]) - 10
            if extra > 0:
                print(f"  … {label}另有 {extra} 条未列出")
    else:
        print("首次建立快照（无旧表可比）")


def apply_manual(sets: list[tuple[str, str]], deletes: list[str],
                 path: Path = OUT_PATH) -> int:
    """不依赖在线接口，直接新增 / 更正 / 删除单条简称。"""
    old = load_existing(path)
    names = dict(old)
    for code, name in sets:
        value = str(code).strip().zfill(6)
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError(f"代码必须为 6 位数字：{code}")
        normalized = normalize_name(name)
        if not normalized:
            raise ValueError(f"简称为空：{value}")
        names[value] = normalized
    for code in deletes:
        value = str(code).strip().zfill(6)
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError(f"代码必须为 6 位数字：{code}")
        names.pop(value, None)
    if not names:
        raise RuntimeError("拒绝写入空简称表")
    changes = diff_names(old, names)
    payload = {
        "as_of": config.now().date().isoformat(),
        "source": "手动维护（--set / --delete）；基础数据：AKShare stock_info_a_code_name",
        "count": len(names),
        "names": dict(sorted(names.items())),
    }
    write_atomic(payload, path)
    print(f"已更新 {path}：{len(names)} 条，快照日期 {payload['as_of']}")
    report_diff(old, names, changes)
    return 0


def refresh_online(path: Path = OUT_PATH) -> int:
    """从 AKShare 拉取沪深 A 股全表并覆盖快照；失败时不动旧表。"""
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
    except Exception as exc:
        raise RuntimeError(
            f"在线拉取证券简称失败（{type(exc).__name__}: {str(exc)[:160]}）。"
            f"本地快照保持原样不变。{HINT_MANUAL}",
        ) from exc
    if "code" not in df.columns or "name" not in df.columns:
        raise RuntimeError(f"在线接口字段变动，实际列为：{list(df.columns)}")
    names: dict[str, str] = {}
    for raw_code, raw_name in zip(df["code"], df["name"]):
        code = str(raw_code).strip().zfill(6)
        name = normalize_name(raw_name)
        if re.fullmatch(r"\d{6}", code) and name:
            names[code] = name
    if len(names) < 1000:
        raise RuntimeError(f"在线返回仅 {len(names)} 条，疑似接口异常，拒绝覆盖本地快照")

    old = load_existing(path)
    changes = diff_names(old, names)
    payload = {
        "as_of": config.now().date().isoformat(),
        "source": "AKShare stock_info_a_code_name（沪深 A 股代码与证券简称全表）",
        "count": len(names),
        "names": dict(sorted(names.items())),
    }
    write_atomic(payload, path)
    print(f"已写入 {path}：{len(names)} 条，快照日期 {payload['as_of']}")
    report_diff(old, names, changes)
    for code in ("600519", "000001", "000858", "601318"):
        print(f"  {code} → {names.get(code, '未在表中')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="刷新或手动维护本地证券简称快照")
    parser.add_argument("--set", nargs=2, action="append", default=[], metavar=("CODE", "NAME"),
                        help="新增或更正单条简称，可重复，如 --set 301999 新股股份")
    parser.add_argument("--delete", action="append", default=[], metavar="CODE",
                        help="删除已退市代码的简称，可重复")
    args = parser.parse_args(argv)
    if args.set or args.delete:
        return apply_manual(args.set, args.delete)
    return refresh_online()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)
