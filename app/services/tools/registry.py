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
        names: 工具名称列表，None 则返回所有已注册工具

    Returns:
        OpenAI tools 参数格式的列表
    """
    if names is None:
        return [t["schema"] for t in _tools.values()]

    schemas = []
    for name in names:
        tool = _tools.get(name)
        if tool:
            schemas.append(tool["schema"])
        else:
            logger.warning(f"Tool '{name}' not found in registry")
    return schemas


def list_tools() -> List[Dict[str, Any]]:
    """列出所有已注册工具的元信息（不含 schema 详情）"""
    return [
        {
            "name": t["name"],
            "description": t["schema"].get("function", {}).get("description", ""),
            "parameters": t["schema"].get("function", {}).get("parameters", {}),
        }
        for t in _tools.values()
    ]


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
        result = await handler(args)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        logger.exception(f"Tool '{name}' execution failed")
        return {"error": str(e)}