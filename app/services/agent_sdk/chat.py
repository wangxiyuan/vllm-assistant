"""
OpenAI Agents SDK — 聊天流式编排

把 SDK 的流事件映射回项目原有 SSE 协议：
  thinking / tool_call / tool_result / token / done / error

流式语义（与旧实现一致，逐轮整段）：
  - 每轮模型输出中：若该轮发生工具调用 → 该轮文本作为 thinking
  - 若该轮未发生工具调用 → 该轮文本作为最终回答 token
  - 一轮完整消息产出后，round +1
"""
import asyncio
import json
import logging
from typing import AsyncIterator, List, Optional

from app.config import Config
from app.services.agent_sdk.core import AgentStage, ToolRunContext, run_stage_stream
from app.services.llm import (
    EVENT_DONE, EVENT_ERROR, EVENT_THINKING, EVENT_TOKEN, EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
)

logger = logging.getLogger(__name__)


class ChatEventBuilder:
    """把每个模型"轮"的缓冲串成 SSE 事件，保持与旧实现的 1:1 语义。

    产出的事件进入 self.pending，由外层循环逐一 yield。
    """

    def __init__(self):
        self.round = 1
        self.pending: List[dict] = []
        self._turn_text: List[str] = []
        self._turn_has_tools = False
        self._turn_flushed = False

    def add_text_delta(self, delta: str):
        self._turn_text.append(delta)

    def mark_tool(self):
        self._turn_has_tools = True

    def flush_as_thinking(self):
        """工具调用前冲刷：该轮文本 → thinking（不会作为最终答案）。"""
        if self._turn_flushed:
            return
        self._turn_flushed = True
        text = "".join(self._turn_text)
        if text:
            self._pending(EVENT_THINKING, text)
        self._turn_text = []

    def flush_turn(self, force_token: bool = False):
        """本轮结束：有工具→thinking，无工具→token（最终回答）。"""
        if self._turn_flushed:
            return
        self._turn_flushed = True
        text = "".join(self._turn_text)
        if text:
            self._pending(EVENT_TOKEN if (force_token and not self._turn_has_tools) else EVENT_THINKING, text)
        self._turn_text = []
        self._turn_has_tools = False

    def begin_new_turn(self):
        self._turn_flushed = False
        self._turn_has_tools = False
        self._turn_text = []
        self.round += 1

    def emit(self, etype: str, data):
        self._pending(etype, data)

    def _pending(self, etype: str, data):
        self.pending.append({"type": etype, "data": data, "round": self.round})


