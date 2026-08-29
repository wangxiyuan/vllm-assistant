"""
第二段 agent 复核（漏斗式分诊的第二段）

批量粗筛（ai_triage.run_triage 第一段）命中后，对命中候选起一个带工具的
复核 agent：查知识库、看 issue/PR 详情、翻本地代码，剔除误报、确认真命中。
复用 agent_sdk 的工具桥接（tools/registry）与 max_turns 兜底；LLM client
每次复核独立创建——agent_sdk.model 的全局单例 AsyncOpenAI 不能安全跨
asyncio.run 的事件循环复用，而 run_triage 运行在无事件循环的 worker 线程。
任何失败都返回 None，由调用方回退到粗筛结果：复核是增强，不是依赖。
"""
import asyncio
import json
import logging
from typing import Optional

from app.config import Config
from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)

# 复核 agent 可用的工具类别（tools/registry CATEGORY_TOOLS）
REVIEW_TOOL_CATEGORIES = ["knowledge", "github", "code"]


def review_matches(rule_name: str, rule_prompt: str, matched: list) -> Optional[dict]:
    """复核粗筛命中。

    Args:
        matched: 粗筛命中的候选列表，每项含 index（与粗筛 prompt 序号一致）和候选字段。

    Returns:
        {index: reason} 复核结论（只含保留条目）；失败/不可用时返回 None。
    """
    if not matched:
        return None
    try:
        return asyncio.run(_review_async(rule_name, rule_prompt, matched))
    except Exception:
        logger.exception("agent review failed, fallback to first-pass matches")
        return None


async def _review_async(rule_name: str, rule_prompt: str, matched: list) -> Optional[dict]:
    from agents import Agent, ModelSettings, RunConfig, Runner
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
    from openai import AsyncOpenAI
    import httpx

    from app.services.agent_sdk.core import ToolRunContext, _last_text_from_run_data
    from app.services.agent_sdk.model import disable_tracing
    from app.services.agent_sdk.tools import build_sdk_tools

    disable_tracing()
    instructions = render_prompt(
        "triage", "agent_review.md",
        rule_name=rule_name, rule_prompt=rule_prompt, items=matched,
    )

    timeout = httpx.Timeout(600.0, connect=15.0, read=600.0, write=30.0, pool=None)
    client = AsyncOpenAI(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
        timeout=timeout,
    )
    try:
        model = OpenAIChatCompletionsModel(
            model=Config.OPENAI_MODEL, openai_client=client,
        )
        agent = Agent(
            name="triage-reviewer",
            instructions=instructions,
            tools=build_sdk_tools(REVIEW_TOOL_CATEGORIES, ToolRunContext().cache),
            model=model,
            model_settings=ModelSettings(temperature=0.2, preserve_raw_usage=True),
        )

        def _max_turns_handler(hin):
            # 轮次耗尽时取最后一条模型文本，保证已生成的结论不丢
            text = _last_text_from_run_data(hin.run_data)
            return {"final_output": text or "", "include_in_history": True}

        result = await Runner.run(
            agent,
            input="请按系统指令复核上述条目，只输出 JSON。",
            max_turns=Config.AI_TRIAGE_AGENT_MAX_TURNS,
            run_config=RunConfig(model=model),
            error_handlers={"max_turns": _max_turns_handler},
        )
        content = result.final_output or ""
    finally:
        try:
            await client.close()
        except Exception:
            logger.debug("close review client failed", exc_info=True)

    return _parse_review(content, matched)


def _parse_review(content: str, matched: list) -> Optional[dict]:
    """解析复核输出， clamp 到输入候选范围内（防 agent 幻觉补条目）。"""
    if not content:
        logger.warning("agent review returned empty content")
        return None
    from app.services.llm import LLMClient

    data = LLMClient.safe_json(content, default=None)
    if not isinstance(data, dict) or "matches" not in data:
        logger.warning("agent review output not parseable: %s", (content or "")[:200])
        return None
    valid = {c["index"]: c for c in matched}
    out: dict = {}
    for m in data.get("matches") or []:
        if not isinstance(m, dict):
            continue
        try:
            idx = int(m.get("index"))
        except (TypeError, ValueError):
            continue
        if idx in valid:
            out[idx] = (m.get("reason") or "").strip()[:500] or (valid[idx].get("reason") or "")
    return out
