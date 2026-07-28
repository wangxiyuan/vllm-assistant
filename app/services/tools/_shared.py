"""
Tools 模块共享工具函数

主要供 AgentRunner 和 IntelligenceReportGenerator 等不同 agent 循环复用。
"""
from typing import Optional, Set


def get_declared_tool_props(tool_name: str) -> Optional[Set[str]]:
    """从 tool schema 里取出声明的属性名集合。

    用来在执行/缓存前剔除模型塞进来的 schema 外字段，避免同语义不同噪声
    key 导致缓存 miss、重复执行。

    Args:
        tool_name: 工具名称

    Returns:
        声明属性名的 set，或 None（工具未找到时）
    """
    from . import registry as tool_registry

    tool_def = tool_registry.get_tool(tool_name)
    if not tool_def:
        return None
    params = tool_def.get("schema", {}).get("function", {}).get("parameters", {})
    props = params.get("properties")
    if not isinstance(props, dict):
        return None
    return set(props.keys())