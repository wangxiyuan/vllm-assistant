"""
代码同步/缓存查询 API
对应 DESIGN-ARTICLES.md 4.3 代码缓存查询
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LocalCodeCache
from app.services.local_code_sync import LocalCodeSyncService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/code/files")
async def list_cached_files(
    repo: Optional[str] = Query(None, description="仓库名，不传则用默认仓库"),
    q: str = Query("", description="搜索关键词"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """列出缓存的代码文件，支持前缀搜索"""
    from app.services._shared import get_default_repo_short
    repo = repo or get_default_repo_short()
    query = db.query(LocalCodeCache.file_path).filter(
        LocalCodeCache.repo == repo,
    )
    if q:
        query = query.filter(LocalCodeCache.file_path.ilike(f"%{q}%"))
    rows = query.order_by(LocalCodeCache.file_path).limit(limit).all()
    return {"files": [r[0] for r in rows]}


@router.get("/code/{file_path:path}")
async def get_cached_code(
    file_path: str,
    repo: Optional[str] = Query(None, description="仓库名，不传则用默认仓库"),
    line_start: Optional[int] = Query(None),
    line_end: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """获取缓存的代码文件内容（用于前端跳转预览）"""
    from app.services._shared import get_default_repo_short
    repo = repo or get_default_repo_short()
    cache_service = LocalCodeSyncService(db)

    content = cache_service.get_file_content(repo, file_path)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found in cache")

    cached = db.query(LocalCodeCache).filter(
        LocalCodeCache.repo == repo,
        LocalCodeCache.file_path == file_path,
    ).first()

    total_lines = len(content.split("\n"))
    result = {
        "repo": repo,
        "file_path": file_path,
        "content": content,
        "total_lines": total_lines,
        "checksum": cached.checksum if cached else None,
        "last_synced_at": cached.last_synced_at.isoformat() if cached and cached.last_synced_at else None,
    }

    # 如果指定了行号范围，截取片段
    if line_start is not None:
        lines = content.split("\n")
        start = max(0, line_start - 1)
        end = min(len(lines), line_end or line_start)
        result["content"] = "\n".join(lines[start:end])
        result["line_start"] = line_start
        result["line_end"] = end

    return result