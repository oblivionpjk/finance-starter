# 生产镜像（云服务器预留，当前默认本机运行）
# 构建：docker build -f deploy/Dockerfile -t finance-analysis .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

# 中文字体：PDF 与静态图都不会出现方块字
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY src/ ./src/
COPY web/ ./web/
COPY data/ ./data/
COPY scripts/ ./scripts/

# 会话产物写在容器 /tmp，容器重启即清空，符合「不长期留存」策略
ENV FINANCE_HOST=0.0.0.0 \
    FINANCE_PORT=8000 \
    FINANCE_SESSION_ROOT=/tmp/finance-starter-sessions

EXPOSE 8000
CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
