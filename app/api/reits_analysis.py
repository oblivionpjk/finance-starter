"""REITs 行情分析独立 API：/api/v1/reits/*。

与 A 股主链路共用会话存储与静态挂载，但路由、状态、产物完全独立。
产物下载做路径穿越防护（只认会话内已登记的文件名）。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, File, UploadFile
from fastapi.responses import FileResponse

from app.reits_analysis import config as cfg, service

router = APIRouter(prefix="/api/v1/reits", tags=["REITs 行情分析"])


@router.post("/session")
def create_session():
    return {"session_id": service.create_session(),
            "retention": "上传文件与产物仅在当前会话内留存，关闭页面即销毁。"}


@router.get("/capabilities")
def capabilities():
    return cfg.capability_payload()


@router.post("/upload")
async def upload(session_id: str, files: list[UploadFile] = File(...)):
    payloads = [(f.filename or "upload.xls", await f.read()) for f in files]
    return service.upload(session_id, payloads)


@router.post("/options")
def set_options(body: dict = Body(...)):
    return service.set_options(str(body.get("session_id", "")), body)


@router.get("/state")
def get_state(session_id: str):
    return service.state(session_id)


@router.get("/metrics")
def get_metrics(session_id: str):
    return service.metrics(session_id)


@router.post("/generate")
def generate(body: dict = Body(...)):
    return service.generate(str(body.get("session_id", "")))


@router.get("/artifacts/{key}")
def artifact(key: str, session_id: str):
    path = service.resolve(session_id, key)
    suffix = path.suffix.lower()
    media = {".pdf": "application/pdf", ".png": "image/png",
             ".json": "application/json"}.get(suffix, "application/octet-stream")
    return FileResponse(path, media_type=media, filename=path.name)
