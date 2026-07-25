# ============================================================================
# vLLM Assistant — 多阶段 Docker 构建
# ============================================================================
# 阶段一：依赖构建
# ============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

# 系统依赖：git 用于仓库克隆
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ============================================================================
# 阶段二：运行镜像
# ============================================================================
FROM python:3.12-slim

WORKDIR /app

# 安装运行时依赖
#   - git：代码仓库克隆需要
#   - tzdata：时区数据，配合 TZ 环境变量设置容器时区
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /var/cache/apt/*

# 从构建阶段复制已安装的 Python 依赖（系统 site-packages 路径）
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 复制应用代码
COPY app/ ./app/
COPY static/ ./static/
COPY requirements.txt .

# 创建数据目录（SQLite 和仓库克隆的挂载点）
RUN mkdir -p /app/data && \
    # 预编译 .pyc 加速启动
    python -m compileall -q app/

# 创建非 root 用户，提升容器安全性
RUN addgroup --system --gid 1001 app && \
    adduser --system --uid 1001 --ingroup app --no-create-home app

# 预创建 repos 子目录并确保 app 用户可写
# 注意：命名卷（vllm-assistant-data / vllm-assistant-repos-cache）
# 挂载时可能覆盖目录所有权，确保此处权限正确设置
RUN mkdir -p /app/data/repos && \
    chown -R app:app /app/data

USER app

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1

# 默认端口（实际端口由 .env 中 PORT 变量控制）
# EXPOSE 行已移除，端口映射由 docker-compose.yml 中的 ports 配置决定

# 默认启动命令
# ===== ⚠️ 重要：必须单进程运行 =====
# 原因：
#   - APScheduler BackgroundScheduler 在每个进程中独立运行
#   - workers > 1 会导致多个进程同时执行同步任务，造成 SQLite 数据竞争
#   - 即使 SQLite WAL 模式防止文件损坏，业务层 upsert 仍可能互相覆盖
#   - 如需横向扩展，应在外部使用反向代理（nginx/caddy）负载均衡多个容器
# ====================================
# 使用 exec 形式确保 SIGTERM 正确传递给 uvicorn（Docker stop 优雅关闭）
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000} --workers 1 --log-level ${LOG_LEVEL:-info} --no-access-log --timeout-graceful-shutdown ${GRACEFUL_SHUTDOWN_TIMEOUT:-30}"]