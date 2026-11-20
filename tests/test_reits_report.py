"""P2：PNG 图表与 PDF 报告单测（合成数据，含数字白名单校验）。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app import config as app_config
from app.reits_analysis.charts import generate_charts
from app.reits_analysis.metrics import compute_metrics
from app.reits_analysis.model import AnalysisTask, SourceFile
from app.reits_analysis.parser import parse_uploaded
from app.reits_analysis.quality import build_quality_report
from app.reits_analysis.report import build_report
from app.reporting.pdf import render_pdf


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        path = self.root / "wind.xlsx"
        frames = []
        for name, code, values in (
            ("华安百联消费REIT", "508002", [3.0, 3.147, 2.8, 2.541]),
            ("华夏华润消费REIT", "180601", [8.0, 8.1, 8.4, 9.0]),
        ):
            frames.append((name, pd.DataFrame(
                [["日期", f"{name}['{code}]", f"成交金额(百万元)['{code}]"],
                 ["2025-12-30", values[0], 30.0],
                 ["2025-12-31", values[1], 20.0],
                 ["2026-01-05", values[2], 25.0],
                 ["2026-11-16", values[3], 15.0]],
                columns=["日期", "价格", "成交额"])))
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name, frame in frames:
                frame.to_excel(writer, sheet_name=name, header=False, index=False)
        sf = SourceFile("x.xlsx", path.name, "quote")
        _, ds = parse_uploaded(path, sf)
        self.task = AnalysisTask(
            id="t", source_files=[sf], datasets={"quote": ds},
            created_at=app_config.now_str())
        self.task.quality_report = build_quality_report(self.task)
        self.task.metrics = compute_metrics(self.task)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_eight_charts_are_generated(self) -> None:
        charts = generate_charts(self.task, self.task.metrics, self.root / "charts")
        self.assertEqual(len(charts), 8)
        self.assertTrue(all(p.exists() and p.stat().st_size > 2000 for p in charts.values()))

    def test_report_numbers_are_all_registered_and_pdf_renders(self) -> None:
        charts = generate_charts(self.task, self.task.metrics, self.root / "charts")
        doc, consistency = build_report(self.task, self.task.metrics, charts,
                                        self.task.quality_report)
        self.assertTrue(consistency["passed"], str(consistency["unknown"]))
        self.assertIn("2.541", consistency["registered"])
        pdf = render_pdf(doc, self.root / "report.pdf")
        self.assertTrue(pdf.exists() and pdf.stat().st_size > 10000)
        self.assertTrue(any(b.type == "image" for b in doc.blocks))
        self.assertTrue(any(b.type == "table" for b in doc.blocks))

    def test_price_basis_is_fixed_and_evidence_backed(self) -> None:
        """口径为系统固定标注：报告写明来源与反算依据，不再有确认/待核措辞。"""
        charts = generate_charts(self.task, self.task.metrics, self.root / "charts_basis")
        doc, consistency = build_report(self.task, self.task.metrics, charts,
                                        self.task.quality_report)
        self.assertTrue(consistency["passed"], str(consistency["unknown"]))
        text = doc.all_text()
        self.assertIn("价格口径：未复权收盘价（元）", text)
        self.assertIn("WIND 日行情导出模板", text)
        self.assertIn("反算交叉验证", text)
        self.assertNotIn("口径待核", text)
        self.assertNotIn("不作为定稿", text)

    def test_benchmark_switch_drives_report_and_chart_notes(self) -> None:
        """切换基准后，报告标题/正文与图表脚注都必须指向新标的。"""
        self.task.benchmark_code = "180601"
        self.task.metrics = compute_metrics(self.task, self.task.benchmark_code)
        charts = generate_charts(self.task, self.task.metrics, self.root / "charts_switched")
        doc, consistency = build_report(self.task, self.task.metrics, charts,
                                        self.task.quality_report)
        self.assertTrue(consistency["passed"], str(consistency["unknown"]))
        self.assertIn("华夏华润", doc.subject)
        texts = []
        for block in doc.blocks:
            p = block.payload
            if isinstance(p, str):
                texts.append(p)
            elif isinstance(p, dict):
                texts.extend([str(p.get("text", "")), str(p.get("caption", ""))])
        joined = "\n".join(texts)
        self.assertIn("基准标的：华夏华润消费REIT（180601）", joined)
        self.assertIn("对标基准：华夏华润消费REIT（180601）", joined)
        self.assertIn("横向对标（基准：华夏华润消费REIT）", joined)
        self.assertNotIn("基准标的：华安百联消费REIT", joined)
        # 图表脚注与标题均使用新基准名（图表标题由同一 benchmark name 构造）
        from app.reits_analysis.charts import _note
        note = _note(self.task, self.task.metrics)
        self.assertIn("对标基准：华夏华润消费REIT（180601）", note)
        self.assertNotIn("对标基准：华安百联消费REIT", note)

    def test_missing_quote_still_produces_gap_report(self) -> None:
        empty = AnalysisTask(id="e", created_at=app_config.now_str())
        empty.quality_report = build_quality_report(empty)
        doc, consistency = build_report(empty, {}, {}, empty.quality_report)
        self.assertTrue(consistency["passed"], str(consistency["unknown"]))
        self.assertTrue(any("缺口" in str(b.payload) for b in doc.blocks))


if __name__ == "__main__":
    unittest.main()
