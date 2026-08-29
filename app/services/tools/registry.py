"""
Tool 注册表核心

注册/查找/列出所有可用工具。
AgentRunner 通过名称查找 tool 并调用 handler。

新增一个 tool 只需要：
1. 新建文件定义 schema + handler
2. 调用 register_tool() 注册
3. 在 __init__.py 中 import
"""
import logging
from typing import Callable, Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# 全局注册表
_tools: Dict[str, dict] = {}

# 工具类别映射：前端可按类别请求，后端展开成具体工具。
# 新增工具时只需在 register_tool() 之后把名字加到对应类别即可。
CATEGORY_TOOLS: Dict[str, List[str]] = {
    "github": [
        "search_issues",
        "get_issue_detail",
        "get_pr_diff",
        "get_github_releases",
    ],
    "knowledge": [
        "search_memory",
        "search_by_tags",
    ],
    "code": [
        "read_local_code",
        "search_code",
    ],
    "doc": [
        "search_docs",
    ],
    "academic": [
        "search_arxiv",
    ],
    "web": [
        "search_web",
        "extract_web_content",
    ],
    # 写类工具：AI 可创建/更新/删除项目实体（删除带 confirm 守卫）。
    # 不挂限流器（rate_limiter 对未知名返回 None）。
    "write": [
        "create_rule",
        "update_rule",
        "delete_rule",
        "create_task",
        "update_task",
        "delete_task",
        "create_article",
        "update_article",
        "delete_article",
        "import_anatomy_yaml",
        "generate_intelligence_report",
        "list_entities",
    ],
}


def register_tool(name: str, schema: dict, handler: Callable) -> None:
    """注册一个 tool。

    Args:
        name: tool 名称（唯一标识，在 agent_runner 中通过此名称查找）
        schema: OpenAI function calling 的 tool schema（完整 structure 对象）
        handler: 异步处理函数，接收 (args: dict) -> dict
    """
    if name in _tools:
        logger.warning(f"Tool '{name}' already registered, overwriting")
    _tools[name] = {
        "name": name,
        "schema": schema,
        "handler": handler,
    }
    logger.debug(f"Tool registered: {name}")


def get_tool(name: str) -> Optional[Dict[str, Any]]:
    """按名称查找 tool"""
    return _tools.get(name)


def get_tool_schemas(names: Optional[List[str]] = None) -> List[dict]:
    """获取指定工具列表的 OpenAI function calling schema。

    Args:
        names: 工具或类别名称列表。None 返回全部。
               类别名会自动展开为对应具体工具，类别+具体工具名可混传，
               重复项会去重（按出现顺序）。

    Returns:
        OpenAI tools 参数格式的列表
    """
    if names is None:
        return [t["schema"] for t in _tools.values()]

    # 先把类别名展开成具体工具名
    expanded: List[str] = []
    for name in names:
        if name in CATEGORY_TOOLS:
            expanded.extend(CATEGORY_TOOLS[name])
        else:
            expanded.append(name)

    # 去重 + 查表（保持出现顺序）
    seen = set()
    schemas: List[dict] = []
    for name in expanded:
        if name in seen:
            continue
        seen.add(name)
        tool = _tools.get(name)
        if tool:
            schemas.append(tool["schema"])
        else:
            logger.warning(f"Tool '{name}' not found in registry")
    return schemas


async def execute_tool(name: str, args: dict) -> dict:
    """执行指定名称的 tool。

    Args:
        name: tool 名称
        args: 参数 dict

    Returns:
        工具执行结果 dict
    """
    tool = _tools.get(name)
    if not tool:
        return {"error": f"Tool '{name}' not found"}

    handler = tool["handler"]
    try:
        if handler is None:
            return {"error": f"Tool '{name}' has no handler"}

        # 速率限制：根据工具名获取对应的限流器
        from app.services.tools.rate_limiter import get_limiter_for_tool
        limiter = get_limiter_for_tool(name)
        if limiter:
            wait = await limiter.acquire()
            if wait > 0:
                logger.debug(f"Rate limited tool '{name}', waited {wait:.2f}s")

        result = await handler(args)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        logger.exception(f"Tool '{name}' execution failed")
        return {"error": str(e)}