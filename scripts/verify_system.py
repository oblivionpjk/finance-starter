#!/usr/bin/env python3
"""端到端自检：不启动 HTTP 服务，直接跑两条完整链路。

验证项：入口 A（600519 离线快照）、入口 B（上传 demo 三表）、
PDF 与图表落盘、数字一致性、会话销毁后临时目录不存在。

用法：.venv/bin/python scripts/verify_system.py
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.adapters import upload as upload_adapter  # noqa: E402
from app.services import orchestrator  # noqa: E402
from app.storage.session import STORE  # noqa: E402

DEMO_FILES = ("income_statement.csv", "balance_sheet.csv", "cash_flow.csv")


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        raise AssertionError(label)


def verify_outcome(out: dict, label: str) -> None:
    print(f"\n=== {label} ===")
    check("分析返回可比报告期", bool(out["periods"]), "、".join(out["periods"]))
    check("数字一致性校验通过", out["consistency"]["passed"],
          f"登记 {out['consistency']['registered_numbers']} 个数值")
    check("图表数量 >= 10", len(out["charts"]) >= 10, f"{len(out['charts'])} 张")
    check("结论摘要非空", len(out["insights"]) >= 5, f"{len(out['insights'])} 条")
    pdf = STORE.resolve(out["session_id"], out["report"]["name"])
    check("PDF 已落盘且非空", pdf is not None and pdf.stat().st_size > 20000,
          f"{out['report']['size_bytes']} 字节")
    missing = [c["name"] for c in out["charts"]
               if STORE.resolve(out["session_id"], c["name"]) is None]
    check("全部图表可解析", not missing, "、".join(missing))


def main() -> int:
    print("财务分析系统端到端自检")
    print(f"数据源：mock 离线快照；报告：PDF；会话临时目录：{config.SESSION_ROOT}")

    s1 = STORE.create()
    out1 = orchestrator.analyze_code(s1, "600519", periods=10, source_name="mock")
    verify_outcome(out1, "入口 A：6 位 A 股代码 600519")
    check("标的核对提示存在", bool(out1["note"]), out1["note"][:60])
    check("入口 A 返回公司名称与展示名",
          out1["company_name"] == "贵州茅台" and
          "贵州茅台" in out1["subject"] and "600519" in out1["subject"],
          f"{out1['subject']} / 来源 {out1['name_source']}")
    check("报告数据说明含证券简称与来源",
          out1["source_meta"]["证券简称"] == "贵州茅台" and
          "本地证券简称表" in out1["source_meta"]["简称来源"])
    check("PDF 文件名带公司名称", out1["report"]["name"].startswith("贵州茅台_"),
          out1["report"]["name"])

    s2 = STORE.create()
    for name in DEMO_FILES:
        dst = s2.root / f"upload_{name}"
        shutil.copyfile(config.DEMO_DIR / name, dst)
        s2.uploads[dst.name] = dst
    tables = []
    for path in s2.uploads.values():
        tables.extend(upload_adapter.read_tables(path))
    s2.tables = tables
    payload = upload_adapter.inspect_payload(tables)
    check("上传布局全部识别", all(f["layout"] != "unknown" for f in payload["files"]))
    out2 = orchestrator.analyze_upload(s2, unit="元", roles=payload["roles"],
                                       overrides={}, periods=10)
    verify_outcome(out2, "入口 B：上传 demo 三大报表")
    check("上传入口不虚构公司名称",
          out2["company_name"] == "" and out2["subject"] == "上传报表" and
          out2["source_meta"]["证券简称"] == "—")

    check("两条入口产出同构结果",
          set(out1.keys()) == set(out2.keys()) and
          set(out1["source_meta"]) == set(out2["source_meta"]))

    root1, root2 = s1.root, s2.root
    STORE.destroy(s1.id)
    STORE.destroy(s2.id)
    check("会话销毁后临时目录不存在", not root1.exists() and not root2.exists())
    check("会话索引已清空", STORE.count() == 0)

    print("\n全部自检通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
