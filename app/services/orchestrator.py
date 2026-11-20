"""分析任务编排：两条入口汇合到同一条「校验 → 分析 → 图表 → 报告 → 数字校验」流水线。

本模块不依赖 HTTP，可直接被接口层调用，也可被端到端自检脚本调用。
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from app import config
from app.adapters import sources, upload as upload_adapter
from app.domain.normalize import build_dataset, inspect
from app.domain.model import Dataset
from app.domain.numbers import verify
from app.engine import validation
from app.engine.analysis import analyze
from app.errors import AnalysisError
from app.rendering.charts import render_chart
from app.reporting.document import get_narrator
from app.reporting.pdf import render_pdf
from app.services import names
from app.services.subject import SubjectInfo, resolve
from app.storage.session import Session, STORE

PDF_NAME = "财务分析报告.pdf"


def _prepare_source_frames(raw: dict[str, pd.DataFrame]) -> list:
    tables = []
    roles: dict[str, str] = {}
    for st, raw_df in raw.items():
        df = raw_df.copy()
        # 在线接口的「报告日」可能是日期/时间戳，统一成 8 位数字，避免期间解析失败
        if "报告日" in df.columns:
            df["报告日"] = (df["报告日"].astype(str)
                           .str.replace(r"\D", "", regex=True).str[:8])
        name = f"source::{st}"
        t = inspect(df, name, st)
        if t.layout == "unknown":
            raise AnalysisError("LAYOUT_UNKNOWN",
                                f"数据源返回的{st}表结构无法识别",
                                "请检查数据源字段或改用本地快照")
        tables.append(t)
        roles[name] = st
    return tables, roles


def dataset_from_code(code: str, source_name: str | None = None) -> tuple[Dataset, SubjectInfo, str]:
    subject = resolve(code)
    source = sources.get_source(source_name)
    try:
        raw = source.fetch(code)
    except AnalysisError:
        raise
    except sources.LocalSnapshotMiss as exc:
        raise AnalysisError(
            "LOCAL_SNAPSHOT_MISS",
            f"本地快照未收录 {code} 的财报数据",
            f"缺少 {', '.join(exc.missing)}。本地离线源只收录有限标的，"
            "切换到在线数据源或改用上传三大报表即可继续。",
            data={
                "code": code,
                "missing_files": exc.missing,
                "actions": ["switch_online_source", "upload_statements"],
            },
        ) from exc
    except sources.OnlineCodeNotFound as exc:
        # 走到这里说明在线接口已实际返回空数据（不只是简称表缺失）：
        # 简称表缺失本身不代表无数据，新股换在线源常能取到；只有在线也落空才判查无此股。
        if exc.in_name_table:
            reason = "证券简称表收录了该代码，但在线接口未返回其三大报表，可能已退市或接口数据缺失"
        else:
            reason = ("本地简称表未收录该代码，且在线接口也未返回其三大报表，"
                      "该代码可能不是有效的 A 股；若为近期新股，可刷新简称表后重试")
        name_info = names.lookup(code)
        raise AnalysisError(
            "ONLINE_CODE_NOT_FOUND",
            f"在线数据源未取得 {code} 的财报",
            f"{reason}。请核对 6 位代码是否正确；重试无法解决。",
            data={
                "code": code,
                "reason": reason,
                "known_name": name_info.name if name_info else None,
                "actions": ["check_code", "upload_statements"],
            },
        ) from exc
    except Exception as exc:
        raise AnalysisError(
            "SOURCE_UNAVAILABLE",
            f"数据源 {source.name} 获取 {code} 的财报失败：{type(exc).__name__}",
            f"{exc}；免费接口可能限流或字段变动，可切换数据源或稍后重试。"
            "该代码未能通过「能否取得个股三大报表」的二次确认。",
        ) from exc
    if not raw or len(raw) < 3:
        raise AnalysisError("STATEMENTS_INCOMPLETE",
                            "数据源未返回完整的三大报表",
                            "该代码未能通过个股身份二次确认")

    # 在线源成功取到完整财报 → 若本地简称表缺该代码，查在线名称并补写进全表。
    # 只在取数成功之后做；mock 离线源、查无此股、取数失败都不会触发补录。
    # 补录结果只作审计记录，任何失败都不阻断分析（名称本就只用于展示）。
    backfill = None
    if getattr(source, "online", False) and names.lookup(code) is None:
        backfill = names.backfill_name(code)

    tables, roles = _prepare_source_frames(raw)
    name_info = names.lookup(code)   # 补录后重新解析，本次报告即可用上新名称
    dataset = build_dataset(
        tables, origin="code", subject=names.display_subject(code, name_info),
        source_ref=f"{getattr(source, 'label', source.name)} · {subject.market_label}",
        dataset_id=uuid.uuid4().hex, unit="元", roles=roles,
        company_name=name_info.name if name_info else "",
        name_source=name_info.source if name_info else "未匹配到证券简称，仅显示 6 位代码",
    )
    # 补录结果挂在实例上供 run() 汇总审计，不进入 Dataset 的字段模型。
    dataset.name_backfill = backfill.as_dict() if backfill else None
    return dataset, subject, getattr(source, "label", source.name)


def dataset_from_upload(session: Session, unit: str, roles: dict[str, str],
                        overrides: dict[str, str]) -> Dataset:
    if not session.uploads:
        raise AnalysisError("NO_UPLOAD", "当前会话没有上传文件", "请先上传三大报表")
    if unit not in config.AMOUNT_UNITS:
        raise AnalysisError("INVALID_UNIT", f"不支持的金额单位：{unit}")
    tables = session.tables
    if tables is None:
        tables = []
        for path in session.uploads.values():
            tables.extend(upload_adapter.read_tables(path))
        session.tables = tables
    dataset = build_dataset(
        tables, origin="upload", subject="上传报表",
        source_ref="用户上传三大报表（仅当前会话留存）",
        dataset_id=uuid.uuid4().hex, unit=unit, roles=roles,
        overrides=overrides,
    )
    return dataset


def inspect_uploads(session: Session) -> dict:
    if session.tables is None:
        raise AnalysisError("NO_UPLOAD", "当前会话没有上传文件")
    return upload_adapter.inspect_payload(session.tables)


def _session(session: Session | str) -> Session:
    if isinstance(session, Session):
        return session
    s = STORE.get(session)
    if s is None:
        raise AnalysisError("SESSION_EXPIRED", "会话不存在或已过期", "请刷新页面重新开始")
    return s


def run(session: Session | str, dataset: Dataset, *, max_periods: int | None = None,
        note: str = "") -> dict[str, Any]:
    s = _session(session)
    issues = validation.validate(dataset)
    if validation.has_block(issues):
        blocked = [i for i in issues if i.level == "block"]
        raise AnalysisError("VALIDATION_FAILED",
                            "；".join(i.message for i in blocked[:3]),
                            "；".join(i.detail for i in blocked[:3]))

    result, reg = analyze(dataset, issues, max_periods=max_periods)
    if not result.periods:
        raise AnalysisError("NO_COMPARABLE_PERIOD",
                            "没有可用于分析的共同年度报告期",
                            "请确认三张报表的报告期一致，且包含年报数据")

    images: list[tuple[str, str, str]] = []
    charts_meta: list[dict[str, str]] = []
    for spec in result.chart_specs:
        path = s.root / f"{spec.chart_id}.png"
        try:
            render_chart(spec, path)
        except Exception as exc:
            raise AnalysisError("CHART_RENDER_FAILED",
                                f"图表 {spec.title} 渲染失败", str(exc)) from exc
        STORE.register_artifact(s.id, path.name, path)
        title = f"{spec.title}（单位：{spec.unit}）"
        images.append((spec.chart_id, title, str(path)))
        charts_meta.append({"name": path.name, "title": spec.title,
                            "caption": title, "unit": spec.unit})

    doc = get_narrator().build(result, reg, images)
    passed, unknown = verify(doc, reg)
    if not passed:
        raise AnalysisError("NUMBER_CONSISTENCY_FAILED",
                            "报告中存在无法溯源的数字，已中止交付",
                            "、".join(unknown[:10]))

    pdf_name = (f"{re.sub(r'[\\/:*?\"<>|]', '_', dataset.company_name)}_{PDF_NAME}"
                if dataset.company_name else PDF_NAME)
    pdf_path = s.root / pdf_name
    try:
        render_pdf(doc, pdf_path)
    except Exception as exc:
        raise AnalysisError("PDF_RENDER_FAILED", "PDF 生成失败", str(exc)) from exc
    STORE.register_artifact(s.id, pdf_path.name, pdf_path)

    s.status = {"stage": "DONE", "subject": dataset.subject,
                "charts": len(charts_meta), "consistency": "passed"}
    return {
        "session_id": s.id,
        "subject": dataset.subject,
        "company_name": dataset.company_name,
        "name_source": dataset.name_source,
        "periods": result.periods,
        "report": {"name": pdf_path.name, "title": doc.title,
                   "size_bytes": pdf_path.stat().st_size},
        "charts": charts_meta,
        "insights": [{"level": i.level, "text": i.text} for i in result.insights],
        "quality": [{"level": q.level, "code": q.code,
                     "message": q.message, "detail": q.detail} for q in result.quality],
        "consistency": {"passed": True, "registered_numbers": len(reg.tokens),
                        "unknown": []},
        "source_meta": result.source_meta,
        "name_backfill": getattr(dataset, "name_backfill", None),
        "note": note,
        "retention": "产物仅保存在当前会话临时目录；页面关闭或会话到期即销毁。",
    }


def analyze_code(session: Session | str, code: str, periods: int | None = None,
                 source_name: str | None = None) -> dict[str, Any]:
    dataset, subject, label = dataset_from_code(code, source_name)
    note = subject.note or f"已按 {subject.market_label} 个股口径核对，数据源：{label}。"
    return run(session, dataset, max_periods=periods, note=note)


def analyze_upload(session: Session | str, unit: str, roles: dict[str, str],
                   overrides: dict[str, str], periods: int | None = None) -> dict[str, Any]:
    s = _session(session)
    dataset = dataset_from_upload(s, unit, roles, overrides)
    return run(s, dataset, max_periods=periods,
               note="数据由用户上传，系统未做外部核验；金额单位按页面选择换算为元后参与计算。")
