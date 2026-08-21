"""
OpenAI Agents SDK — 归一化 Agent 引擎

核心抽象：一次 agent 执行 = 若干 AgentStage 顺序执行（聊天=单阶段，报告=多阶段）。
两端（chat.py / report.py）只声明 AgentStage 并消费事件/结果，不重复工具适配、
max_turns 强制、模型/温度控制等逻辑。
"""
import json
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
        model_settings=ModelSettings(
            temperature=stage.temperature,
            preserve_raw_usage=True,
        ),
    )


def _run_config() -> RunConfig:
    return RunConfig(model=build_chat_model())


async def run_stage_nonstream(stage: AgentStage, ctx: ToolRunContext, input) -> str:
    """非流式跑单个阶段，返回最终输出文本。"""
    res = await run_stage_with_meta(stage, ctx, input)
    return res["final_output"]


async def run_stage_with_meta(stage: AgentStage, ctx: ToolRunContext, input) -> dict:
    """非流式跑单个阶段，返回含痕迹元信息的完整结果。

    之所以非流式：本项目的 OpenAI 兼容端口仅在非流式响应中返回 token 用量，
    流式响应（stream=True）每 chunk 的 usage 为 None，无法拿到真实 Token 数。
    返回 dict：final_output / tool_calls[{name, arguments, call_id, output, status}] / usage / turns。

    max_turns 耗尽时 SDK 会抛 MaxTurnsExceeded；通过 error_handlers 捕获并复用已生成的
    raw_responses，使 final_output / usage / 工具调用仍可回溯，而非整个阶段失败。
    """
    _ensure_tracing_disabled()
    agent = create_agent(stage, ctx)

    def _max_turns_handler(hin):
        # 取最近一条文本消息作为最终输出，保证在 max_turns 内已生成的内容不丢失
        text = _last_text_from_run_data(hin.run_data)
        return {"final_output": text or "（已达最大轮次，未生成完整结果）", "include_in_history": True}

    result = await Runner.run(
        agent,
        input=input,
        max_turns=stage.max_turns,
        run_config=_run_config(),
        error_handlers={"max_turns": _max_turns_handler},
    )
    tool_calls: List[dict] = []
    for resp in getattr(result, "raw_responses", None) or []:
        for item in getattr(resp, "output", None) or []:
            if getattr(item, "type", None) == "function_call":
                tool_calls.append({
                    "name": getattr(item, "name", "") or "",
                    "arguments": getattr(item, "arguments", "") or "",
                    "call_id": getattr(item, "call_id", "") or "",
                    "output": "",
                })
    # 从 new_items 提取工具输出（按 call_id 配对）
    outs = {}
    for it in getattr(result, "new_items", None) or []:
        if getattr(it, "type", None) == "tool_call_output_item":
            cid = _raw_item_call_id(it)
            if cid and hasattr(it, "output"):
                outs[cid] = _raw_attr(getattr(it, "raw_item", None), "output") or getattr(it, "output", "") or ""
    for tc in tool_calls:
        if tc["call_id"] in outs:
            tc["output"] = outs[tc["call_id"]]
        tc["status"] = _tool_status(outs.get(tc.get("call_id", ""), ""))
    return {
        "final_output": result.final_output or "",
        "tool_calls": tool_calls,
        "usage": _agg_usage(result),
        "turns": len(tool_calls),
    }


def _raw_item_call_id(it) -> str:
    raw = getattr(it, "raw_item", None)
    if isinstance(raw, dict):
        return raw.get("call_id", "") or ""
    return getattr(raw, "call_id", "") or ""


def _tool_status(output: str) -> str:
    """根据工具输出 JSON 判断执行状态：工具统一以 {"error": ...} 表示失败。"""
    if not output:
        return "unknown"
    try:
        obj = json.loads(output)
    except (TypeError, ValueError):
        return "success"
    if isinstance(obj, dict) and obj.get("error"):
        return "error"
    return "success"


def _last_text_from_run_data(run_data) -> str:
    """从 max_turns 的 RunErrorData 中提取最后一条模型文本消息。"""
    try:
        items = getattr(run_data, "new_items", None) or []
        # 取最后一个 message_output_item 的文本
        for it in reversed(items):
            if getattr(it, "type", None) == "message_output_item":
                try:
                    from agents.items import ItemHelpers
                    return ItemHelpers.text_message_output(it) or ""
                except Exception:
                    pass
        # 回退：遍历 raw_responses 输出里的文本
        for resp in reversed(getattr(run_data, "raw_responses", None) or []):
            parts = []
            for item in getattr(resp, "output", None) or []:
                if getattr(item, "type", None) == "message":
                    ints = getattr(item, "content", None) or []
                    if isinstance(ints, list):
                        for c in ints:
                            t = getattr(c, "text", None)
                            if t:
                                parts.append(t)
            if parts:
                return "".join(parts)
    except Exception:
        logger.debug("failed to extract last text from run_data", exc_info=True)
    return ""


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
                    yield {"kind": "tool_call", "name": name, "arguments": arguments, "call_id": cid}
                elif itype == "tool_call_output_item":
                    output = getattr(item, "output", None) or ""
                    cid = _raw_attr(getattr(item, "raw_item", None), "call_id") or ""
                    yield {"kind": "tool_output", "name": call_names.get(cid, ""), "output": output, "call_id": cid}
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


def _glue_value(obj, *keys, _default=0):
    """从 object 或 dict 中按多个候选键取第一个非空值（用法：_glue_value(u, 'input_tokens', 'prompt_tokens')）。"""
    for k in keys:
        if isinstance(obj, dict):
            v = obj.get(k)
        else:
            v = getattr(obj, k, None)
        if v:
            return v
    return _default


def _agg_usage(result) -> dict:
    """汇总一次 run 的 token 用量（输入/输出 token）。

    优先读 raw_usage（preserve_raw_usage=True 时由 ModelResponse 保留的原始 usage dict，
    含 prompt_tokens/completion_tokens），该值在部分兼容端口未被 SDK 归一化到 usage 上时为 0。
    退而读 usage（object/dict，fields input_tokens/output_tokens 或 prompt/completion_tokens）。
    """
    total_in = 0
    total_out = 0
    raw_responses = getattr(result, "raw_responses", None) or []
    for resp in raw_responses:
        raw_usage = getattr(resp, "raw_usage", None)
        usage = raw_usage or getattr(resp, "usage", None) or getattr(resp, "response_usage", None)
        if usage is None:
            continue
        if isinstance(usage, dict) and not usage:
            continue
        if raw_usage is not None:
            total_in += _glue_value(raw_usage, "prompt_tokens", "input_tokens")
            total_out += _glue_value(raw_usage, "completion_tokens", "output_tokens")
        else:
            total_in += _glue_value(usage, "prompt_tokens", "input_tokens")
            total_out += _glue_value(usage, "completion_tokens", "output_tokens")
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