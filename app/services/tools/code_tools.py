"""
本地代码读取工具

AI 可以通过这些工具读取本地缓存的代码文件。
仅在知识库检索不够时使用（避免重复读取源码）。
"""
import logging

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
        "description": "读取本地已缓存的代码文件或文档文件。当知识库检索不够时，用此工具读取具体文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径（相对于仓库根目录），如 'vllm/vllm/attention/layer.py'",
                },
                "repo": {
                    "type": "string",
                    "description": "仓库名，如 'vllm'，'vllm-ascend' 等，默认 'vllm'",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "最大返回行数，默认 100",
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

    repo = args.get("repo", "vllm")
    max_lines = min(args.get("max_lines", 100), 500)

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

        # 截断
        if total_lines > max_lines:
            # 取前 max_lines 行
            content = "\n".join(lines[:max_lines])
            truncated = True
        else:
            content = entry.content
            truncated = False

        return {
            "file_path": file_path,
            "repo": repo,
            "content": content,
            "total_lines": total_lines,
            "returned_lines": min(total_lines, max_lines),
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
        "description": "在本地缓存的代码中搜索关键词。返回匹配的文件路径和行号。适合快速定位代码位置。",
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "repo": {
                    "type": "string",
                    "description": "仓库名，如 'vllm'，'vllm-ascend' 等，默认 'vllm'",
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

    repo = args.get("repo", "vllm")
    max_results = min(args.get("max_results", 10), 30)

    db = SessionLocal()
    try:
        query = db.query(LocalCodeCache).filter(
            LocalCodeCache.repo == repo,
            LocalCodeCache.content.contains(keyword),
        ).limit(max_results)

        results = []
        for entry in query.all():
            # 找到匹配的行号
            matched_lines = []
            for i, line in enumerate(entry.content.split("\n"), 1):
                if keyword in line:
                    matched_lines.append({
                        "line": i,
                        "content": line.strip()[:200],
                    })
                    if len(matched_lines) >= 3:  # 每个文件最多 3 行
                        break

            results.append({
                "file_path": entry.file_path,
                "repo": entry.repo,
                "matched_lines": matched_lines,
                "total_matches": len(matched_lines),
            })

        return {
            "results": results,
            "total": len(results),
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