# ============================================================================
# vLLM Assistant — 多阶段 Docker 构建
# ============================================================================
# 阶段一：Python 依赖构建
# ============================================================================
FROM python:3.12-slim AS python-builder

WORKDIR /build

# 系统依赖：git 用于仓库克隆
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================================
# 阶段二：前端构建
# ============================================================================
FROM node:20-slim AS frontend-builder

WORKDIR /build

# 复制前端源码
COPY frontend/ ./frontend/
WORKDIR /build/frontend

# 安装依赖并构建
RUN npm install && npm run build

# ============================================================================
# 阶段三：运行镜像
# ============================================================================
FROM python:3.12-slim

WORKDIR /app

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/*

# 从 Python 构建阶段复制已安装的依赖
COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

# 复制应用源代码
COPY app/ ./app/
COPY static/ ./static/

# 从前端构建阶段复制前端产物（覆盖 static/dist/）
COPY --from=frontend-builder /build/static/dist/ ./static/dist/

# 预编译 .pyc 加速启动
RUN python -m compileall -q app/

# 创建非 root 用户
RUN addgroup --system --gid 1001 app && \
    adduser --system --uid 1001 --ingroup app --no-create-home app

RUN mkdir -p /app/data/repos && \
    chown -R app:app /app/data

USER app

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://localhost:{port}/health')" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} --workers 1 --log-level ${LOG_LEVEL:-info} --no-access-log --timeout-graceful-shutdown ${GRACEFUL_SHUTDOWN_TIMEOUT:-30}"]