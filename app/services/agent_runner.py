"""
Agent 执行引擎

只做流程控制，不做业务逻辑。
- chat(): streaming 对话，内部自动循环处理 tool_calls
- run_task(): 异步任务执行

流程：
1. 从 MemoryService 检索相关记忆，注入 system prompt
2. 调 LLMClient streaming chat API
3. 流式返回 token 事件
4. 遇到 tool_calls -> 查 tools/registry 获取 handler -> 执行
5. 工具结果返回给模型继续推理
6. 对话结束后自动 remember() 新知识
"""
import asyncio
import json
import logging
import re
import uuid
from typing import AsyncIterator, List, Dict, Optional, Any

from app.config import Config
from app.services.base_agent import BaseAgent
from app.services.llm import LLMClient, EVENT_TOKEN, EVENT_THINKING, EVENT_TOOL_CALL, EVENT_TOOL_RESULT, EVENT_DONE, EVENT_ERROR
from app.services.tools import registry as tool_registry
from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)


class AgentRunner(BaseAgent):
    """Agent 执行引擎——只做流程控制，不做业务逻辑"""

    # 还剩多少轮时提醒模型收尾
    WRAP_UP_REMAINING_ROUNDS = 5

    def __init__(self):
        super().__init__()

    async def chat(
        self,
        messages: List[dict],
        tools: Optional[List[str]] = None,
        stream: bool = True,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """streaming 对话。返回事件流，每个事件是 dict。

        内部自动循环处理 tool_calls：
        1. 注入记忆到 system prompt
        2. 调 OpenAI streaming API
        3. 遇到 tool_calls -> 执行 -> 继续
        4. 直到模型返回纯文本为止

        Args:
            messages: 对话消息列表
            tools: 可用工具名称列表，None 使用全部，[] 不使用工具
            stream: 是否 stream（默认 True）
            system_prompt: 可选的 system prompt 覆盖

        Yields:
            {"type": "token", "data": "..."}
            {"type": "tool_call", "data": {"name": ..., "args": ...}}
            {"type": "tool_result", "data": {...}}
            {"type": "done", "data": null}
            {"type": "error", "data": "..."}
        """
        # 1. 构建 system prompt（注入记忆 + 自定义 prompt）
        system = self._build_system_prompt(messages, system_prompt)

        # 2. 构建完整消息列表
        full_messages = [{"role": "system", "content": system}]
        for m in messages:
            if m.get("role") != "system":
                full_messages.append(m)

        # 3. 获取 tool schemas
        if tools is not None:
            tool_schemas = tool_registry.get_tool_schemas(tools)
        else:
            tool_schemas = tool_registry.get_tool_schemas()

        # 4. Tool 循环
        logger.info(
            "Agent chat start: model=%s, tool_count=%d, history_len=%d",
            self.llm.model, len(tool_schemas), len(full_messages),
        )
        for round_num in range(self.MAX_TOOL_ROUNDS):
            logger.info("Agent round %d begin", round_num + 1)
            kwargs = {"messages": full_messages}
            if tool_schemas:
                kwargs["tools"] = tool_schemas

            try:
                if stream:
                    assistant_message, text_content = await self.llm.chat_stream(**kwargs)
                else:
                    assistant_message, text_content = await self.llm.chat_async(**kwargs)
            except Exception as e:
                logger.exception("AI chat failed after 10 attempts")
                yield {"type": EVENT_ERROR, "data": str(e)}
                return

            # 文本回落：模型可能不支持 function calling
            if not assistant_message.get("tool_calls") and text_content:
                parsed = self._try_parse_text_tool_call(text_content)
                if parsed:
                    assistant_message["tool_calls"] = parsed
                    logger.info(
                        "Parsed %d tool call(s) from text content (model may lack function calling support)",
                        len(parsed),
                    )

            if text_content:
                if assistant_message.get("tool_calls"):
                    prefix = "\n\n---\n\n" if round_num > 0 else ""
                    yield {"type": EVENT_THINKING, "data": prefix + text_content, "round": round_num + 1}
                else:
                    yield {"type": EVENT_TOKEN, "data": text_content}

            full_messages.append(assistant_message)

            if assistant_message.get("tool_calls"):
                for tc in assistant_message["tool_calls"]:
                    yield {
                        "type": EVENT_TOOL_CALL,
                        "data": {
                            "name": tc["function"]["name"],
                            "args": self.llm.safe_json_loads(tc["function"]["arguments"]),
                        },
                        "round": round_num + 1,
                    }

                for tc in assistant_message["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    tool_args = self.llm.safe_json_loads(tc["function"]["arguments"])

                    result = await self.execute_tool_cached(tool_name, tool_args)

                    yield {"type": EVENT_TOOL_RESULT, "data": {"name": tool_name, "result": result}, "round": round_num + 1}

                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                # 接近预算上限时收尾提醒
                remaining = self.MAX_TOOL_ROUNDS - (round_num + 1)
                if remaining == self.WRAP_UP_REMAINING_ROUNDS:
                    full_messages.append({
                        "role": "system",
                        "content": (
                            f"⚠️ 还剩 {remaining} 轮迭代预算。立即停止读取新代码，"
                            "基于已有信息给出最终回答；如果确实缺关键信息，"
                            "用 1 次精准 search_code + 1 次 read_local_code 拿到即可。"
                        ),
                    })
                    logger.warning("Agent wrap-up reminder injected (remaining=%d)", remaining)

                continue

            # 没有 tool_calls，对话结束
            if text_content:
                self._auto_remember(messages, text_content, session_id)

            yield {"type": EVENT_DONE, "data": None}
            return

        # 超过最大轮次——强制收尾
        logger.warning("Agent exceeded MAX_TOOL_ROUNDS=%d, forcing final answer", self.MAX_TOOL_ROUNDS)
        try:
            kwargs_final = {
                "messages": full_messages + [{
                    "role": "system",
                    "content": (
                        f"⚠️ 已用尽 {self.MAX_TOOL_ROUNDS} 轮工具调用预算。"
                        "现在不允许再调用工具，立即基于已收集的所有信息给出最终回答。"
                    ),
                }],
            }
            _, final_text = await self.llm.chat_stream(**kwargs_final)
            if final_text:
                yield {"type": EVENT_TOKEN, "data": final_text}
                self._auto_remember(messages, final_text, session_id)
        except Exception as e:
            logger.exception("Failed to force final answer after max rounds")
            yield {"type": EVENT_ERROR, "data": f"工具调用超限且收尾失败: {e}"}

        yield {"type": EVENT_DONE, "data": None}

    # ======================================================================
    # 内部方法
    # ======================================================================

    def _build_system_prompt(self, messages: List[dict], custom_prompt: Optional[str] = None) -> str:
        """构建 system prompt，注入相关记忆"""
        user_query = self._last_user_message(messages)
        memory_context = self._build_memory_context(user_query, top_k=3)
        time_context = self._build_time_context()
        repo_list_text = self._build_repo_list_text()

        system_prompt = render_prompt("agent", "system_prompt.md",
            time_context=time_context,
            repo_list_text=repo_list_text,
            memory_context=memory_context,
        )

        if custom_prompt:
            system_prompt = f"{custom_prompt}\n\n{system_prompt}"

        return system_prompt

    def _last_user_message(self, messages: List[dict]) -> str:
        """获取最后一条用户消息"""
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")[:200]
        return ""

    def _try_parse_text_tool_call(self, text: str) -> Optional[List[dict]]:
        """从模型输出文本中解析 tool call（用于不支持 function calling 的模型）。"""
        if not text:
            return None

        candidates: List[str] = []

        code_block_pattern = re.compile(
            r"```(?:json)?\s*\n?\s*(\{.*?\})\s*\n?\s*```",
            re.DOTALL,
        )
        for m in code_block_pattern.finditer(text):
            candidates.append(m.group(1))

        for raw_obj in self._iter_top_level_json(text):
            candidates.append(raw_obj)

        for raw in candidates:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            name = obj.get("name") or obj.get("function") or obj.get("tool")
            if not isinstance(name, str) or not name:
                continue

            if tool_registry.get_tool(name) is None:
                continue

            args = obj.get("arguments")
            if args is None:
                args = obj.get("args") or obj.get("parameters") or {}
            if isinstance(args, str):
                args = self.llm.safe_json_loads(args)
            if not isinstance(args, dict):
                args = {}

            return [{
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }]

        return None

    @staticmethod
    def _iter_top_level_json(text: str):
        i = 0
        n = len(text)
        while i < n:
            if text[i] != "{":
                i += 1
                continue
            depth = 0
            j = i
            in_str = False
            esc = False
            while j < n:
                c = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                j += 1
            if depth == 0 and j > i + 1:
                snippet = text[i:j]
                if re.search(r'"(?:name|function|tool)"\s*:', snippet):
                    yield snippet
            i = j if j > i else i + 1

    def _auto_remember(self, messages: List[dict], response_content: str, session_id: Optional[str] = None) -> None:
        if not response_content or len(response_content) < 100:
            return

        user_msg = self._last_user_message(messages)
        if not user_msg:
            return

        if len(response_content) > 200 and not any(
            kw in response_content[:50] for kw in ["好的", "明白", "可以", "没问题", "抱歉"]
        ):
            import hashlib
            source_ref = f"conv/{session_id}/{hashlib.md5(user_msg.encode()).hexdigest()[:12]}" if session_id else None
            self.memory_service.remember(
                content=f"## 用户问题\n{user_msg}\n\n## AI 回答\n{response_content}",
                source_type="conversation",
                tags=["auto", "conversation"],
                source_ref=source_ref,
            )