"""REITs 分析门面：session → upload → confirm → metrics → generate → artifacts。

所有文件按会话隔离；多次上传按维度累积（同一维度再次上传则替换），
为后续上传其他 Excel 扩展分析内容留出入口。
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from app import config as app_config
from app.errors import AnalysisError
from app.reits_analysis import config as cfg
from app.reits_analysis.charts import generate_charts
from app.reits_analysis.metrics import compute_metrics
from app.reits_analysis.model import AnalysisTask, GenericDataset, SourceFile
from app.reits_analysis.parser import parse_generic, parse_uploaded
from app.reits_analysis.quality import build_quality_report
from app.reits_analysis.report import build_report
from app.reporting.pdf import render_pdf
from app.storage.session import STORE

_LOCK = threading.RLock()


def _session(sid: str):
    s = STORE.get(sid)
    if s is None:
        raise AnalysisError("REIT_SESSION_EXPIRED", "会话不存在或已过期，请刷新页面")
    return s


def _task(s) -> AnalysisTask:
    task = getattr(s, "reits_task", None)
    if task is None:
        task = AnalysisTask(id=uuid.uuid4().hex[:12], created_at=app_config.now_str())
        s.reits_task = task
    return task


def create_session() -> str:
    return STORE.create().id


def _safe_name(original: str, suffix: str) -> str:
    return f"reit_{uuid.uuid4().hex[:12]}{suffix.lower()}"


def upload(sid: str, files: list[tuple[str, bytes]]) -> dict[str, Any]:
    """上传 1..N 份 Excel；已识别维度入 datasets，未识别文件保留但不参与分析。"""
    if not files:
        raise AnalysisError("REIT_NO_FILE", "请选择要上传的 WIND Excel 文件")
    if len(files) > 6:
        raise AnalysisError("REIT_TOO_MANY_FILES", "一次最多上传 6 份文件")

    with _LOCK:
        s = _session(sid)
        task = _task(s)
        notes: list[str] = []

        for original, content in files:
            suffix = Path(original or "").suffix.lower()
            if suffix not in cfg.ALLOWED_SUFFIXES:
                raise AnalysisError("REIT_SUFFIX_UNSUPPORTED",
                                    f"{original} 格式不支持，仅支持 xls / xlsx")
            if len(content) > cfg.MAX_UPLOAD_BYTES:
                raise AnalysisError("REIT_FILE_TOO_LARGE", f"{original} 超过上传上限")

            safe = _safe_name(original, suffix)
            path = s.root / safe
            path.write_bytes(content)
            s.uploads[safe] = path

            source = SourceFile(key=safe, original_name=original or safe, dimension=None)
            dimension, dataset = parse_uploaded(path, source)
            source.dimension = dimension

            if dimension is None:
                # 未识别 ≠ 丢弃：作为附加数据集保留，报告给出结构概览；
                # 后续只需注册专用解析器即可把同一份文件升级为正式维度。
                source.note = ("未识别为专用维度，已作为附加数据表纳入结构概览；"
                               "注册对应解析器后可产出专项指标")
                source.dimension = "attachments"
                dataset = parse_generic(path, "attachments", source)
                dataset.note = source.note
                existing = task.datasets.get("attachments")
                if isinstance(existing, GenericDataset):
                    existing.tables.update(dataset.tables)
                    existing.quality.extend(dataset.quality)
                else:
                    task.datasets["attachments"] = dataset
                notes.append(f"{original}：{source.note}")
            else:
                spec = cfg.DIMENSIONS[dimension]
                source.sheet_count = len(getattr(dataset, "tables", {}) or {}) or len(
                    getattr(dataset, "series", {}) or {})
                if dimension in task.datasets:
                    notes.append(f"{original}：已替换原有「{spec.label}」数据集")
                else:
                    notes.append(f"{original}：已纳入「{spec.label}」分析")
                task.datasets[dimension] = dataset

            task.source_files = [f for f in task.source_files if f.key != safe]
            task.source_files.append(source)

        quotes = task.quotes
        if quotes is not None and quotes.series and task.benchmark_code not in quotes.series:
            fallback = quotes.codes()[0]
            notes.append(f"原基准 {task.benchmark_code} 不在本次数据中，"
                         f"已自动切换为 {quotes.series[fallback].name}（{fallback}）")
            task.benchmark_code = fallback
        task.metrics = {}
        task.artifacts = {}
        task.created_at = app_config.now_str()
        task.quality_report = build_quality_report(task)
        state = task.state()
        state["notes"] = notes
        return state


def set_options(sid: str, body: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        task = _task(_session(sid))
        benchmark = str(body.get("benchmark") or task.benchmark_code or cfg.BENCHMARK_CODE)
        if task.quotes is not None and benchmark not in task.quotes.series:
            raise AnalysisError("REIT_BENCHMARK_UNKNOWN", f"标的中不存在代码 {benchmark}")
        task.benchmark_code = benchmark
        task.exclude_listing_day = bool(body.get("exclude_listing_day", False))
        task.metrics = {}
        task.artifacts = {}
        return task.state()


def state(sid: str) -> dict[str, Any]:
    return _task(_session(sid)).state()


def metrics(sid: str) -> dict[str, Any]:
    with _LOCK:
        task = _task(_session(sid))
        if not task.metrics:
            if not task.datasets:
                raise AnalysisError("REIT_NO_DATA", "尚无可用数据集，请先上传 WIND Excel")
            task.metrics = compute_metrics(task, task.benchmark_code, task.exclude_listing_day)
        return task.metrics


def generate(sid: str) -> dict[str, Any]:
    with _LOCK:
        s = _session(sid)
        task = _task(s)
        if not task.datasets:
            raise AnalysisError("REIT_NO_DATA", "尚无可用数据集，请先上传 WIND Excel")
        task.metrics = compute_metrics(task, task.benchmark_code, task.exclude_listing_day)
        task.quality_report = build_quality_report(task)

        out_dir = s.root / "artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        # 幂等：每次重新生成覆盖上次产物
        for old in out_dir.iterdir():
            if old.is_file():
                old.unlink()

        charts = generate_charts(task, task.metrics, out_dir)
        doc, consistency = build_report(task, task.metrics, charts, task.quality_report)
        if not consistency["passed"]:
            raise AnalysisError("REIT_NUMBER_MISMATCH", "报告存在未登记数值，已中止交付",
                                "、".join(consistency["unknown"]))

        snapshot = task.quotes.snapshot_date if task.quotes else app_config.now().strftime("%Y-%m-%d")
        revision = uuid.uuid4().hex[:8]
        pdf_name = f"{snapshot.replace('-', '')}_{task.benchmark_code}_{cfg.ARTIFACT_PDF}"
        pdf_path = render_pdf(doc, out_dir / pdf_name)

        quality_path = out_dir / cfg.ARTIFACT_QUALITY_JSON
        quality_path.write_text(
            json.dumps(task.quality_report, ensure_ascii=False, indent=2), encoding="utf-8")

        task.artifacts = {}
        register(sid, "pdf", pdf_path)
        register(sid, "quality", quality_path)
        for key, path in charts.items():
            register(sid, key, path)

        benchmark_row = (task.metrics.get("quote") or {}).get("benchmark") or {}
        benchmark_name = benchmark_row.get("name") or task.benchmark_code
        base_url = f"session_id={sid}&v={revision}"
        return {
            "session_id": sid,
            "task_id": task.id,
            "revision": revision,
            "benchmark": {"code": task.benchmark_code, "name": benchmark_name},
            "pdf": {"key": "pdf", "name": pdf_path.name, "size_bytes": pdf_path.stat().st_size,
                    "url": f"/api/v1/reits/artifacts/pdf?{base_url}"},
            "charts": [
                {"key": k, "name": p.name, "size_bytes": p.stat().st_size,
                 "url": f"/api/v1/reits/artifacts/{k}?{base_url}"}
                for k, p in charts.items()
            ],
            "quality": {"key": "quality", "name": quality_path.name,
                        "url": f"/api/v1/reits/artifacts/quality?{base_url}"},
            "consistency": {"passed": True, "registered": len(consistency["registered"])},
        }


def register(sid: str, key: str, path: Path) -> None:
    """登记产物；路径必须位于会话目录内，杜绝穿越。"""
    s = _session(sid)
    if s.root not in path.parents or not path.exists():
        raise AnalysisError("REIT_ARTIFACT_INVALID", "产物路径无效")
    s.artifacts[key] = path


def resolve(sid: str, key: str) -> Path:
    path = STORE.resolve(sid, key)
    if path is None:
        raise AnalysisError("REIT_ARTIFACT_NOT_FOUND", "产物不存在或会话已销毁")
    return path


def destroy(sid: str) -> dict[str, bool]:
    STORE.destroy(sid)
    return {"destroyed": True}
