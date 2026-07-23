"""
vLLM Assistant - FastAPI 主应用
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_401_UNAUTHORIZED

from app.config import Config
from app.scheduler import (
    start_scheduler,
    stop_scheduler,
    trigger_refresh,
    get_sync_status,
)

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

static_dir = Path(__file__).parent.parent / "static"

# 用于持有后台 asyncio tasks，防止被 GC 回收
_background_tasks = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 配置验证：失败不抛错（让用户在 /docs 看到 API），仅告警
    try:
        Config.validate()
        logger.info("Configuration validated successfully")
    except ValueError as e:
        logger.warning(f"Configuration incomplete: {e}. Most endpoints will return 4xx/empty until configured.")

    # 启动 scheduler
    try:
        start_scheduler()
    except Exception:
        logger.exception("Failed to start scheduler; service will run without background sync")

    # 后台异步初始化代码仓库（学习文章功能）
    if Config.REPOS:
        task = asyncio.create_task(_init_repo_caches())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    yield

    # 关闭
    try:
        stop_scheduler()
    except Exception:
        logger.exception("Error stopping scheduler")


async def _init_repo_caches():
    """后台异步 clone/pull 所有代码仓库（不阻塞服务启动）"""
    from app.services.repo_manager import RepoManager

    manager = RepoManager()
    for repo_name, clone_url in Config.REPOS.items():
        try:
            await manager.async_ensure_cloned(repo_name, clone_url, branch="main")
        except Exception:
            logger.exception(f"Failed to clone repo {repo_name}")


app = FastAPI(
    title="vLLM Assistant",
    description="vLLM 贡献者效率工具 - 帮助贡献者高效参与社区，加速成为 committer",
    version="0.1.0",
    lifespan=lifespan,
)


class AuthMiddleware(BaseHTTPMiddleware):
    """简单的 Bearer Token 认证中间件。

    DEBUG 模式跳过认证；静态文件和 /health 放行。
    """
    async def dispatch(self, request: Request, call_next):
        if Config.DEBUG:
            return await call_next(request)

        path = request.url.path
        # 放行静态文件、健康检查、/
        if path.startswith("/static/") or path in ("/health", "/"):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == Config.API_KEY:
            return await call_next(request)

        return JSONResponse(
            status_code=HTTP_401_UNAUTHORIZED,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )


app.add_middleware(AuthMiddleware)

# API 路由
from app.api.community import router as community_router
from app.api.pr_center import router as pr_center_router
from app.api.ai_assistant import router as ai_assistant_router
from app.api.watchlist import router as watchlist_router
from app.api.my_stats import router as my_stats_router
from app.api.personal_todo import router as personal_todo_router
from app.api.intelligence import router as intelligence_router
from app.api.articles import router as articles_router
from app.api.sync import router as sync_router
from app.api.code_browser import router as code_browser_router

app.include_router(community_router, prefix="/api/community", tags=["Community Pulse"])
app.include_router(pr_center_router, prefix="/api/pr-center", tags=["PR Command Center"])
app.include_router(ai_assistant_router, prefix="/api/ai-assistant", tags=["AI Assistant"])
app.include_router(watchlist_router, prefix="/api/watchlist", tags=["Watchlist"])
app.include_router(my_stats_router, prefix="/api/my-stats", tags=["My Stats"])
app.include_router(personal_todo_router, prefix="/api/personal-todo", tags=["Personal Todo"])
app.include_router(intelligence_router, prefix="/api/intelligence", tags=["Intelligence Reports"])
app.include_router(articles_router, prefix="/api/articles", tags=["Articles"])
app.include_router(sync_router, prefix="/api/sync", tags=["Sync"])
app.include_router(code_browser_router, prefix="/api/code-browser", tags=["Code Browser"])


# 静态文件
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static")


@app.get("/")
async def root():
    """返回主页面"""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "vLLM Assistant API is running. Visit /docs for API documentation."}


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "debug": Config.DEBUG,
        "configured": bool(Config.GITHUB_PAT),
        "username_configured": bool(Config.USERNAME),
    }


@app.post("/api/refresh")
async def refresh_cache():
    """手动触发一次完整同步（异步执行，不阻塞请求）"""
    try:
        result = trigger_refresh()
        return result
    except Exception:
        logger.exception("Error in /api/refresh")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/status")
async def scheduler_status():
    """查看 scheduler 状态"""
    return get_sync_status()


# 全局异常处理器（仅处理非 HTTPException 的意外错误）
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """处理所有未捕获的意外异常（HTTPException 由 FastAPI 内置处理）"""
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception(f"Unhandled exception on {request.url}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=False,  # reload=True 在代码改动时强制重启，scheduler 会丢失
    )
