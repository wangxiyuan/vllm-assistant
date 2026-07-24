"""
Code Browser API - 代码浏览器

类似 IDE 的代码浏览功能：
- 目录树浏览（从本地 git 仓库读取）
- 文件内容查看（带行号）
- 文件变更历史（git log + PR 关联）
- 全文搜索
- Commit diff 查看
- Git blame 信息
"""
import logging
import subprocess
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.config import Config
from app.services.repo_manager import RepoManager

logger = logging.getLogger(__name__)
router = APIRouter()

# 最大文件大小（bytes），超过此大小拒绝直接读取
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

# 常见源码扩展名
TEXT_EXTENSIONS = frozenset({
    ".py", ".md", ".txt", ".yaml", ".yml", ".toml",
    ".cfg", ".ini", ".json", ".html", ".css", ".js",
    ".sh", ".c", ".cpp", ".h", ".hpp", ".rs", ".go",
    ".java", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".sql", ".proto", ".cmake", ".mk", ".dockerfile",
    ".conf", ".rst", ".tex", ".bib",
    ".kt", ".kts", ".swift", ".scala", ".rb", ".php",
    ".pl", ".pm", ".lua", ".r", ".m", ".mm",
    ".zig", ".nim", ".dart", ".ex", ".exs",
    ".gradle", ".properties", ".xml", ".svg", ".graphql",
    ".patch", ".diff", "",
})


def _get_repo_path(repo_name: str) -> Path:
    """获取仓库本地路径，验证存在性"""
    manager = RepoManager()
    local_path = manager.get_local_path(repo_name)
    if not local_path.exists():
        raise HTTPException(status_code=404, detail=f"Repo '{repo_name}' not cloned yet")
    return local_path


def _resolve_path(repo_path: Path, user_path: str) -> Path:
    """安全地解析路径，防止路径穿越"""
    target = (repo_path / user_path).resolve()
    repo_root = repo_path.resolve()
    if not str(target).startswith(str(repo_root)):
        raise HTTPException(status_code=400, detail="Invalid path: directory traversal detected")
    return target


@router.get("/repos")
async def list_repos():
    """获取所有可用的本地仓库列表"""
    manager = RepoManager()
    repos = []
    for repo_name in Config.REPOS:
        local_path = manager.get_local_path(repo_name)
        repos.append({
            "name": repo_name,
            "cloned": local_path.exists(),
        })
    return {"repos": repos}


