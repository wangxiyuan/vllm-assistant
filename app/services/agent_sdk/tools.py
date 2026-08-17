"""
OpenAI Agents SDK — 工具适配

把项目自有的 tools/registry 工具（OpenAI-compatible schema + async handler）
包装成 SDK 的 FunctionTool。保留原有的：
- schema 外字段剔除
- 去重缓存（跨阶段共享）
- 限流（rate_limiter）
- 工具输出截断（防上下文膨胀）
"""
import json
import logging

from agents import FunctionTool

from app.config import Config
from app.services.tools import registry as tool_registry
from app.services.tools._shared import get_declared_tool_props
from app.services.tools.rate_limiter import get_limiter_for_tool

logger = logging.getLogger(__name__)


def _safe_json_loads(s: str) -> dict:
    if not s:
        return {}
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _filter_tool_args(tool_name: str, tool_args: dict) -> dict:
    declared = get_declared_tool_props(tool_name)
    if declared is not None:
        return {k: v for k, v in tool_args.items() if k in declared}
    return tool_args


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


def _make_handler(name: str, cache: dict) -> callable:
    """构造 FunctionTool 的 on_invoke_tool。

    接受 SDK 传入的 JSON 字符串参数，返回工具执行结果的 JSON 字符串。
    """
    async def _on_invoke(ctx, args_json: str) -> str:
        args = _filter_tool_args(name, _safe_json_loads(args_json))
        cache_key = name + "::" + json.dumps(args, sort_keys=True, ensure_ascii=False)
        if cache_key in cache:
            logger.info("Tool %s cache hit", name)
            result = cache[cache_key]
        else:
            logger.info("Executing tool: %s args=%s", name, args)
            result = await tool_registry.execute_tool(name, args)
            cache[cache_key] = result
        try:
            return _truncate(json.dumps(result, ensure_ascii=False), Config.AGENT_TOOL_OUTPUT_LIMIT)
        except (TypeError, ValueError):
            return _truncate(str(result), Config.AGENT_TOOL_OUTPUT_LIMIT)
    return _on_invoke


def build_sdk_tools(tool_names, cache: dict) -> list:
    """把 registry 工具集合或类别展开成 SDK FunctionTool 列表。

    Args:
        tool_names: 工具/类别名列表；None 表示全部；[] 表示不使用工具
        cache: 本次 run 共享的去重缓存 dict
    """
    if tool_names is not None:
        schemas = tool_registry.get_tool_schemas(tool_names)
    else:
        schemas = tool_registry.get_tool_schemas()

    tools = []
    for schema in schemas:
        fn = schema.get("function", {})
        name = fn.get("name")
        if not name:
            continue
        tools.append(FunctionTool(
            name=name,
            description=fn.get("description", ""),
            params_json_schema=fn.get("parameters", {"type": "object", "properties": {}}),
            on_invoke_tool=_make_handler(name, cache),
            strict_json_schema=False,
        ))
    return tools