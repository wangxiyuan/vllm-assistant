"""
vLLM Assistant - FastAPI 主应用
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from starlette.staticfiles import StaticFiles as StarletteStaticFiles

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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

    # Check if there are active repos in DB
    from app.database import SessionLocal
    from app.models import RepoCache

    db = SessionLocal()
    try:
        has_repos = db.query(RepoCache).filter(RepoCache.status == "active").count() > 0
    finally:
        db.close()

    if has_repos:
        task = asyncio.create_task(_init_repo_caches())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # 后台异步初始化知识库（不阻塞服务启动）
    task = asyncio.create_task(_init_knowledge_base())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    yield

    # 关闭
    try:
        stop_scheduler()
    except Exception:
        logger.exception("Error stopping scheduler")


async def _init_repo_caches():
    """后台异步 clone/pull 所有代码仓库（不阻塞服务启动）

    种子数据已在 lifespan 同步阶段写入 DB，这里只从 DB 读取并 clone。
    """
    from app.database import SessionLocal
    from app.models import RepoCache
    from app.services.repo_manager import RepoManager

    db = SessionLocal()
    try:
        repos = db.query(RepoCache).filter(RepoCache.status == "active").all()
        repos_to_clone = [(r.repo, r.clone_url, r.branch or "main") for r in repos]
    finally:
        db.close()

    if not repos_to_clone:
        logger.info("No active repos to clone")
        return

    manager = RepoManager()
    for repo_name, clone_url, branch in repos_to_clone:
        try:
            await manager.async_ensure_cloned(repo_name, clone_url, branch=branch)
        except Exception:
            logger.exception(f"Failed to clone repo {repo_name}")


async def _init_knowledge_base():
    """后台异步初始化知识库（不阻塞服务启动）

    等待所有已配置的代码仓库都同步到缓存后，从数据源增量构建知识。
    内部按 checksum 去重，不会重复构建已存在的条目。
    """
    from app.services.memory_service import MemoryService

    try:
        # 从 DB 获取活跃仓库列表
        from app.database import SessionLocal
        from app.models import RepoCache
        db = SessionLocal()
        try:
            active_repos = db.query(RepoCache).filter(RepoCache.status == "active").all()
            expected_repos = {r.repo for r in active_repos}
        finally:
            db.close()

        if expected_repos:
            logger.info(f"Waiting for repos {expected_repos} before building knowledge base...")
            for _ in range(60):
                from app.database import SessionLocal
                from app.models import LocalCodeCache
                db = SessionLocal()
                try:
                    from sqlalchemy import text
                    synced = set(
                        r[0] for r in db.execute(
                            text("SELECT DISTINCT repo FROM local_code_cache")
                        ).fetchall()
                    )
                    if expected_repos.issubset(synced):
                        break
                finally:
                    db.close()
                await asyncio.sleep(5)

        mem = MemoryService()
        stats = mem.get_stats()
        logger.info(
            f"Knowledge base has {stats.get('total', 0)} entries, "
            f"starting incremental build..."
        )
        loop = asyncio.get_event_loop()

        def _build():
            return mem.build_code_knowledge()

        result = await loop.run_in_executor(None, _build)
        logger.info(f"Knowledge base build complete: {result}")
    except Exception:
        logger.exception("Failed to initialize knowledge base")


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
        # 放行：SPA 静态资源、FastAPI 静态文件、健康检查
        if path.startswith("/assets/") or path.startswith("/static/") or path in ("/health",):
            return await call_next(request)

        # 放行 SPA 客户端路由（非 /api/ 开头的路径，交给 SPAStaticFiles 返回 index.html）
        if not path.startswith("/api/"):
            return await call_next(request)

        # /api/* 路径：需要 Bearer Token 认证

        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[7:] == Config.API_KEY:
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
from app.api.personal_todo import router as personal_todo_router
from app.api.intelligence import router as intelligence_router
from app.api.articles import router as articles_router
from app.api.sync import router as sync_router
from app.api.model_anatomy import router as model_anatomy_router
from app.api.users import router as users_router
from app.api.repos import router as repos_router
from app.api.ai_agent import router as ai_agent_router

app.include_router(community_router, prefix="/api/community", tags=["Community Pulse"])
app.include_router(pr_center_router, prefix="/api/pr-center", tags=["PR Command Center"])
app.include_router(ai_assistant_router, prefix="/api/ai-assistant", tags=["AI Assistant"])
app.include_router(watchlist_router, prefix="/api/watchlist", tags=["Watchlist"])
app.include_router(personal_todo_router, prefix="/api/personal-todo", tags=["Personal Todo"])
app.include_router(intelligence_router, prefix="/api/intelligence", tags=["Intelligence Reports"])
app.include_router(articles_router, prefix="/api/articles", tags=["Articles"])
app.include_router(sync_router, prefix="/api/sync", tags=["Sync"])
app.include_router(model_anatomy_router, prefix="/api/anatomy", tags=["Model Anatomy"])
app.include_router(users_router, prefix="/api/users", tags=["Users"])
app.include_router(repos_router, prefix="/api/repos", tags=["Repos"])
app.include_router(ai_agent_router, prefix="/api/ai-agent", tags=["AI Agent"])


# 静态文件
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir), html=False), name="static")

# 健康检查、刷新、状态等 API 路由
@app.get("/health")
async def health_check():
    """健康检查"""
    scheduler_info = get_sync_status()
    return {
        "status": "ok",
        "version": "0.1.0",
        "debug": Config.DEBUG,
        "configured": bool(Config.GITHUB_PAT),
        "scheduler_running": scheduler_info.get("running", False),
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


# Vue SPA (新前端) - 构建输出到 static/dist/
class SPAStaticFiles(StarletteStaticFiles):
    async def get_response(self, path: str, scope):
        # 如果文件实际存在（如 /assets/index-xxx.js），返回文件内容
        full_path, stat_result = self.lookup_path(path)
        if stat_result is not None:
            return await super().get_response(path, scope)
        # 否则返回 index.html（SPA 路由）
        return await super().get_response("index.html", scope)

spa_dir = static_dir / "dist"
if spa_dir.exists():
    # SPA 挂载在根路径 / 下，不干扰 /api/* 和 /health 等路径
    app.mount("/", SPAStaticFiles(directory=str(spa_dir), html=True), name="app")
else:
    @app.get("/")
    async def root():
        return {"message": "Frontend not built yet. Run 'cd frontend && npm run build' first."}


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
