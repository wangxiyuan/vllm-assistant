"""
Shared utilities for API clients and common patterns.
"""
import logging
from typing import Optional, Dict, List, Tuple

from app.services.github_client import GitHubClient

logger = logging.getLogger(__name__)


def get_github_client() -> GitHubClient:
    """Get or create the global GitHubClient singleton.

    Used by all API modules that need GitHub API access.
    Avoids creating multiple client instances with separate sessions.
    """
    if not hasattr(get_github_client, "_instance"):
        get_github_client._instance = GitHubClient()
    return get_github_client._instance


def get_active_repo_map() -> Dict[str, str]:
    """返回活跃仓库的 短名 -> 完整 owner/repo 映射（从 RepoCache 动态加载）。

    如 ``{"vllm": "vllm-project/vllm", "sglang": "sgl-project/sglang"}``
    """
    from app.database import SessionLocal
    from app.models import RepoCache

    result: Dict[str, str] = {}
    db = SessionLocal()
    try:
        repos = db.query(RepoCache).filter(RepoCache.status == "active").all()
        for r in repos:
            full = _clone_url_to_full_repo(r.clone_url)
            if full:
                result[r.repo] = full
    except Exception:
        logger.warning("Failed to load repo map from DB, using fallback")
    finally:
        db.close()

    return result


def get_default_repo_short() -> str:
    """返回默认仓库短名（取 RepoCache 中第一个 active 仓库）"""
    repo_map = get_active_repo_map()
    if repo_map:
        return next(iter(repo_map))
    return ""


def resolve_repo_short_to_full(short_name: str) -> str:
    """将仓库短名解析为完整 owner/repo。

    先从 RepoCache 查找，找不到时返回空字符串。
    """
    if "/" in short_name:
        return short_name  # 已经是完整格式
    repo_map = get_active_repo_map()
    return repo_map.get(short_name, "")


def _clone_url_to_full_repo(clone_url: str) -> str:
    """从 clone_url 提取完整 owner/repo"""
    url = clone_url
    if url.endswith('.git'):
        url = url[:-4]
    parts = url.rstrip('/').split('/')
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return ""