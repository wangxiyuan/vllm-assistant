"""
知识库搜索工具

AI 可以通过这些工具搜索本地知识库，实现"一次提取，多次复用"。
"""
import logging
from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)


def _get_memory_service():
    """延迟导入 MemoryService，避免循环依赖"""
    from app.services.memory_service import MemoryService
    return MemoryService()


# ======================================================================
# Tool 1: search_memory
# ======================================================================

SEARCH_MEMORY = {
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": "在本地知识库中搜索相关信息。知识库包含代码结构、文档摘要、历史 issue/PR 讨论、学习文章等。优先使用此工具，不够再调 read_local_code 或 search_issues。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，如 'attention kernel'、'tensor parallelism'",
                },
                "tags": {
                    "type": "string",
                    "description": "标签过滤，逗号分隔，如 'docs,vllm' 或 'code,attention'",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                },
            },
            "required": ["query"],
        },
    },
}


async def handle_search_memory(args: dict) -> dict:
    """搜索本地知识库"""
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    top_k = min(args.get("top_k", 5), 10)
    tags_str = args.get("tags", "")
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None

    mem = _get_memory_service()
    results = mem.recall(query=query, top_k=top_k, tags=tags)

    return {
        "results": results,
        "total": len(results),
        "query": query,
    }


# ======================================================================
# Tool 2: search_by_tags
# ======================================================================

SEARCH_BY_TAGS = {
    "type": "function",
    "function": {
        "name": "search_by_tags",
        "description": "按标签列出知识库条目。适合已知分类名（如 'attention'、'kernel'、'docs'）时快速定位知识。",
        "parameters": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "string",
                    "description": "标签，逗号分隔，如 'attention,kernel'",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                },
            },
            "required": ["tags"],
        },
    },
}


async def handle_search_by_tags(args: dict) -> dict:
    """按标签搜索知识库"""
    tags_str = args.get("tags", "")
    if not tags_str:
        return {"error": "tags is required"}

    tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    top_k = min(args.get("top_k", 5), 10)

    mem = _get_memory_service()
    results = mem.list_by_tags(tags=tags, top_k=top_k)

    return {
        "results": results,
        "total": len(results),
        "tags": tags,
    }


# ======================================================================
# 注册
# ======================================================================

register_tool("search_memory", SEARCH_MEMORY, handle_search_memory)
register_tool("search_by_tags", SEARCH_BY_TAGS, handle_search_by_tags)