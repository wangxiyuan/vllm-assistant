"""
代码同步/缓存查询 API
对应 DESIGN-ARTICLES.md 4.3 代码缓存查询
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LocalCodeCache
from app.services.local_code_sync import LocalCodeSyncService

logger = logging.getLogger(__name__)
router = APIRouter()


class EmbedRef(BaseModel):
    repo: str = "vllm"
    file_path: str
    line_start: int
    line_end: Optional[int] = None


class EmbedRequest(BaseModel):
    refs: List[EmbedRef]


@router.get("/code/{file_path:path}")
async def get_cached_code(
    file_path: str,
    repo: str = Query("vllm"),
    line_start: Optional[int] = Query(None),
    line_end: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """获取缓存的代码文件内容（用于前端跳转预览）"""
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


@router.post("/code/embed")
async def batch_get_embeds(req: EmbedRequest, db: Session = Depends(get_db)):
    """批量获取多个代码片段，用于文章渲染时嵌入"""
    cache_service = LocalCodeSyncService(db)
    refs_list = [r.model_dump() for r in req.refs]
    snippets = cache_service.batch_get_snippets(refs_list)

    return {"snippets": snippets}