"""FastAPI 接口。

同步路由跑在线程池里，在线免费数据源的阻塞调用不会卡住事件循环。
所有产物按会话隔离；DELETE /sessions/{id} 由前端页面关闭时触发，销毁临时目录。
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.adapters import sources, upload as upload_adapter
from app.api import reits_analysis as reits_api
from app.errors import AnalysisError
from app.services import names, orchestrator
from app.storage.session import STORE


@asynccontextmanager
async def lifespan(app: FastAPI):
    STORE.start_sweeper()
    yield
    STORE.stop_sweeper()
    STORE.destroy_all()


app = FastAPI(title="财务分析系统", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 内部自用；部署到公网时应改为具体域名
    allow_methods=["*"], allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(config.WEB_DIR)), name="static")
app.include_router(reits_api.router)          # REITs 独立分析链路，不改 A 股业务逻辑


@app.exception_handler(AnalysisError)
async def analysis_error_handler(request, exc: AnalysisError):
    error = {"code": exc.code, "message": exc.message, "detail": exc.detail}
    if exc.data:
        error["data"] = exc.data
    return JSONResponse(status_code=400, content={"error": error})


def _get_session(sid: str):
    s = STORE.get(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请刷新页面")
    return s


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


@app.get("/reits")
def reits_page():
    """REITs 行情分析与横向对标独立页面。"""
    return FileResponse(config.WEB_DIR / "reits.html")


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "sessions": STORE.count(),
            "sources": [s["name"] for s in sources.list_sources()],
            "time": config.now_str()}


@app.get("/api/v1/config")
def get_config():
    return {
        "sources": sources.list_sources(),
        "default_source": config.DEFAULT_SOURCE,
        "markets": [{"code": r.code, "label": r.label, "enabled": r.enabled}
                    for r in config.MARKET_RULES],
        "units": list(config.AMOUNT_UNITS),
        "default_periods": config.DEFAULT_PERIODS,
        "max_upload_mb": round(config.MAX_UPLOAD_BYTES / 1024 / 1024, 1),
        "allowed_suffixes": list(config.ALLOWED_UPLOAD_SUFFIXES),
        "retention": "上传的原始报表与产物仅在当前页面会话内留存，关闭页面即销毁。",
        "report_format": "PDF",
        "narrator": config.NARRATOR,
    }


@app.get("/api/v1/company-name/{code}")
def company_name(code: str):
    """代码提示：证券简称 + 本地离线快照是否收录其三大报表。"""
    payload = names.describe(code)
    payload["local_statement_available"] = sources.has_local_statements(payload["code"])
    return payload


@app.post("/api/v1/sessions")
def create_session():
    s = STORE.create()
    return {"session_id": s.id, "retention": config.SESSION_TTL_SECONDS}


@app.delete("/api/v1/sessions/{sid}")
def destroy_session(sid: str):
    STORE.destroy(sid)
    return {"destroyed": True}


@app.post("/api/v1/sessions/{sid}/upload")
async def upload_files(sid: str, files: list[UploadFile] = File(...)):
    """保存上传文件到会话临时目录，解析并给出映射确认建议。"""
    s = _get_session(sid)
    if not files or len(files) > 6:
        raise HTTPException(status_code=400, detail="请上传 1-3 张报表（最多 6 个文件）")
    s.uploads.clear()
    s.artifacts.clear()
    s.tables = None
    tables = []
    original_names = []
    for f in files:
        content = await f.read()
        if len(content) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename} 超过上传大小上限")
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in config.ALLOWED_UPLOAD_SUFFIXES:
            raise HTTPException(status_code=400, detail=f"不支持 {suffix}，仅支持 xlsx / xls / csv")
        safe = f"{uuid.uuid4().hex[:10]}{suffix}"
        path = s.root / safe
        path.write_bytes(content)
        s.uploads[safe] = path
        original_names.append(f.filename)
        try:
            tables.extend(upload_adapter.read_tables(path))
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError("FILE_PARSE_FAILED",
                                f"{f.filename} 解析失败：{type(exc).__name__}", str(exc)) from exc
    s.tables = tables
    s.status = {"stage": "WAITING_MAPPING", "files": original_names}
    payload = upload_adapter.inspect_payload(tables)
    payload["original_names"] = original_names
    payload["session_id"] = s.id
    return payload


@app.post("/api/v1/sessions/{sid}/analyze-code")
def analyze_code(sid: str, body: dict = Body(...)):
    s = _get_session(sid)
    s.status = {"stage": "ANALYZING"}
    return orchestrator.analyze_code(
        s, code=str(body.get("code", "")),
        periods=body.get("periods") or config.DEFAULT_PERIODS,
        source_name=body.get("source") or config.DEFAULT_SOURCE,
    )


@app.post("/api/v1/sessions/{sid}/analyze")
def analyze_upload(sid: str, body: dict = Body(...)):
    s = _get_session(sid)
    s.status = {"stage": "ANALYZING"}
    return orchestrator.analyze_upload(
        s, unit=str(body.get("unit") or config.DEFAULT_UPLOAD_UNIT),
        roles=dict(body.get("roles") or {}),
        overrides={k: v for k, v in dict(body.get("overrides") or {}).items() if v},
        periods=body.get("periods") or config.DEFAULT_PERIODS,
    )


@app.get("/api/v1/sessions/{sid}/artifacts/{name}")
def artifact(sid: str, name: str):
    path = STORE.resolve(sid, name)
    if path is None:
        raise HTTPException(status_code=404, detail="产物不存在或会话已销毁")
    media = "application/pdf" if path.suffix == ".pdf" else "image/png"
    return FileResponse(path, media_type=media, filename=name)
