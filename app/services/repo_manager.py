"""
代码仓库管理服务
对应 DESIGN-ARTICLES.md 5.1 RepoManager

多仓库管理：clone、pull、同步到 LocalCodeCache
"""
import asyncio
import hashlib
import logging
import re
import shutil
import subprocess as _subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from app.config import Config

logger = logging.getLogger(__name__)


class RepoManager:
    """多仓库管理：clone、pull、同步到缓存"""

    CACHE_DIR = Config.BASE_DIR / "data" / "repos"

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def get_local_path(self, repo_name: str) -> Path:
        """获取仓库本地路径"""
        return self.CACHE_DIR / repo_name

    async def async_ensure_cloned(self, repo_name: str, clone_url: str, branch: str = "main"):
        """
        异步确保仓库已 clone（不阻塞服务启动）。
        已存在则 git pull --ff-only，不存在则 git clone --depth 1。
        clone/pull 完成后自动同步到 LocalCodeCache 并更新 RepoCache。
        """

        local_path = self.get_local_path(repo_name)
        if local_path.exists():
            await self._async_unshallow_if_needed(repo_name, local_path, branch)
            proc = await asyncio.create_subprocess_exec(
                "git", "pull", "--ff-only", "origin", branch,
                cwd=str(local_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"git pull failed for {repo_name}: {stderr.decode()}")
            else:
                logger.info(f"git pull succeeded for {repo_name}")
        else:
            # blobless 克隆：完整 commit 历史（供 commit 流水/AI 分诊用），不下载历史 blob
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--filter=blob:none", "--branch", branch,
                clone_url, str(local_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"git clone failed for {repo_name}: {stderr.decode()}")
                raise RuntimeError(f"Failed to clone {repo_name}: {stderr.decode()}")
            logger.info(f"git clone succeeded for {repo_name}")

        # 获取当前 commit SHA
        commit_sha = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "HEAD",
                cwd=str(local_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                commit_sha = stdout.decode().strip()
        except Exception:
            pass

        # clone/pull 完成后同步到 LocalCodeCache
        try:
            from app.database import SessionLocal
            db = SessionLocal()
            try:
                stats = self._sync_to_cache(repo_name, local_path, db)
                self._upsert_repo_cache(db, repo_name, clone_url, branch, commit_sha)
                db.commit()
                logger.info(f"Synced {repo_name} to cache: {stats}")
            except Exception:
                db.rollback()
                logger.exception(f"Sync to cache failed for {repo_name}")
            finally:
                db.close()
        except Exception:
            logger.exception(f"Failed to sync {repo_name} to cache")

    @staticmethod
    def full_name_from_clone_url(clone_url: str) -> str:
        """从 clone_url 提取 owner/name 全名（与 items.repo 同格式）"""
        url = (clone_url or "").strip().rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        parts = url.split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return ""

    def short_to_full_map(self, db) -> Dict[str, str]:
        """短仓库名（RepoCache.repo）→ owner/name 全名，仅含 active 仓库"""
        from app.models import RepoCache

        mapping = {}
        for r in db.query(RepoCache).filter(RepoCache.status == "active").all():
            full = self.full_name_from_clone_url(r.clone_url)
            if full:
                mapping[r.repo] = full
        return mapping

    def is_shallow(self, local_path: Path) -> bool:
        """判断本地仓库是否为浅克隆（无完整 commit 历史）"""
        try:
            result = _subprocess.run(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=str(local_path), capture_output=True, text=True,
            )
            return result.returncode == 0 and result.stdout.strip() == "true"
        except Exception:
            return False

    async def _async_unshallow_if_needed(self, repo_name: str, local_path: Path, branch: str):
        """存量浅克隆升级为 blobless 完整历史；失败只警告，不阻塞 pull"""
        if not self.is_shallow(local_path):
            return
        logger.info(f"Repo {repo_name} is shallow, fetching full history...")
        proc = await asyncio.create_subprocess_exec(
            "git", "fetch", "--unshallow", "--filter=blob:none", "origin", branch,
            cwd=str(local_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"git fetch --unshallow failed for {repo_name}: {stderr.decode()}")
        else:
            logger.info(f"Repo {repo_name} unshallowed successfully")

    def get_recent_commits(self, repo_name: str, since_days: int = 7,
                           limit: int = 200) -> list:
        """读取本地仓库最近 N 天的 commit（默认分支）。

        返回 [{sha, short_sha, author, committed_at(iso), subject, pr_number}]，
        pr_number 从 merge commit 的 "(#1234)" 尾缀提取，取不到为 None。
        仓库未 clone 时返回空列表。
        """
        local_path = self.get_local_path(repo_name)
        if not local_path.exists():
            return []
        sep, rec_sep = "\x1f", "\x1e"
        fmt = sep.join(["%H", "%h", "%an", "%aI", "%s"]) + rec_sep
        try:
            result = _subprocess.run(
                ["git", "log", f"--since={since_days} days ago",
                 "--pretty=format:" + fmt, "-n", str(limit)],
                cwd=str(local_path), capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning(f"git log failed for {repo_name}: {result.stderr[:200]}")
                return []
        except Exception:
            logger.exception(f"git log failed for {repo_name}")
            return []

        commits = []
        for line in result.stdout.split(rec_sep):
            line = line.strip("\n")
            if not line.strip():
                continue
            parts = line.split(sep)
            if len(parts) < 5:
                continue
            sha, short_sha, author, committed_at, subject = parts[:5]
            pr_number = None
            m = re.search(r"\(#(\d+)\)\s*$", subject)
            if m:
                pr_number = int(m.group(1))
            commits.append({
                "sha": sha,
                "short_sha": short_sha,
                "author": author,
                "committed_at": committed_at,
                "subject": subject,
                "pr_number": pr_number,
            })
        return commits

    def pull_and_sync(self, repo_name: str) -> Dict:
        """
        同步单个仓库：git pull → 更新 LocalCodeCache。
        串行执行（SQLite 不支持并发写）。
        """
        from app.database import SessionLocal
        from app.models import RepoCache

        local_path = self.get_local_path(repo_name)
        if not local_path.exists():
            return {"status": "not_cloned", "repo": repo_name}

        # 获取 repo 的 branch 和 clone_url
        db = SessionLocal()
        repo_record = db.query(RepoCache).filter(
            RepoCache.repo == repo_name, RepoCache.status == "active"
        ).first()
        branch = repo_record.branch if repo_record else "main"
        clone_url = repo_record.clone_url if repo_record else ""
        db.close()

        # 存量浅克隆先补全历史，再 git pull
        if self.is_shallow(local_path):
            unshallow = _subprocess.run(
                ["git", "fetch", "--unshallow", "--filter=blob:none", "origin", branch],
                cwd=str(local_path), capture_output=True, text=True,
            )
            if unshallow.returncode != 0:
                logger.warning(f"git fetch --unshallow failed for {repo_name}: {unshallow.stderr[:200]}")

        # git pull
        result = _subprocess.run(
            ["git", "pull", "--ff-only", "origin", branch],
            cwd=str(local_path), capture_output=True, text=True,
        )
        if result.returncode != 0:
            return {"status": "pull_failed", "repo": repo_name, "error": result.stderr}

        # 获取当前 commit SHA
        commit_sha = None
        try:
            sha_result = _subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(local_path), capture_output=True, text=True,
            )
            if sha_result.returncode == 0:
                commit_sha = sha_result.stdout.strip()
        except Exception:
            pass

        # 同步到 LocalCodeCache
        db = SessionLocal()
        try:
            stats = self._sync_to_cache(repo_name, local_path, db)
            self._upsert_repo_cache(db, repo_name, clone_url, branch, commit_sha)
            db.commit()
            return {"status": "ok", "repo": repo_name, **stats}
        except Exception:
            db.rollback()
            logger.exception(f"Sync to cache failed for {repo_name}")
            return {"status": "sync_failed", "repo": repo_name}
        finally:
            db.close()

    def _sync_to_cache(self, repo_name: str, local_path: Path, db) -> Dict:
        """扫描仓库下所有代码文件和文档文件，更新 LocalCodeCache"""
        from app.models import LocalCodeCache

        stats = {"created": 0, "updated": 0, "unchanged": 0, "errors": []}

        # 所有需要同步的文件扩展名
        exts = (".py", ".cpp", ".cu", ".h", ".hpp", ".cuh",
                ".md", ".rst", ".txt")

        # 逐扩展名搜索（比 rglob(*) 快很多，跳过 .git 等无关目录）
        for ext in exts:
            for file_path in sorted(local_path.rglob(f"*{ext}")):
                if ".git" in file_path.parts:
                    continue
                relative_path = str(file_path.relative_to(local_path)).replace("\\", "/")
                result = self._sync_file(repo_name, relative_path, file_path, db)
                if result["status"] == "created":
                    stats["created"] += 1
                elif result["status"] == "updated":
                    stats["updated"] += 1
                elif result["status"] == "unchanged":
                    stats["unchanged"] += 1
                else:
                    stats["errors"].append(result)

        return stats

    def _sync_file(self, repo: str, relative_path: str, full_path: Path, db) -> Dict:
        """同步单个文件到 LocalCodeCache"""
        try:
            content = full_path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(content.encode()).hexdigest()
            lines = content.split("\n")

            from app.models import LocalCodeCache
            cached = db.query(LocalCodeCache).filter(
                LocalCodeCache.repo == repo,
                LocalCodeCache.file_path == relative_path,
            ).first()

            if cached:
                if cached.checksum != checksum:
                    cached.content = content
                    cached.checksum = checksum
                    cached.total_lines = len(lines)
                    cached.last_synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    return {"status": "updated", "path": relative_path}
                return {"status": "unchanged", "path": relative_path}
            else:
                db.add(LocalCodeCache(
                    repo=repo,
                    file_path=relative_path,
                    content=content,
                    checksum=checksum,
                    total_lines=len(lines),
                    last_synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
                ))
                return {"status": "created", "path": relative_path}
        except Exception as e:
            logger.exception(f"Error syncing file {relative_path}")
            return {"status": "error", "path": relative_path, "error": str(e)}

    def validate_all_refs(self):
        """对所有受影响的文件做行号越界检查（轻量验证）"""
        from app.models import CodeReference
        from app.services.local_code_sync import LocalCodeSyncService
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            cache_service = LocalCodeSyncService(db)
            refs = db.query(CodeReference).all()
            for ref in refs:
                lines = cache_service.get_file_lines(ref.repo_name, ref.file_path)
                if lines is None:
                    continue
                total_lines = len(lines)
                if ref.line_start > total_lines or ref.line_end > total_lines:
                    ref.is_valid = False
                    ref.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
        finally:
            db.close()

    def _upsert_repo_cache(self, db, repo_name: str, clone_url: str,
                           branch: str, commit_sha: Optional[str]):
        """写入或更新 RepoCache 记录"""
        from app.models import RepoCache

        local_path = str(self.get_local_path(repo_name))
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        record = db.query(RepoCache).filter(RepoCache.repo == repo_name).first()
        if record:
            record.clone_url = clone_url
            record.local_path = local_path
            record.branch = branch
            record.last_synced_at = now
            if commit_sha:
                record.commit_sha = commit_sha
            record.updated_at = now
        else:
            db.add(RepoCache(
                repo=repo_name,
                clone_url=clone_url,
                local_path=local_path,
                branch=branch,
                last_synced_at=now,
                commit_sha=commit_sha,
                status="active",
                created_at=now,
                updated_at=now,
            ))

    def delete_local_repo(self, repo_name: str) -> bool:
        """删除本地仓库目录"""
        local_path = self.get_local_path(repo_name)
        if local_path.exists():
            try:
                shutil.rmtree(str(local_path))
                logger.info(f"Deleted local repo directory: {local_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete local repo {repo_name}: {e}")
                return False
        return True

    def checkout_branch(self, repo_name: str, branch: str) -> bool:
        """切换仓库分支"""
        local_path = self.get_local_path(repo_name)
        if not local_path.exists():
            return False
        try:
            # fetch then checkout
            _subprocess.run(
                ["git", "fetch", "origin", branch],
                cwd=str(local_path), capture_output=True, text=True,
            )
            result = _subprocess.run(
                ["git", "checkout", branch],
                cwd=str(local_path), capture_output=True, text=True,
            )
            if result.returncode != 0:
                # 尝试创建并跟踪远程分支
                result = _subprocess.run(
                    ["git", "checkout", "-b", branch, f"origin/{branch}"],
                    cwd=str(local_path), capture_output=True, text=True,
                )
            if result.returncode == 0:
                logger.info(f"Checked out branch '{branch}' for {repo_name}")
                return True
            else:
                logger.error(f"Failed to checkout branch '{branch}' for {repo_name}: {result.stderr}")
                return False
        except Exception as e:
            logger.exception(f"Error checking out branch for {repo_name}: {e}")
            return False