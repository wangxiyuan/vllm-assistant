"""
本地代码缓存查询服务
本地代码同步服务（LocalCodeSyncService）

只读缓存查询服务，不负责同步，同步由 RepoManager 负责
"""
from typing import List, Optional

from app.models import LocalCodeCache


class LocalCodeSyncService:
    """只读缓存查询服务（不负责同步，同步由 RepoManager 负责）"""

    def __init__(self, db):
        self.db = db

    def get_file_lines(self, repo: str, file_path: str) -> Optional[List[str]]:
        """获取缓存的文件行列表"""
        cached = self.db.query(LocalCodeCache).filter(
            LocalCodeCache.repo == repo,
            LocalCodeCache.file_path == file_path,
        ).first()
        if cached:
            return cached.content.split("\n")
        return None

    def get_file_content(self, repo: str, file_path: str) -> Optional[str]:
        """获取缓存的文件内容"""
        cached = self.db.query(LocalCodeCache).filter(
            LocalCodeCache.repo == repo,
            LocalCodeCache.file_path == file_path,
        ).first()
        return cached.content if cached else None

    def batch_get_snippets(self, refs: List[dict]) -> List[dict]:
        """批量获取代码片段"""
        results = []
        for ref in refs:
            repo = ref.get("repo")
            if not repo:
                from app.services._shared import get_default_repo_short
                repo = get_default_repo_short()
            file_path = ref["file_path"]
            start_line = ref["line_start"]
            end_line = ref.get("line_end", start_line)

            lines = self.get_file_lines(repo, file_path)
            if lines is None or start_line > len(lines) or end_line > len(lines):
                results.append({
                    "repo": repo,
                    "file_path": file_path,
                    "line_start": start_line,
                    "line_end": end_line,
                    "is_valid": False,
                    "reason": "line_out_of_range",
                })
            else:
                content = "\n".join(lines[start_line - 1:end_line])
                results.append({
                    "repo": repo,
                    "file_path": file_path,
                    "line_start": start_line,
                    "line_end": end_line,
                    "is_valid": True,
                    "content": content,
                })
        return results