@router.get("/tree")
async def get_tree(
    repo: str = Query("vllm"),
    path: str = Query("", description="仓库内相对路径，空=根目录"),
):
    """获取指定目录下的文件和子目录列表（懒加载）"""
    repo_path = _get_repo_path(repo)
    target = _resolve_path(repo_path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    dirs = []
    files = []
    try:
        for entry in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            name = entry.name
            rel_path = f"{path}/{name}" if path else name
            if entry.is_dir():
                # 跳过 .git 和 __pycache__ 等隐藏/缓存目录
                if name == ".git" or name == "__pycache__" or name.startswith("."):
                    continue
                dirs.append({"name": name, "path": rel_path})
            elif entry.is_file():
                ext = entry.suffix.lower()
                if ext in TEXT_EXTENSIONS:
                    try:
                        size = entry.stat().st_size
                        files.append({"name": name, "path": rel_path, "size": size})
                    except OSError:
                        continue
    except PermissionError:
        raise HTTPException(status_code=500, detail="Permission denied reading repo")

    return {
        "repo": repo,
        "path": path,
        "dirs": dirs,
        "files": files,
    }


@router.get("/file")
async def get_file(
    repo: str = Query("vllm"),
    path: str = Query(..., description="仓库内文件路径，如 vllm/engine/core.py"),
    start_line: int = Query(0, ge=0, description="起始行号（从1开始，0=从头）"),
    end_line: int = Query(0, ge=0, description="结束行号（0=到末尾）"),
):
    """获取文件内容（带行号信息），支持分片加载"""
    repo_path = _get_repo_path(repo)
    target = _resolve_path(repo_path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    file_size = target.stat().st_size

    # 检查文件大小
    if file_size > MAX_FILE_SIZE and start_line == 0 and end_line == 0:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({file_size / 1024 / 1024:.1f} MB). "
                   f"Max {MAX_FILE_SIZE / 1024 / 1024:.0f} MB. Use start_line/end_line to load in chunks.",
        )

    try:
        content = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        raise HTTPException(status_code=400, detail="File is not a text file or cannot be read")

    lines = content.split("\n")
    total_lines = len(lines)
    ext = target.suffix.lower()

    # 分片处理
    if start_line > 0 or end_line > 0:
        s = max(0, start_line - 1) if start_line > 0 else 0
        e = min(end_line, total_lines) if end_line > 0 else total_lines
        if s >= e:
            raise HTTPException(status_code=400, detail="Invalid line range")
        content = "\n".join(lines[s:e])
        line_offset = s + 1
    else:
        line_offset = 1

    return {
        "repo": repo,
        "path": path,
        "content": content,
        "total_lines": total_lines,
        "line_offset": line_offset,
        "extension": ext,
        "size": file_size,
    }


@router.get("/file-history")
async def get_file_history(
    repo: str = Query("vllm"),
    path: str = Query(..., description="仓库内文件路径"),
    max_count: int = Query(50, ge=1, le=200),
):
    """获取文件的 git commit 历史（从本地仓库用 git log）

    同时查询 FileChangeHistory 表关联 PR 号。
    """
    repo_path = _get_repo_path(repo)
    target = _resolve_path(repo_path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    # 用 git log 获取 commit 历史
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_count}",
             "--format=%H||%h||%an||%ai||%s",
             "--", path],
            cwd=str(repo_path),
            capture_output=True, text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"git log failed for {path}: {result.stderr}")
            return {"repo": repo, "path": path, "commits": []}
    except subprocess.TimeoutExpired:
        logger.warning(f"git log timed out for {path}")
        return {"repo": repo, "path": path, "commits": []}

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("||", 4)
        if len(parts) < 5:
            continue
        commits.append({
            "hash": parts[0],
            "short_hash": parts[1],
            "author": parts[2],
            "date": parts[3],
            "message": parts[4],
        })

    # 查询关联的 PR 号（从 FileChangeHistory 表）
    try:
        from app.database import SessionLocal
        from app.models import FileChangeHistory

        db = SessionLocal()
        try:
            records = db.query(FileChangeHistory).filter(
                FileChangeHistory.repo == repo,
                FileChangeHistory.file_path == path,
            ).all()
            pr_map = {}
            for r in records:
                pr_map[r.pr_number] = {"title": r.pr_title, "state": r.pr_state}
            # 为每条 commit 尝试匹配 PR（通过 commit message 中的 #NNN）
            for c in commits:
                m = re.search(r'#(\d+)', c["message"])
                if m:
                    pr_num = int(m.group(1))
                    if pr_num in pr_map:
                        c["pr_number"] = pr_num
                        c["pr_title"] = pr_map[pr_num]["title"]
                        c["pr_state"] = pr_map[pr_num]["state"]
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to query PR association")
        # 非关键错误，不影响 commit 列表返回

    return {
        "repo": repo,
        "path": path,
        "commits": commits,
    }


@router.get("/commit-diff")
async def get_commit_diff(
    repo: str = Query("vllm"),
    path: str = Query(..., description="仓库内文件路径"),
    commit_hash: str = Query(..., description="commit hash"),
):
    """获取某个 commit 中对指定文件的 diff"""
    repo_path = _get_repo_path(repo)

    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}^..{commit_hash}", "--", path],
            cwd=str(repo_path),
            capture_output=True, text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"git diff failed for {path}@{commit_hash}: {result.stderr}")
            return {"diff": "", "error": result.stderr}
    except subprocess.TimeoutExpired:
        return {"diff": "", "error": "timeout"}

    return {
        "repo": repo,
        "path": path,
        "commit_hash": commit_hash,
        "diff": result.stdout,
    }


