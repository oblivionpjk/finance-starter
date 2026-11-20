"""P3：服务门面与会话隔离单测（合成数据）。"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.errors import AnalysisError
from app.reits_analysis import service
from app.storage.session import STORE


def _quote_bytes() -> bytes:
    path = Path(tempfile.gettempdir()) / "_reits_service_fixture.xlsx"
    rows = []
    for name, code, values in (
        ("华安百联消费REIT", "508002", [3.0, 3.1, 2.9, 2.541]),
        ("华夏华润消费REIT", "180601", [8.0, 8.2, 8.6, 9.0]),
    ):
        rows.append((name, pd.DataFrame(
            [["日期", f"{name}['{code}]", f"成交金额(百万元)['{code}]"],
             ["2025-12-30", values[0], 30.0],
             ["2025-12-31", values[1], 20.0],
             ["2026-01-05", values[2], 25.0],
             ["2026-11-16", values[3], 15.0]],
            columns=["日期", "价格", "成交额"])))
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in rows:
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    data = path.read_bytes()
    path.unlink()
    return data


def _quote_bytes_without_default() -> bytes:
    """不含默认基准 508002 的工作簿，用于验证上传后自动切换基准。"""
    path = Path(tempfile.gettempdir()) / "_reits_service_fixture_other.xlsx"
    rows = []
    for name, code, values in (
        ("中金印力消费REIT", "180602", [5.0, 5.1, 5.4, 5.6]),
        ("华夏华润消费REIT", "180601", [8.0, 8.2, 8.6, 9.0]),
    ):
        rows.append((name, pd.DataFrame(
            [["日期", f"{name}['{code}]", f"成交金额(百万元)['{code}]"],
             ["2025-12-30", values[0], 30.0],
             ["2025-12-31", values[1], 20.0],
             ["2026-01-05", values[2], 25.0],
             ["2026-11-16", values[3], 15.0]],
            columns=["日期", "价格", "成交额"])))
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in rows:
            frame.to_excel(writer, sheet_name=name, header=False, index=False)
    data = path.read_bytes()
    path.unlink()
    return data


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sid = service.create_session()

    def tearDown(self) -> None:
        service.destroy(self.sid)

    def test_upload_confirm_generate_and_download(self) -> None:
        state = service.upload(self.sid, [("wind.xlsx", _quote_bytes())])
        self.assertEqual(state["series_count"], 2)
        self.assertEqual(state["datasets"], ["quote"])
        self.assertEqual(state["price_basis"]["label"], "未复权收盘价（元）")
        self.assertNotIn("field", state)

        out = service.generate(self.sid)
        self.assertTrue(out["consistency"]["passed"])
        self.assertNotIn("finalized", out)
        self.assertEqual(len(out["charts"]), 8)
        self.assertTrue(all(service.resolve(self.sid, c["key"]).exists()
                            for c in out["charts"]))
        self.assertTrue(service.resolve(self.sid, "pdf").exists())

    def test_benchmark_switch_regenerates_artifacts(self) -> None:
        service.upload(self.sid, [("wind.xlsx", _quote_bytes())])
        first = service.generate(self.sid)
        service.set_options(self.sid, {"benchmark": "180601"})
        out = service.generate(self.sid)
        self.assertEqual(out["benchmark"], {"code": "180601", "name": "华夏华润消费REIT"})
        self.assertIn("180601", out["pdf"]["name"])
        self.assertNotIn("508002", out["pdf"]["name"])
        self.assertNotEqual(first["revision"], out["revision"])
        for url in [out["pdf"]["url"], out["quality"]["url"], out["charts"][0]["url"]]:
            self.assertIn(f"v={out['revision']}", url)

    def test_upload_auto_switches_benchmark_when_absent(self) -> None:
        state = service.upload(self.sid, [("other.xlsx", _quote_bytes_without_default())])
        self.assertEqual(state["benchmark"], "180601")
        self.assertTrue(any("自动切换" in n for n in state["notes"]))
        out = service.generate(self.sid)
        self.assertEqual(out["benchmark"]["code"], "180601")
        self.assertTrue(out["consistency"]["passed"])

    def test_future_excel_is_kept_as_attachment(self) -> None:
        service.upload(self.sid, [("wind.xlsx", _quote_bytes())])
        other = pd.DataFrame({"代码": ["508002"], "可供分配金额": [100]})
        bio = io.BytesIO()
        other.to_excel(bio, engine="openpyxl", index=False)
        buf = bio.getvalue()
        state = service.upload(self.sid, [("future.xlsx", buf)])
        self.assertEqual(state["datasets"], ["attachments", "quote"])
        self.assertFalse(any(g["dimension"] == "unrecognized"
                             for g in state["quality"]["gaps"]))
        out = service.generate(self.sid)
        self.assertTrue(out["consistency"]["passed"])

    def test_generate_without_data_is_rejected(self) -> None:
        with self.assertRaises(AnalysisError) as ctx:
            service.generate(self.sid)
        self.assertEqual(ctx.exception.code, "REIT_NO_DATA")

    def test_destroy_removes_artifacts(self) -> None:
        service.upload(self.sid, [("wind.xlsx", _quote_bytes())])
        out = service.generate(self.sid)
        key = out["charts"][0]["key"]
        service.destroy(self.sid)
        with self.assertRaises(AnalysisError):
            service.resolve(self.sid, key)
        self.assertNotIn(self.sid, STORE._sessions)


if __name__ == "__main__":
    unittest.main()
