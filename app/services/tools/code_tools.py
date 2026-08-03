"""
本地代码读取工具

AI 可以通过这些工具读取本地缓存的代码文件。
仅在知识库检索不够时使用（避免重复读取源码）。
"""
import logging
from typing import Optional

from app.database import SessionLocal
from app.models import LocalCodeCache
from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)


# ======================================================================
# Tool: read_local_code
# ======================================================================

READ_LOCAL_CODE = {
    "type": "function",
    "function": {
        "name": "read_local_code",
        "description": (
            "读取本地已缓存的代码文件或文档文件（支持指定行号区间）。"
            "当知识库检索不够时，用此工具读取具体文件。"
            "读取大文件时，先用 search_code 定位关键行，再用 start_line + max_lines 精准切片，避免重叠读取。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径（相对于仓库根目录），如 'vllm/vllm/attention/layer.py'",
                },
                "repo": {
                    "type": "string",
                    "description": "仓库名，不传则用默认仓库",
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（0-based，包含），默认 0。读取大文件时分段用，从上次结束的行开始",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "最大返回行数，默认 100，上限 1500。设为 0 或超过文件总行数表示读到文件末尾",
                },
            },
            "required": ["file_path"],
        },
    },
}


async def handle_read_local_code(args: dict) -> dict:
    """读取本地缓存中的代码文件"""
    file_path = args.get("file_path", "").strip()
    if not file_path:
        return {"error": "file_path is required"}

    repo = args.get("repo")
    if not repo:
        from app.services._shared import get_default_repo_short
        repo = get_default_repo_short()
    # max_lines 默认 100，上限 1500；0 或负数视为「读到文件末尾」
    raw_max = args.get("max_lines", 100)
    try:
        raw_max = int(raw_max)
    except (TypeError, ValueError):
        raw_max = 100
    if raw_max <= 0:
        max_lines = None  # 读完全文
    else:
        max_lines = min(raw_max, 1500)

    try:
        start_line = int(args.get("start_line", 0) or 0)
    except (TypeError, ValueError):
        start_line = 0
    if start_line < 0:
        start_line = 0

    db = SessionLocal()
    try:
        entry = (
            db.query(LocalCodeCache)
            .filter(
                LocalCodeCache.repo == repo,
                LocalCodeCache.file_path == file_path,
            )
            .first()
        )
        if not entry or not entry.content:
            return {"error": f"File not found in cache: {repo}/{file_path}"}

        lines = entry.content.split("\n")
        total_lines = len(lines)

        if start_line >= total_lines:
            return {
                "error": f"start_line {start_line} out of range (total_lines={total_lines})",
                "file_path": file_path,
                "repo": repo,
                "total_lines": total_lines,
            }

        end_line = total_lines if max_lines is None else min(total_lines, start_line + max_lines)
        content = "\n".join(lines[start_line:end_line])
        truncated = end_line < total_lines

        return {
            "file_path": file_path,
            "repo": repo,
            "content": content,
            "total_lines": total_lines,
            "returned_lines": end_line - start_line,
            "start_line": start_line,
            "end_line": end_line,
            "truncated": truncated,
            "checksum": entry.checksum,
        }
    except Exception as e:
        logger.exception("Failed to read local code")
        return {"error": str(e)}
    finally:
        db.close()


# ======================================================================
# Tool: search_code
# ======================================================================

SEARCH_CODE = {
    "type": "function",
    "function": {
        "name": "search_code",
        "description": (
            "在本地缓存的代码中搜索关键词。返回匹配的文件路径、总匹配行数、和最多3行示例。"
            "结果按匹配行数降序排列，匹配最多的文件排最前。"
            "搜到结果后，应调用 read_local_code 读取关键文件的完整上下文来确认功能是否已实现。"
            "可用 file_pattern 限定到某目录/文件前缀，节省全仓库扫描。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "repo": {
                    "type": "string",
                    "description": "仓库名，不传则用默认仓库",
                },
                "file_pattern": {
                    "type": "string",
                    "description": (
                        "可选的文件路径前缀，例如 'vllm/v1/metrics/'。"
                        "会自动作为前缀匹配（无需自己加 %）。"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数，默认 10",
                },
            },
            "required": ["keyword"],
        },
    },
}


async def handle_search_code(args: dict) -> dict:
    """在本地缓存的代码中搜索关键词"""
    keyword = args.get("keyword", "").strip()
    if not keyword:
        return {"error": "keyword is required"}

    repo = args.get("repo")
    if not repo:
        from app.services._shared import get_default_repo_short
        repo = get_default_repo_short()
    max_results = min(args.get("max_results", 10), 30)

    raw_pattern = (args.get("file_pattern") or "").strip().rstrip("/")
    like_pattern: Optional[str] = None
    if raw_pattern:
        escaped = raw_pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_pattern = f"{escaped}%"

    db = SessionLocal()
    try:
        # 先查询所有匹配文件（不设 limit），统计每个文件的匹配行数
        query = db.query(LocalCodeCache).filter(
            LocalCodeCache.repo == repo,
            LocalCodeCache.content.contains(keyword),
        )
        if like_pattern:
            query = query.filter(LocalCodeCache.file_path.like(like_pattern, escape="\\"))

        all_entries = query.all()
        total_matched_files = len(all_entries)

        # 统计每个文件的匹配行数
        file_stats = []
        for entry in all_entries:
            match_count = entry.content.count(keyword)
            if match_count == 0:
                continue
            file_stats.append((entry, match_count))

        # 按匹配行数降序排列
        file_stats.sort(key=lambda x: x[1], reverse=True)

        # 截取前 max_results 个
        results = []
        for entry, match_count in file_stats[:max_results]:
            matched_lines = []
            for i, line in enumerate(entry.content.split("\n"), 1):
                if keyword in line:
                    matched_lines.append({
                        "line": i,
                        "content": line.strip()[:200],
                    })
                    if len(matched_lines) >= 3:
                        break

            results.append({
                "file_path": entry.file_path,
                "repo": entry.repo,
                "matched_lines": matched_lines,
                "total_matches_in_file": match_count,
            })

        return {
            "results": results,
            "total": len(results),
            "total_matched_files": total_matched_files,
            "truncated": total_matched_files > max_results,
            "keyword": keyword,
            "repo": repo,
        }
    except Exception as e:
        logger.exception("Failed to search code")
        return {"error": str(e)}
    finally:
        db.close()


# ======================================================================
# 注册
# ======================================================================

register_tool("read_local_code", READ_LOCAL_CODE, handle_read_local_code)
register_tool("search_code", SEARCH_CODE, handle_search_code)