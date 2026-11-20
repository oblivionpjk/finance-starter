#!/usr/bin/env python3
"""启动财务分析系统（本机开发 / 内部自用）。

用法：
    .venv/bin/python scripts/run_server.py
然后浏览器打开 http://127.0.0.1:8000

部署到云服务器时用环境变量覆盖监听地址：
    FINANCE_HOST=0.0.0.0 FINANCE_PORT=8000 .venv/bin/python scripts/run_server.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from app import config  # noqa: E402


if __name__ == "__main__":
    print(f"财务分析系统启动：http://{config.SERVER_HOST}:{config.SERVER_PORT}")
    print(f"数据源：{config.DEFAULT_SOURCE}；报告：PDF；叙述：确定性模板")
    print("上传数据与产物仅在当前页面会话内留存，关闭页面即销毁。")
    uvicorn.run("app.api.server:app", host=config.SERVER_HOST,
                port=config.SERVER_PORT, log_level="info")
