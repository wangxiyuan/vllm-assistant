"""
Agent 执行引擎（OpenAI Agents SDK 包装）

只做转发，不包含 agent 循环逻辑。所有循环/工具/流式由 agent_sdk 承担。
- chat(): 流式对话，事件协议与旧实现完全一致
  （thinking / tool_call / tool_result / token / done / error）
"""
import logging
from typing import AsyncIterator, List, Optional

from app.services.agent_sdk.chat import chat_stream as _sdk_chat_stream

logger = logging.getLogger(__name__)


class AgentRunner:
    """Agent 执行引擎——薄封装，转发到 agent_sdk.chat.chat_stream"""

    def __init__(self):
        self._closed = False

    async def close(self):
        self._closed = True

    async def chat(
        self,
        messages: List[dict],
        tools: Optional[List[str]] = None,
        stream: bool = True,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """streaming 对话。返回事件流（与旧实现事件协议一致）。

        Args:
            messages: 对话消息列表
            tools: 可用工具名称列表，None 使用全部，[] 不使用工具
            stream: 是否 stream（SDK 端目前是逐轮输出，stream=False 忽略）
            system_prompt: 可选的 system prompt 覆盖
            session_id: 会话 ID（用于 auto-remember）

        Yields:
            {"type": "thinking|tool_call|tool_result|token|done|error", "data": ..., "round": ...}
        """
        async for event in _sdk_chat_stream(
            messages=messages,
            tools=tools,
            system_prompt=system_prompt,
            session_id=session_id,
        ):
            yield event