async def chat_stream(
    messages: List[dict],
    tools: Optional[List[str]] = None,
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    max_turns: Optional[int] = None,
    temperature: float = 0.7,
) -> AsyncIterator[dict]:
    """聊天流式生成器，yield SSE 事件 dict。

    事件（相对旧协议为**增量**，旧字段不变）：
      - {'type':'delta','data':str,'kind':'thinking'|'answer','round'}  新增：实时文本分片
      - {'type':'thinking', 'data':str, 'round'}   工具轮文本定稿（thinking 块）
      - {'type':'token','data':str,'round'}        最终回答（完整，供持久化）
      - {'type':'tool_call'|'tool_result', ...}    不变
      - {'type':'done','data':{'usage':..,'duration_s':..},'round'}
    """
    if system_prompt is None:
        from app.services.agent_prompt import build_system_prompt
        system_prompt = build_system_prompt(messages)

    stage = AgentStage(
        name="chat",
        instructions=system_prompt,
        tool_names=tools,
        max_turns=max_turns or Config.AGENT_MAX_TURNS,
        temperature=temperature,
    )
    ctx = ToolRunContext()

    start_ts = _now()
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    final_text = ""
    # 区分实时分片所属区域：见到过工具调用且已过工具轮 → answer，否则 thinking
    saw_any_tool = False
    in_answer = False

    builder = ChatEventBuilder()

    def drain():
        while builder.pending:
            yield builder.pending.pop(0)

    def emit(etype: str, data):
        builder.emit(etype, data)

    try:
        async for ev in run_stage_stream(stage, ctx, input=_to_sdk_input(messages)):
            kind = ev.get("kind")
            if kind == "text_delta":
                # 实时分片：工具调用前的轮 → thinking；之后 → answer
                k = "answer" if in_answer else "thinking"
                emit("delta", {"data": ev["delta"], "kind": k})
                builder.add_text_delta(ev["delta"])
            elif kind == "tool_call":
                builder.mark_tool()
                builder.flush_as_thinking()
                try:
                    args = json.loads(ev["arguments"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                emit(EVENT_TOOL_CALL, {"name": ev["name"], "args": args})
                saw_any_tool = True
            elif kind == "tool_output":
                result = _parse_tool_result(ev.get("output", ""))
                payload = {"name": ev.get("name", ""), "result": result}
                emit(EVENT_TOOL_RESULT, payload)
                # 工具执行完成后，后续文本属于最终回答区
                in_answer = True
            elif kind == "message_end":
                # 实时分片已由 delta 事件流式发出；此处仅推进轮次，
                # 不再重复发 thinking/token（thinking 由 tool_call 前的 flush 提交）
                builder.begin_new_turn()
                # 有工具调用的轮结束后，后续文本属于最终回答区
                if saw_any_tool:
                    in_answer = True
            elif kind in ("stage_final", "stage_done"):
                if ev.get("text"):
                    final_text = final_text or ev["text"]
                u = ev.get("usage")
                if u:
                    usage = {k: usage.get(k, 0) + (u.get(k) or 0) for k in usage}
            for e in drain():
                yield e

        # 流结束：补齐最终回答 token（供持久化，完整文本）
        if final_text and not _token_emitted(builder):
            emit(EVENT_TOKEN, final_text)
            builder._turn_text = []
        elif not _token_emitted(builder):
            pending = "".join(builder._turn_text)
            if pending:
                final_text = pending
                emit(EVENT_TOKEN, pending)
                builder._turn_text = []
        for e in drain():
            yield e

        if final_text:
            _auto_remember(messages, final_text, session_id)

    except asyncio.CancelledError:
        logger.info("agent chat cancelled (session=%s)", session_id)
        raise
    except Exception as e:
        logger.exception("agent chat failed")
        emit(EVENT_ERROR, str(e))
        for e in drain():
            yield e
    finally:
        # 注意：finally 内不得 yield（aclose() 时 async generator 会抛 GeneratorExit >= Critical）
        pass

    # 聚合用量 + 耗时，发出最终的 done（在 finally 之外）
    duration_s = round(_now() - start_ts, 1)
    _fill_usage_estimate(usage, final_text)
    emit(EVENT_DONE, {"usage": usage, "duration_s": duration_s})
    for e in drain():
        yield e


def _fill_usage_estimate(usage: dict, final_text: str) -> None:
    """provider 未返回 usage 时，用最终答案长度估算输出 token。"""
    if usage.get("output_tokens", 0) == 0 and final_text:
        # 中文约 1 token/字，英文约 0.75 token/词：取 1 字≈0.75 token 的折中
        usage["output_tokens"] = max(int(len(final_text) * 0.75), 1)
        usage["total_tokens"] = usage.get("input_tokens", 0) + usage["output_tokens"]


# ======================================================================
# 内部工具
# ======================================================================


def _now() -> float:
    import time
    return time.time()


def _to_sdk_input(messages: List[dict]):
    """把 [{role, content}] 转为 SDK 输入列表。"""
    out = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role == "user" and content:
            out.append({"role": "user", "content": content})
        elif role == "assistant" and content:
            out.append({"role": "assistant", "content": content})
    return out


def _token_emitted(builder: "ChatEventBuilder") -> bool:
    """是否已经发出过最终回答 token。"""
    return any(e.get("type") == EVENT_TOKEN for e in builder.pending)


def _parse_tool_result(output: str) -> dict:
    if not output:
        return {}
    try:
        obj = json.loads(output)
        return obj if isinstance(obj, dict) else {"result": obj}
    except (json.JSONDecodeError, TypeError):
        return {"result": output[:10000]}


def _last_user_message(messages: List[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return (m.get("content") or "")[:200]
    return ""


def _auto_remember(messages: List[dict], response_content: str, session_id: Optional[str] = None):
    if not response_content or len(response_content) < 100:
        return
    user_msg = _last_user_message(messages)
    if not user_msg:
        return
    if len(response_content) > 200 and not any(
        kw in response_content[:50] for kw in ["好的", "明白", "可以", "没问题", "抱歉"]
    ):
        import hashlib
        source_ref = None
        if session_id:
            source_ref = f"conv/{session_id}/{hashlib.md5(user_msg.encode()).hexdigest()[:12]}"
        from app.services.memory_service import MemoryService
        MemoryService().remember(
            content=f"## 用户问题\n{user_msg}\n\n## AI 回答\n{response_content}",
            source_type="conversation",
            tags=["auto", "conversation"],
            source_ref=source_ref,
        )