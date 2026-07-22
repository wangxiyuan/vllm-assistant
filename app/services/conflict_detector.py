"""
PR冲突检测模块

DESIGN.md 77, 293 行：通过 GitHub Compare API 检测冲突，
无需本地 clone 仓库。
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ConflictDetector:
    """通过 GitHub Compare API 检测 PR 与 base 分支的冲突"""

    def __init__(self, github_client=None):
        """
        Args:
            github_client: GitHubClient 实例（推荐）。如果不传则懒加载。
        """
        if github_client is not None:
            self._client = github_client
        else:
            # 懒加载
            from app.services.github_client import GitHubClient
            self._client = GitHubClient()

    def detect_conflicts(self, pr_number: int) -> Dict[str, Any]:
        """通过 Compare API 检测 PR 是否落后且不可 clean merge

        Returns:
            {
                "has_conflict": bool,
                "behind_count": int,
                "ahead_count": int,
                "can_fast_forward": bool,
                "mergeable": Optional[bool],
                "last_sync_time": str (ISO),
            }
        """
        try:
            pr = self._client.get_pull(pr_number)
            if not pr or not isinstance(pr, dict):
                return self._error("PR not found")

            base = (pr.get("base") or {}).get("ref", "main")
            head = (pr.get("head") or {}).get("sha", "")
            base_sha = (pr.get("base") or {}).get("sha", "")

            if not base_sha or not head:
                return self._error("Missing base/head sha")

            compare = self._client.compare_branches(base_sha, head) or {}
            ahead = int(compare.get("ahead_by") or 0)
            behind = int(compare.get("behind_by") or 0)
            mergeable = compare.get("mergeable")
            # 兼容 GitHub PR 对象直接的 mergeable 字段
            if mergeable is None and "mergeable" in pr:
                mergeable = pr.get("mergeable")

            # can_fast_forward: behind == 0（PR 包含了 base 的所有内容）
            can_ff = behind == 0
            has_conflict = behind > 0 and mergeable is False

            return {
                "has_conflict": bool(has_conflict),
                "behind_count": behind,
                "ahead_count": ahead,
                "can_fast_forward": bool(can_ff),
                "mergeable": mergeable,
                "base_ref": base,
                "last_sync_time": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            }
        except Exception as e:
            logger.exception("detect_conflicts failed")
            return self._error(str(e))

    @staticmethod
    def _error(msg: str) -> Dict[str, Any]:
        return {
            "has_conflict": False,
            "behind_count": 0,
            "ahead_count": 0,
            "can_fast_forward": False,
            "mergeable": None,
            "error": msg,
        }
