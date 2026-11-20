"""P1：指标层单测（纯函数 + 真实 WIND 数据关键数值回归）。"""
from __future__ import annotations

import math
import os
import statistics
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app.reits_analysis.metrics import (annualized_volatility, compare_quotes,
                                        daily_returns, max_drawdown, normalized_curve)
from app.reits_analysis.model import SourceFile
from app.reits_analysis.parser import parse_uploaded


class MetricFunctionTests(unittest.TestCase):
    def test_daily_returns_and_normalized_curve(self) -> None:
        close = [100.0, 110.0, 99.0]
        self.assertEqual([round(x, 6) for x in daily_returns(close)],
                         [0.1, -0.1])
        self.assertEqual(normalized_curve(close), [100.0, 110.0, 99.0])

    def test_volatility_and_drawdown(self) -> None:
        self.assertIsNone(annualized_volatility([1.0]))
        expected = statistics.stdev([0.1, -1 / 11, 0.1]) * math.sqrt(252)
        self.assertAlmostEqual(annualized_volatility([100.0, 110.0, 100.0, 110.0]) or 0,
                               expected, places=9)
        self.assertAlmostEqual(max_drawdown([100.0, 120.0, 90.0, 110.0]) or 0, -0.25, places=6)


class CompareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _book(self) -> Path:
        path = self.root / "wind.xlsx"
        frames = []
        for name, code, values in (
            ("华安百联消费REIT", "508002", [3.0, 3.147, 2.8, 2.541]),
            ("华夏华润消费REIT", "180601", [8.0, 8.1, 8.4, 9.0]),
        ):
            frames.append(pd.DataFrame(
                [["日期", f"{name}['{code}]", f"成交金额(百万元)['{code}]"],
                 ["2025-12-30", values[0], 30.0],
                 ["2025-12-31", values[1], 20.0],
                 ["2026-01-05", values[2], 25.0],
                 ["2026-11-16", values[3], 15.0]],
                columns=["日期", "价格", "成交额"]))
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for frame, (name, _, _) in zip(frames, (
                ("华安百联消费REIT", "508002", None), ("华夏华润消费REIT", "180601", None))):
                frame.to_excel(writer, sheet_name=name, header=False, index=False)
        return path

    def test_compare_uses_prev_year_close_as_ytd_base(self) -> None:
        path = self._book()
        _, ds = parse_uploaded(path, SourceFile("x.xlsx", path.name, "quote"))
        result = compare_quotes(ds)
        b = result["benchmark"]
        self.assertEqual(b["snapshot_close"], 2.541)
        self.assertEqual(b["ytd_base_date"], "2025-12-31")
        self.assertAlmostEqual(b["ytd_return"], 2.541 / 3.147 - 1, places=9)
        self.assertEqual(result["window"]["days"], 4)
        self.assertEqual(len(result["correlation"]["matrix"]), 2)
        self.assertEqual(len(result["curve"]["dates"]), 4)

    @unittest.skipUnless(os.environ.get("REIT_TEST_XLS"),
                         "设置 REIT_TEST_XLS 后运行真实文件关键数值回归")
    def test_real_bailian_numbers(self) -> None:
        path = Path(os.environ["REIT_TEST_XLS"])
        _, ds = parse_uploaded(path, SourceFile("x.xls", path.name, "quote"))
        result = compare_quotes(ds)
        b = result["benchmark"]
        self.assertEqual(result["snapshot_date"], "2026-11-16")
        self.assertEqual(result["window"], {"start": "2025-10-31", "end": "2026-11-16", "days": 253})
        self.assertAlmostEqual(b["snapshot_close"], 2.541, places=3)
        self.assertEqual(b["ytd_base_date"], "2025-12-31")
        self.assertEqual(round(b["ytd_return"] * 100, 2), -19.26)
        self.assertEqual(len(result["series"]), 12)
        self.assertEqual(len(result["correlation"]["matrix"]), 12)
        self.assertTrue(any(r["code"] == "180601" for r in result["series"]))


if __name__ == "__main__":
    unittest.main()
