"""
Agent system prompt 构建（从旧 BaseAgent / AgentRunner 提取）

- build_system_prompt: 记忆召回 + 时间上下文 + 仓库列表 + 可选自定义 prompt
- build_memory_context / build_time_context / build_repo_list_text: 各片段
"""
import logging
from typing import List, Optional

from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)


def build_system_prompt(messages: List[dict], custom_prompt: Optional[str] = None) -> str:
    """构建聊天 system prompt，注入相关记忆。"""
    user_query = last_user_message(messages)
    memory_context = build_memory_context(user_query, top_k=3)
    time_context = build_time_context()
    repo_list_text = build_repo_list_text()

    system_prompt = render_prompt(
        "agent", "system_prompt.md",
        time_context=time_context,
        repo_list_text=repo_list_text,
        memory_context=memory_context,
    )
    if custom_prompt:
        system_prompt = f"{custom_prompt}\n\n{system_prompt}"
    return system_prompt


def last_user_message(messages: List[dict]) -> str:
    """获取最后一条用户消息（截断）。"""
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "")[:200]
    return ""


def build_memory_context(query: str, top_k: int = 3) -> str:
    """从知识库召回相关记忆，返回格式化文本。"""
    if not query.strip():
        return ""
    try:
        from app.services.memory_service import MemoryService
        memories = MemoryService().recall(query=query, top_k=top_k)
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


def build_time_context() -> str:
    """返回当前 UTC 时间上下文。"""
    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    return (
        f"\n\n## 当前时间\n当前 UTC 时间：{now_utc.strftime('%Y-%m-%d %H:%M:%S')}。\n"
        f"用户问题中的时间范围（如'最近 N 天'）请以这个日期为基准计算。\n"
        f"搜索时优先使用工具的 days_back 参数指定时间范围，而不是依赖默认值。"
    )


def build_repo_list_text() -> str:
    """返回已配置仓库列表文本。"""
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