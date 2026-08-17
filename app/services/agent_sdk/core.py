"""
OpenAI Agents SDK — 归一化 Agent 引擎

核心抽象：一次 agent 执行 = 若干 AgentStage 顺序执行（聊天=单阶段，报告=多阶段）。
两端（chat.py / report.py）只声明 AgentStage 并消费事件/结果，不重复工具适配、
max_turns 强制、模型/温度控制等逻辑。
"""
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional

from agents import Agent, RunConfig, Runner, ModelSettings

from app.config import Config
from app.services.agent_sdk.model import build_chat_model, disable_tracing
from app.services.agent_sdk.tools import build_sdk_tools

logger = logging.getLogger(__name__)

_tracing_disabled = False


def _ensure_tracing_disabled():
    global _tracing_disabled
    if not _tracing_disabled:
        disable_tracing()
        _tracing_disabled = True


@dataclass
class ToolRunContext:
    """一次 agent 执行的共享工具缓存（跨阶段去重）。"""
    cache: dict = field(default_factory=dict)


@dataclass
class AgentStage:
    """一个 agent 阶段：角色 prompt + 可用工具 + 轮次预算 + 温度。"""
    name: str
    instructions: str
    tool_names: Optional[List[str]] = None  # None=全部工具; [] = 无工具
    max_turns: int = Config.AGENT_MAX_TURNS
    temperature: float = 0.7


def create_agent(stage: AgentStage, ctx: ToolRunContext) -> Agent:
    """根据阶段规格构造 SDK Agent。

    stage.tool_names: None=全部工具; [] = 不使用工具; 其他=指定工具/类别列表。
    """
    tools = build_sdk_tools(stage.tool_names, ctx.cache)
    return Agent(
        name=stage.name,
        instructions=stage.instructions,
        tools=tools,
        model=build_chat_model(),
        model_settings=ModelSettings(temperature=stage.temperature),
    )


def _run_config() -> RunConfig:
    return RunConfig(model=build_chat_model())


async def run_stage_nonstream(stage: AgentStage, ctx: ToolRunContext, input) -> str:
    """非流式跑单个阶段，返回最终输出文本。"""
    _ensure_tracing_disabled()
    agent = create_agent(stage, ctx)
    result = await Runner.run(
        agent,
        input=input,
        max_turns=stage.max_turns,
        run_config=_run_config(),
    )
    return result.final_output or ""


async def run_stage_stream(stage: AgentStage, ctx: ToolRunContext, input) -> AsyncIterator[dict]:
    """流式跑单个阶段，yield 该阶段内的 openai-agents 流事件包装。

    事件类型（在 ``agents.stream_events`` 中定义）：
      - {'kind': 'text_delta', 'delta': str}
      - {'kind': 'tool_call', 'name': str, 'arguments': str}
      - {'kind': 'tool_output', 'name': str, 'output': str}
      - {'kind': 'message_end', 'text': str}   # 模型产出一条完整文本消息
    """
    _ensure_tracing_disabled()
    agent = create_agent(stage, ctx)
    result = Runner.run_streamed(
        agent,
        input=input,
        max_turns=stage.max_turns,
        run_config=_run_config(),
    )
    try:
        call_names: dict = {}
        async for event in result.stream_events():
            if event.type == "raw_response_event":
                data = getattr(event, "data", None)
                if data is not None and getattr(data, "type", None) == "response.output_text.delta":
                    ts = getattr(data, "delta", None)
                    if ts:
                        yield {"kind": "text_delta", "delta": ts}
            elif event.type == "run_item_stream_event":
                item = getattr(event, "item", None)
                itype = getattr(item, "type", None)
                if itype == "message_output_item":
                    text = _message_text(item)
                    yield {"kind": "message_end", "text": text}
                elif itype == "tool_call_item":
                    raw = getattr(item, "raw_item", None)
                    name = _raw_attr(raw, "name") or ""
                    arguments = _raw_attr(raw, "arguments") or ""
                    cid = _raw_attr(raw, "call_id") or ""
                    if cid:
                        call_names[cid] = name
                    yield {"kind": "tool_call", "name": name, "arguments": arguments}
                elif itype == "tool_call_output_item":
                    output = getattr(item, "output", None) or ""
                    cid = _raw_attr(getattr(item, "raw_item", None), "call_id") or ""
                    yield {"kind": "tool_output", "name": call_names.get(cid, ""), "output": output}
    except Exception as e:
        # max_turns 耗尽时 SDK 会抛 MaxTurnsExceeded，但 final_output 仍可用，视为正常结束
        from agents.exceptions import MaxTurnsExceeded
        if isinstance(e, MaxTurnsExceeded):
            logger.info("agent stage max_turns exceeded (stage=%s)", stage.name)
        else:
            logger.exception("run_stage_stream failed")
            raise
    finally:
        if hasattr(result, "cancel"):
            try:
                await result.cancel()
            except Exception:
                logger.debug("cancelled streaming run", exc_info=True)
    # 流结束后让调用方取 final_output 兜底 + token 用量
    last_final = getattr(result, "final_output", None)
    usage = _agg_usage(result)
    if last_final:
        yield {"kind": "stage_final", "text": last_final or "", "usage": usage}
    else:
        yield {"kind": "stage_done", "usage": usage}


def _raw_attr(src, name: str):
    if src is None:
        return None
    if isinstance(src, dict):
        return src.get(name)
    return getattr(src, name, None)


def _agg_usage(result) -> dict:
    """汇总一次 run 的 token 用量（输入/输出 token）。"""
    total_in = 0
    total_out = 0
    raw_responses = getattr(result, "raw_responses", None) or []
    for resp in raw_responses:
        usage = getattr(resp, "usage", None) or getattr(resp, "response_usage", None)
        if usage is None:
            continue
        ti = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0
        to = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0
        total_in += ti or 0
        total_out += to or 0
    return {"input_tokens": total_in, "output_tokens": total_out, "total_tokens": total_in + total_out}


def _message_text(item) -> str:
    from agents.items import ItemHelpers
    try:
        return ItemHelpers.text_message_output(item)
    except Exception:
        raw = getattr(item, "raw_item", None)
        if raw is not None:
            chunks = raw.get("content") if isinstance(raw, dict) else getattr(raw, "content", None)
            if isinstance(chunks, list):
                parts = []
                for c in chunks:
                    t = c.get("text") if isinstance(c, dict) else getattr(c, "text", None)
                    if t:
                        parts.append(t)
                return "".join(parts)
        return ""