@router.get("/blame")
async def get_file_blame(
    repo: str = Query("vllm"),
    path: str = Query(..., description="仓库内文件路径"),
):
    """获取文件的 git blame 信息（逐行最后修改信息）"""
    repo_path = _get_repo_path(repo)
    target = _resolve_path(repo_path, path)

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    try:
        result = subprocess.run(
            ["git", "blame", "--line-porcelain", "--", path],
            cwd=str(repo_path),
            capture_output=True, text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(f"git blame failed for {path}: {result.stderr}")
            return {"repo": repo, "path": path, "lines": []}
    except subprocess.TimeoutExpired:
        logger.warning(f"git blame timed out for {path}")
        return {"repo": repo, "path": path, "lines": []}

    lines = []
    current = {}
    for line in result.stdout.split("\n"):
        if line == "":
            continue
        if line.startswith("\t"):
            # 代码行内容
            current["line_content"] = line[1:]
            if current.get("hash") and current.get("hash") != "0000000000000000000000000000000000000000":
                lines.append(current)
            current = {}
        elif line.startswith("author "):
            current["author"] = line[7:]
        elif line.startswith("author-mail "):
            current["author_mail"] = line[12:]
        elif line.startswith("author-time "):
            current["author_time"] = line[12:]
        elif line.startswith("summary "):
            current["summary"] = line[8:]
        elif line.startswith("committer ") or line.startswith("committer-mail ") or \
             line.startswith("committer-time ") or line.startswith("committer-tz ") or \
             line.startswith("previous ") or line.startswith("boundary ") or \
             line.startswith("filename ") or line.startswith("author-tz "):
            # 这些 header 行都跳过
            pass
        elif re.match(r'^[0-9a-f]{40} ', line):
            # 第一行格式: commit_hash source_line_no result_line_no group_count
            parts = line.split(" ")
            if len(parts) >= 3:
                current["hash"] = parts[0]
                current["line_no"] = parts[2]

    return {
        "repo": repo,
        "path": path,
        "lines": lines,
    }


@router.get("/file-names")
async def search_file_names(
    repo: str = Query("vllm"),
    query: str = Query(..., min_length=1, description="文件名关键词"),
    max_results: int = Query(200, ge=1, le=500),
):
    """在仓库中按文件名搜索（全局过滤）

    用 find 命令搜索文件名包含关键词的文件，返回路径列表。
    与目录树浏览的过滤规则一致：跳过 .git / __pycache__ / 隐藏目录 / 非文本文件。
    """
    repo_path = _get_repo_path(repo)

    try:
        # find 搜索不区分大小写，跳过隐藏目录和 .git / __pycache__
        result = subprocess.run(
            ["find", ".", "-type", "f", "-iname", f"*{query}*",
             "-not", "-path", "./.git/*",
             "-not", "-path", "*/__pycache__/*",
             "-not", "-path", "*/.*"],
            cwd=str(repo_path),
            capture_output=True, text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"repo": repo, "query": query, "results": [], "truncated": False}

    if result.returncode not in (0, 1):
        logger.warning(f"find failed for {query}: {result.stderr}")
        return {"repo": repo, "query": query, "results": [], "truncated": False}

    results = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        # 格式: ./path/to/file.py
        file_path = line[2:]  # 去掉 "./"
        ext = Path(file_path).suffix.lower()
        if ext not in TEXT_EXTENSIONS:
            continue
        name = Path(file_path).name
        results.append({
            "path": file_path,
            "name": name,
            "extension": ext,
        })

    truncated = len(results) > max_results
    results = results[:max_results]

    return {
        "repo": repo,
        "query": query,
        "results": results,
        "truncated": truncated,
    }


@router.get("/search")
async def search_code(
    repo: str = Query("vllm"),
    query: str = Query(..., min_length=1, description="搜索关键词"),
    path: str = Query("", description="限定搜索路径，空=整个仓库"),
    max_results: int = Query(50, ge=1, le=200),
):
    """在仓库中全文搜索代码"""
    repo_path = _get_repo_path(repo)
    search_path = _resolve_path(repo_path, path) if path else repo_path

    if not search_path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    try:
        result = subprocess.run(
            ["grep", "-rn", "--binary-files=without-match",
             "-i", query, "."],
            cwd=str(search_path),
            capture_output=True, text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"repo": repo, "query": query, "results": [], "truncated": False}

    if result.returncode not in (0, 1):  # 1 = not found
        logger.warning(f"grep failed for {query}: {result.stderr}")
        return {"repo": repo, "query": query, "results": [], "truncated": False}

    results = []
    # 过滤掉 .git 目录的结果
    for line in result.stdout.split("\n"):
        if not line.strip() or ".git/" in line:
            continue
        # 格式: ./path/to/file:line_no:content
        m = re.match(r'^\./(.+?):(\d+):(.*)', line)
        if m:
            file_path = m.group(1)
            line_no = int(m.group(2))
            text = m.group(3)[:200]  # 截断显示
            ext = Path(file_path).suffix.lower()
            if ext in TEXT_EXTENSIONS:
                full_path = f"{path}/{file_path}" if path else file_path
                results.append({
                    "path": full_path,
                    "line_no": line_no,
                    "text": text,
                    "extension": ext,
                })

    truncated = len(results) > max_results
    results = results[:max_results]

    return {
        "repo": repo,
        "query": query,
        "results": results,
        "truncated": truncated,
    }