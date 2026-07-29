"""
Repos API - 仓库缓存管理
支持动态增删改，修改/删除时联动清理关联资源。
"""
import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RepoCache

logger = logging.getLogger(__name__)
router = APIRouter()


class RepoCreate(BaseModel):
    repo: str  # 仓库短名称，slug 格式
    clone_url: str
    branch: str = "main"


class RepoUpdate(BaseModel):
    repo: str = ""
    clone_url: str = ""
    branch: str = ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_repo_name(name: str) -> bool:
    """验证仓库名称格式（字母数字 + 短横线 + 下划线）"""
    import re
    return bool(re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', name))


# ===== 联动清理辅助函数 =====

def _cleanup_on_delete(db: Session, repo_name: str):
    """删除仓库时联动清理所有关联资源"""
    from app.models import LocalCodeCache, FileChangeHistory, CodeReference

    # 1. 删除 LocalCodeCache
    deleted = db.query(LocalCodeCache).filter(LocalCodeCache.repo == repo_name).delete()
    logger.info(f"Deleted {deleted} LocalCodeCache rows for repo '{repo_name}'")

    # 2. 删除 FileChangeHistory
    deleted = db.query(FileChangeHistory).filter(FileChangeHistory.repo == repo_name).delete()
    logger.info(f"Deleted {deleted} FileChangeHistory rows for repo '{repo_name}'")

    # 3. 标记 CodeReference 为无效
    updated = db.query(CodeReference).filter(
        CodeReference.repo_name == repo_name
    ).update({"is_valid": False}, synchronize_session=False)
    logger.info(f"Marked {updated} CodeReference rows invalid for repo '{repo_name}'")

    # 4. 标记 AI Memory 为过期（软删除，tag 包含该 repo 名的条目）
    from app.services.memory_service import MemoryService
    mem = MemoryService()
    count = mem.forget_by_source_ref_prefix(f"{repo_name}/")
    logger.info(f"Marked {count} AI Memory entries stale for repo '{repo_name}'")

    db.commit()


def _cleanup_on_repo_rename(db: Session, old_name: str, new_name: str):
    """重命名仓库时更新所有关联表中的 repo 字段"""
    from app.models import LocalCodeCache, FileChangeHistory, CodeReference

    # 1. 更新 LocalCodeCache
    updated = db.query(LocalCodeCache).filter(
        LocalCodeCache.repo == old_name
    ).update({"repo": new_name}, synchronize_session=False)
    logger.info(f"Renamed {updated} LocalCodeCache rows: '{old_name}' -> '{new_name}'")

    # 2. 更新 FileChangeHistory
    updated = db.query(FileChangeHistory).filter(
        FileChangeHistory.repo == old_name
    ).update({"repo": new_name}, synchronize_session=False)
    logger.info(f"Renamed {updated} FileChangeHistory rows: '{old_name}' -> '{new_name}'")

    # 3. 标记旧名称的 CodeReference 为无效
    updated = db.query(CodeReference).filter(
        CodeReference.repo_name == old_name
    ).update({"is_valid": False}, synchronize_session=False)
    logger.info(f"Marked {updated} CodeReference rows invalid for renamed repo '{old_name}'")

    # 4. 更新 AI Memory 中 tag 包含旧 repo 名的条目
    from app.services.memory_service import MemoryService
    mem = MemoryService()
    count = mem.forget_by_source_ref_prefix(f"{old_name}/")
    logger.info(f"Marked {count} AI Memory entries stale for renamed repo '{old_name}'")

    db.commit()


# ===== API 端点 =====


@router.get("")
async def list_repos(db: Session = Depends(get_db)):
    """获取仓库列表（仅返回活跃仓库）"""
    repos = db.query(RepoCache).filter(
        RepoCache.status == "active"
    ).order_by(RepoCache.repo).all()
    return {"repos": [r.to_dict() for r in repos]}


@router.get("/{repo_id}")
async def get_repo(repo_id: int, db: Session = Depends(get_db)):
    """获取单个仓库详情"""
    repo = db.query(RepoCache).filter(RepoCache.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found")
    return repo.to_dict()


@router.post("", status_code=201)
async def create_repo(req: RepoCreate, db: Session = Depends(get_db)):
    """创建新仓库，异步触发 clone"""
    if not req.repo.strip():
        raise HTTPException(status_code=400, detail="Repo name is required")
    if not req.clone_url.strip():
        raise HTTPException(status_code=400, detail="Clone URL is required")
    if not _validate_repo_name(req.repo.strip()):
        raise HTTPException(status_code=400, detail="Repo name must be alphanumeric (a-z, 0-9, -, _)")

    repo_name = req.repo.strip()
    clone_url = req.clone_url.strip()
    branch = req.branch.strip() or "main"

    # 检查重名
    existing = db.query(RepoCache).filter(RepoCache.repo == repo_name).first()
    if existing:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail=f"Repo '{repo_name}' already exists")
        else:
            # 重激活已删除的仓库
            existing.clone_url = clone_url
            existing.branch = branch
            existing.status = "active"
            existing.updated_at = _utcnow()
            db.commit()
            db.refresh(existing)

            # 异步 clone
            from app.services.repo_manager import RepoManager
            manager = RepoManager()
            asyncio.create_task(manager.async_ensure_cloned(repo_name, clone_url, branch=branch))

            return existing.to_dict()

    from app.services.repo_manager import RepoManager

    local_path = str(RepoManager.CACHE_DIR / repo_name)
    now = _utcnow()

    repo = RepoCache(
        repo=repo_name,
        clone_url=clone_url,
        local_path=local_path,
        branch=branch,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)

    # 异步触发 clone + sync
    manager = RepoManager()
    asyncio.create_task(manager.async_ensure_cloned(repo_name, clone_url, branch=branch))

    return repo.to_dict()


@router.put("/{repo_id}")
async def update_repo(repo_id: int, req: RepoUpdate, db: Session = Depends(get_db)):
    """更新仓库配置，联动清理关联资源"""
    repo = db.query(RepoCache).filter(RepoCache.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found")

    from app.services.repo_manager import RepoManager
    manager = RepoManager()

    old_repo_name = repo.repo
    changes = []

    # 1. 重命名
    if req.repo.strip() and req.repo.strip() != old_repo_name:
        new_name = req.repo.strip()
        if not _validate_repo_name(new_name):
            raise HTTPException(status_code=400, detail="Repo name must be alphanumeric (a-z, 0-9, -, _)")

        # 检查新名称是否冲突
        conflict = db.query(RepoCache).filter(
            RepoCache.repo == new_name, RepoCache.status == "active"
        ).first()
        if conflict and conflict.id != repo_id:
            raise HTTPException(status_code=409, detail=f"Repo '{new_name}' already exists")

        _cleanup_on_repo_rename(db, old_repo_name, new_name)
        repo.repo = new_name
        repo.local_path = str(manager.get_local_path(new_name))
        changes.append("repo_name")

    # 2. 修改 clone_url
    if req.clone_url.strip() and req.clone_url.strip() != repo.clone_url:
        repo.clone_url = req.clone_url.strip()
        changes.append("clone_url")

        # 删除旧本地目录
        manager.delete_local_repo(old_repo_name)

        # 异步重新 clone
        current_name = repo.repo
        asyncio.create_task(
            manager.async_ensure_cloned(current_name, req.clone_url.strip(), branch=repo.branch or "main")
        )

    # 3. 修改 branch
    if req.branch.strip() and req.branch.strip() != repo.branch:
        old_branch = repo.branch
        repo.branch = req.branch.strip()
        changes.append("branch")

        # 切换分支
        if not manager.checkout_branch(repo.repo, req.branch.strip()):
            logger.warning(f"Failed to checkout branch '{req.branch.strip()}' for {repo.repo}, reverting")
            repo.branch = old_branch

    repo.updated_at = _utcnow()
    db.commit()
    db.refresh(repo)
    return repo.to_dict()


@router.delete("/{repo_id}")
async def delete_repo(repo_id: int, db: Session = Depends(get_db)):
    """软删除仓库，联动清理所有关联资源"""
    repo = db.query(RepoCache).filter(RepoCache.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repo not found")

    repo_name = repo.repo

    # 1. 软删除 RepoCache
    repo.status = "deleted"
    repo.updated_at = _utcnow()
    db.commit()

    # 2. 清理关联资源
    _cleanup_on_delete(db, repo_name)

    # 3. 删除本地目录
    from app.services.repo_manager import RepoManager
    manager = RepoManager()
    manager.delete_local_repo(repo_name)

    return {"deleted": True, "repo": repo_name}
