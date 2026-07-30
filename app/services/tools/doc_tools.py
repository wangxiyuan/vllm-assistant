"""
文档知识检索工具

文档在源码仓库中，和代码一起被缓存，按扩展名（.md/.rst/.txt）识别。
"""
import logging
from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)


def _get_memory_service():
    """延迟导入 MemoryService，避免循环依赖"""
    from app.services.memory_service import MemoryService
    return MemoryService()


# ======================================================================
# Tool: search_docs
# ======================================================================

SEARCH_DOCS = {
    "type": "function",
    "function": {
        "name": "search_docs",
        "description": "在已配置项目的文档中搜索相关信息。文档来自源码仓库中的 .md/.rst/.txt 文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "项目名称（由仓库配置决定，不传则用默认仓库）",
                },
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
            },
            "required": ["project", "query"],
        },
    },
}


async def handle_search_docs(args: dict) -> dict:
    """从知识库检索本地缓存的文档知识"""
    project = args.get("project")
    if not project:
        from app.services._shared import get_default_repo_short
        project = get_default_repo_short()
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    mem = _get_memory_service()
    results = mem.recall(
        query=query,
        tags=["docs", project],
        source_types=["docs"],
    )

    # 如果 docs 层结果不够，再搜 code_structure 层
    if len(results) < 3:
        code_results = mem.recall(
            query=query,
            tags=["code", project],
            top_k=2,
        )
        results.extend(code_results)

    return {"results": results, "total": len(results), "query": query, "project": project}


# ======================================================================
# 注册
# ======================================================================

register_tool("search_docs", SEARCH_DOCS, handle_search_docs)