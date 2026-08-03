"""
BaseAgent — Agent 公共基类

提取 AgentRunner 和 IntelligenceReportGenerator 的公共逻辑：
- system prompt 构建（含记忆注入、时间上下文、已配置仓库列表）
- 工具调用去重缓存
- 工具参数过滤（剔除 schema 外字段）
- 记忆服务懒加载
"""
import json
import logging
from typing import List, Dict, Optional, Any

from app.services.llm import LLMClient
from app.services.tools import registry as tool_registry

logger = logging.getLogger(__name__)


class BaseAgent:
    """Agent 公共基类——只做流程控制，不做业务逻辑"""

    # 最大 tool 循环轮次
    MAX_TOOL_ROUNDS = 30
    TOOL_TIMEOUT = 30.0

    def __init__(self):
        self.llm = LLMClient()
        self._memory_service = None
        # 工具调用缓存：同 (tool_name, filtered_args) 不重复执行
        self._tool_cache: Dict[str, dict] = {}

    async def close(self):
        await self.llm.aclose()

    # ======================================================================
    # 记忆服务
    # ======================================================================

    @property
    def memory_service(self):
        if self._memory_service is None:
            from app.services.memory_service import MemoryService
            self._memory_service = MemoryService()
        return self._memory_service

    # ======================================================================
    # 工具执行（带去重缓存 + 参数过滤）
    # ======================================================================

    def _get_declared_tool_props(self, tool_name: str):
        """从 tool schema 里取出声明的属性名集合"""
        from app.services.tools._shared import get_declared_tool_props
        return get_declared_tool_props(tool_name)

    def _filter_tool_args(self, tool_name: str, tool_args: dict) -> dict:
        """剔除 schema 未声明的字段，避免噪声字段导致缓存 miss 或执行异常"""
        declared = self._get_declared_tool_props(tool_name)
        if declared is not None:
            return {k: v for k, v in tool_args.items() if k in declared}
        return tool_args

    async def execute_tool_cached(self, tool_name: str, tool_args: dict) -> dict:
        """执行工具调用（带缓存）"""
        filtered_args = self._filter_tool_args(tool_name, tool_args)
        cache_key = f"{tool_name}::{json.dumps(filtered_args, sort_keys=True, ensure_ascii=False)}"
        if cache_key in self._tool_cache:
            logger.info("Tool %s cache hit", tool_name)
            return self._tool_cache[cache_key]
        logger.info("Executing tool: %s args=%s", tool_name, filtered_args)
        result = await tool_registry.execute_tool(tool_name, filtered_args)
        self._tool_cache[cache_key] = result
        return result

    def execute_tool_sync(self, tool_name: str, tool_args: dict) -> dict:
        """同步执行工具调用（带缓存），用于非 async 上下文"""
        filtered_args = self._filter_tool_args(tool_name, tool_args)
        cache_key = f"{tool_name}::{json.dumps(filtered_args, sort_keys=True, ensure_ascii=False)}"
        if cache_key in self._tool_cache:
            return self._tool_cache[cache_key]
        logger.info("Executing tool (sync): %s args=%s", tool_name, filtered_args)
        import asyncio
        result = asyncio.run(tool_registry.execute_tool(tool_name, filtered_args))
        self._tool_cache[cache_key] = result
        return result

    # ======================================================================
    # System Prompt 构建（记忆注入 + 时间上下文 + 仓库列表）
    # ======================================================================

    def _build_memory_context(self, query: str, top_k: int = 3) -> str:
        """从知识库召回相关记忆，返回格式化文本"""
        if not query.strip():
            return ""
        try:
            memories = self.memory_service.recall(query=query, top_k=top_k)
            if not memories:
                return ""
            memory_lines = []
            for i, mem in enumerate(memories, 1):
                content_preview = mem.get("content", "")[:300]
                source_ref = mem.get("source_ref", "")
                source_type = mem.get("source_type", "")
                tags = ", ".join(mem.get("tags", [])[:5])
                memory_lines.append(
                    f"[{i}] 来源: {source_type} | 引用: {source_ref} | 标签: {tags}\n{content_preview}"
                )
            return "\n\n---\n### 相关上下文（来自知识库）\n" + "\n\n".join(memory_lines)
        except Exception:
            logger.warning("Failed to recall memories", exc_info=True)
            return ""

    @staticmethod
    def _build_time_context() -> str:
        """返回当前 UTC 时间上下文"""
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        return (
            f"\n\n## 当前时间\n当前 UTC 时间：{now_utc.strftime('%Y-%m-%d %H:%M:%S')}。\n"
            f"用户问题中的时间范围（如'最近 N 天'）请以这个日期为基准计算。\n"
            f"搜索时优先使用工具的 days_back 参数指定时间范围，而不是依赖默认值。"
        )

    @staticmethod
    def _build_repo_list_text() -> str:
        """返回已配置仓库列表文本"""
        try:
            from app.database import SessionLocal
            from app.models import RepoCache
            db = SessionLocal()
            try:
                repos = [r.repo for r in db.query(RepoCache).filter(
                    RepoCache.status == "active"
                ).all()]
            finally:
                db.close()
            if repos:
                names = "、".join(repos)
                return f"\n\n## 已配置的代码仓库\n当前支持的项目：{names}。GitHub 搜索工具（search_issues 等）可搜索任意 GitHub 仓库，不受此限制。"
        except Exception:
            logger.warning("Failed to query repos", exc_info=True)
        return ""