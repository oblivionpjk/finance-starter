"""P0：WIND Excel 解析与质量报告单测（合成文件，不依赖桌面真实文件）。

运行：.venv/bin/python -m unittest tests.test_reits_parser -v
可选真实文件：REIT_TEST_XLS=/path/to/HPCFile.xls .venv/bin/python -m unittest tests.test_reits_parser -v
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app import config as app_config
from app.reits_analysis.model import AnalysisTask, SourceFile
from app.reits_analysis.parser import detect_dimension, parse_uploaded
from app.reits_analysis.quality import build_quality_report


def _make_quote_book(path: Path, bad_price: bool = False) -> None:
    rows_a = [
        ["2026-01-05", 2.0, 30.0],
        ["2026-01-06", 2.1, 20.0],
        ["2026-01-07", 2.2, 10.0],
    ]
    if bad_price:
        rows_a.append(["2026-01-08", -1.0, 5.0])
    df_a = pd.DataFrame(
        [["日期", "华安百联消费REIT['508002]", "成交金额(百万元)['508002]"]] + rows_a
        + [[None, None, None], ["数据来源：Wind", None, None]],
        columns=["日期", "价格", "成交额"],
    )
    df_b = pd.DataFrame(
        [["日期", "华夏华润消费REIT['180601]", "成交金额(百万元)['180601]"],
         ["2026-01-05", 8.0, 100.0],
         ["2026-01-06", 8.5, 90.0],
         ["2026-01-07", 9.0, 80.0]],
        columns=["日期", "价格", "成交额"],
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_a.to_excel(writer, sheet_name="华安百联消费REIT", header=False, index=False)
        df_b.to_excel(writer, sheet_name="华夏华润消费REIT", header=False, index=False)


class ParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_detect_and_parse_quote(self) -> None:
        path = self.root / "wind.xlsx"
        _make_quote_book(path)
        self.assertEqual(detect_dimension(path), "quote")

        dim, ds = parse_uploaded(path, SourceFile("x.xlsx", "wind.xlsx", "quote"))
        self.assertEqual(dim, "quote")
        self.assertEqual(ds.codes(), ["180601", "508002"])
        bailian = ds.series["508002"]
        self.assertEqual(bailian.market, "SH")
        self.assertAlmostEqual(bailian.last_close, 2.2)
        self.assertEqual(bailian.dates, ["2026-01-05", "2026-01-06", "2026-01-07"])
        self.assertEqual((ds.common_start, ds.common_end), ("2026-01-05", "2026-01-07"))
        self.assertEqual(ds.snapshot_date, "2026-01-07")
        self.assertFalse(any(i.code in ("INVALID_DATE_ROWS", "INVALID_AMOUNT_ROWS")
                             for i in ds.quality))

    def test_invalid_price_row_is_dropped_and_reported(self) -> None:
        path = self.root / "wind_bad.xlsx"
        _make_quote_book(path, bad_price=True)
        _, ds = parse_uploaded(path, SourceFile("x.xlsx", "wind_bad.xlsx", "quote"))
        self.assertNotIn("2026-01-08", ds.series["508002"].dates)
        self.assertTrue(any(i.code == "INVALID_PRICE_ROWS" for i in ds.quality))

    def test_unrecognized_file_has_no_dimension(self) -> None:
        path = self.root / "other.xlsx"
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_excel(path, index=False)
        self.assertIsNone(detect_dimension(path))
        self.assertEqual(
            parse_uploaded(path, SourceFile("x.xlsx", "other.xlsx", None)), (None, None))

    def test_quality_report_lists_fundamental_gaps(self) -> None:
        path = self.root / "wind.xlsx"
        _make_quote_book(path)
        _, ds = parse_uploaded(path, SourceFile("x.xlsx", "wind.xlsx", "quote"))
        task = AnalysisTask(id="t", datasets={"quote": ds}, created_at=app_config.now_str())
        report = build_quality_report(task)
        self.assertEqual(report["series_count"], 2)
        self.assertEqual(report["issue_counts"]["block"], 0)
        self.assertTrue({"distribution", "financial", "operation", "valuation", "index"}
                        <= {g["dimension"] for g in report["gaps"]})

    @unittest.skipUnless(os.environ.get("REIT_TEST_XLS"),
                         "设置 REIT_TEST_XLS 后运行真实文件集成测试")
    def test_real_wind_excel(self) -> None:
        path = Path(os.environ["REIT_TEST_XLS"])
        dim, ds = parse_uploaded(path, SourceFile("x.xls", path.name, "quote"))
        self.assertEqual(dim, "quote")
        self.assertEqual(len(ds.series), 12)
        self.assertEqual(ds.snapshot_date, "2026-11-16")
        self.assertEqual((ds.common_start, ds.common_end), ("2025-10-31", "2026-11-16"))
        self.assertAlmostEqual(ds.series["508002"].last_close, 2.541)


if __name__ == "__main__":
    unittest.main()
