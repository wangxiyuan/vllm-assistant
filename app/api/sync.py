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
from app.models import Item, LocalCodeCache, MyPR
from app.services.github_client import GitHubClient
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


@router.get("/code/files")
async def list_cached_files(
    repo: str = Query("vllm"),
    q: str = Query("", description="搜索关键词"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """列出缓存的代码文件，支持前缀搜索"""
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


@router.get("/file-history")
def get_file_history(
    repo: str = Query("vllm"),
    file_path: str = Query(..., description="仓库内相对路径，如 vllm/engine/core.py"),
    db: Session = Depends(get_db),
):
    """查询某个文件在各 PR 中的变更历史

    优先从 FileChangeHistory 表查询（scheduler 定时填充），
    查询 O(1)，无 GitHub API 调用。
    若缓存未填充，回退到实时查询。
    """
    from app.models import FileChangeHistory, MyPR

    # 优先从缓存表查询
    records = db.query(FileChangeHistory).filter(
        FileChangeHistory.repo == repo,
        FileChangeHistory.file_path == file_path,
    ).order_by(FileChangeHistory.pr_number.desc()).all()

    if records:
        # 批量查询所有相关 PR 号，避免 N+1
        pr_numbers = [r.pr_number for r in records]
        my_pr_nums = {
            row[0] for row in db.query(MyPR.pr_number).filter(
                MyPR.pr_number.in_(pr_numbers)).all()
        }
        prs = []
        for r in records:
            source = "my_pr" if r.pr_number in my_pr_nums else "community"
            prs.append({
                "pr_number": r.pr_number,
                "title": r.pr_title,
                "state": r.pr_state,
                "source": source,
                "additions": r.additions,
                "deletions": r.deletions,
                "status": r.change_status,
                "matched_by": "file_list",
            })
        return {
            "repo": repo,
            "file_path": file_path,
            "total_prs": len(prs),
            "prs": prs,
        }

    # 缓存未填充：回退到实时查询
    return _fallback_file_history(repo, file_path, db)


def _fallback_file_history(repo: str, file_path: str, db):
    """回退方案：从 MyPR 和 Item 表实时查询文件历史（全表扫描 + GitHub API）"""
    from app.models import Item
    from app.services.github_client import GitHubClient

    results = []
    file_name = file_path.split("/")[-1] if file_path else ""

    # 从 MyPR 表通过 title 粗略匹配
    my_prs = db.query(MyPR).all()
    for pr in my_prs:
        if file_name and file_name in (pr.title or ""):
            results.append({
                "pr_number": pr.pr_number, "title": pr.title,
                "state": pr.state, "branch": pr.branch, "source": "my_pr",
            })
            continue

    # 从 Item 表通过 title 粗略匹配
    community_prs = db.query(Item).filter(Item.type == "pr").all()
    for pr in community_prs:
        if file_name and file_name in (pr.title or ""):
            results.append({
                "pr_number": pr.number, "title": pr.title,
                "state": pr.state, "source": "community",
            })

    # 对 open PR 做精确匹配（最多 10 个）
    client = GitHubClient()
    exact_matches = []
    checked_prs = set()
    candidates = []
    for pr in db.query(MyPR).filter(MyPR.state == "open").all():
        candidates.append({"num": pr.pr_number, "title": pr.title, "state": pr.state, "source": "my_pr"})
    for pr in db.query(Item).filter(Item.type == "pr", Item.state == "open").all():
        candidates.append({"num": pr.number, "title": pr.title, "state": pr.state, "source": "community"})

    for c in candidates[:10]:
        pr_num = c["num"]
        if pr_num in checked_prs:
            continue
        checked_prs.add(pr_num)
        try:
            files = client.get_pull_files(pr_num) or []
            for f in files:
                fname = f.get("filename", "")
                if fname == file_path or fname.endswith("/" + file_path):
                    exact_matches.append({
                        "pr_number": pr_num, "title": c["title"], "state": c["state"],
                        "source": c["source"], "matched_by": "file_list",
                        "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                        "status": f.get("status", "modified"),
                    })
                    break
        except Exception:
            continue

    seen = set()
    merged = []
    for m in exact_matches + results:
        key = str(m["pr_number"])
        if key not in seen:
            seen.add(key)
            merged.append(m)
    merged.sort(key=lambda x: x["pr_number"], reverse=True)

    return {"repo": repo, "file_path": file_path, "total_prs": len(merged), "prs": merged}