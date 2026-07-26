"""
任务注册表

所有异步任务类型在此注册，一个文件一个任务。

新增任务三步：
1. 新建文件，实现处理函数
2. 调用 register_task() 注册
3. 在 __init__.py 中 import
"""
import logging
from typing import Callable, Dict, Optional, Any

logger = logging.getLogger(__name__)

_tasks: Dict[str, Callable] = {}


def register_task(name: str, handler: Callable) -> None:
    """注册一个任务类型"""
    if name in _tasks:
        logger.warning(f"Task '{name}' already registered, overwriting")
    _tasks[name] = handler
    logger.debug(f"Task registered: {name}")


def get_task(name: str) -> Optional[Callable]:
    """按名称查找任务 handler"""
    return _tasks.get(name)


def list_tasks() -> List[Dict[str, str]]:
    """列出所有已注册任务"""
    return [{"name": name} for name in _tasks]


async def execute_task(name: str, params: dict) -> Dict[str, Any]:
    """执行指定名称的任务

    Args:
        name: 任务类型名称
        params: 任务参数

    Returns:
        任务结果 dict
    """
    handler = _tasks.get(name)
    if not handler:
        return {"error": f"Task '{name}' not found"}

    try:
        result = await handler(params)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        logger.exception(f"Task '{name}' execution failed")
        return {"error": str(e)}