"""
第二段 agent 复核（漏斗式分诊的第二段）

批量粗筛（ai_triage._run_group 第一段）命中后，对命中候选起一个带工具的
复核 agent：查知识库、看 issue/PR 详情、翻本地代码，剔除误报、确认真命中。
同一组规则联合复核：命中候选按候选去重（一条候选带"命中它的规则+理由"），
一次会话完成整组复核。
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


def review_group(rule_infos: list, matched_entries: list) -> Optional[dict]:
    """组内联合复核粗筛命中。

    Args:
        rule_infos: 本组规则信息列表（含 key/name/prompt）。
        matched_entries: 去重后的命中候选，每项含 index、候选字段和
            hits = {rule_key: 粗筛理由}。

    Returns:
        {rule_key: {index: reason}} 复核结论（只含各规则保留条目）；
        失败/不可用时返回 None。
    """
    if not matched_entries:
        return None
    try:
        return asyncio.run(_review_async(rule_infos, matched_entries))
    except Exception:
        logger.exception("agent review failed, fallback to first-pass matches")
        return None


async def _review_async(rule_infos: list, matched_entries: list) -> Optional[dict]:
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
        rules=rule_infos, items=matched_entries,
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
        ctx = ToolRunContext()
        agent = Agent(
            name="triage-reviewer",
            instructions=instructions,
            tools=build_sdk_tools(REVIEW_TOOL_CATEGORIES, ctx.cache),
            model=model,
            model_settings=ModelSettings(temperature=0.2, preserve_raw_usage=True),
        )

        def _max_turns_handler(hin):
            # 轮次耗尽时取最后一条模型文本，保证已生成的结论不丢
            text = _last_text_from_run_data(hin.run_data)
            return {"final_output": text or "", "include_in_history": True}

        run_config = RunConfig(model=model)
        expected_keys = ", ".join(ri["key"] for ri in rule_infos)
        parsed: Optional[dict] = None
        result_text = ""
        for attempt in range(3):
            if attempt == 0:
                message = "请按系统指令复核上述条目，只输出 JSON。"
            else:
                message = (
                    f"你上一次的回复不是要求的纯 JSON（你回答的是：{(result_text or '')[:200]}）。"
                    f"请重新输出：只输出一个 JSON 对象，key 为 {expected_keys}，"
                    f"不要任何解释、列表或 markdown。"
                )
            result = await Runner.run(
                agent,
                input=message,
                max_turns=Config.AI_TRIAGE_AGENT_MAX_TURNS,
                run_config=run_config,
                error_handlers={"max_turns": _max_turns_handler},
            )
            result_text = result.final_output or ""
            parsed = _parse_review(result_text, rule_infos, matched_entries)
            if parsed is not None:
                break
            logger.warning("agent review parse failed (attempt %d/3): %s",
                           attempt + 1, (result_text or "")[:200])
    finally:
        try:
            await client.close()
        except Exception:
            logger.debug("close review client failed", exc_info=True)

    return parsed


def _parse_review(content: str, rule_infos: list, matched_entries: list) -> Optional[dict]:
    """解析复核输出，clamp 到各规则输入候选范围内（防 agent 幻觉补条目）。"""
    if not content:
        logger.warning("agent review returned empty content")
        return None
    from app.services.llm import LLMClient

    data = LLMClient.safe_json(content, default=None)
    if not isinstance(data, dict):
        logger.warning("agent review output not parseable: %s", (content or "")[:200])
        return None

    # 每条候选只可能被"命中它的规则"复核，index 合法范围按 hits 限定
    valid_indexes: dict = {}
    for e in matched_entries:
        for rule_key in (e.get("hits") or {}):
            valid_indexes.setdefault(rule_key, set()).add(e["index"])

    out: dict = {}
    for ri in rule_infos:
        rule_key = ri["key"]
        verdict: dict = {}
        raw = data.get(rule_key)
        if isinstance(raw, dict):
            for m in raw.get("matches") or []:
                if not isinstance(m, dict):
                    continue
                try:
                    idx = int(m.get("index"))
                except (TypeError, ValueError):
                    continue
                if idx in valid_indexes.get(rule_key, set()):
                    verdict[idx] = (m.get("reason") or "").strip()[:500]
        out[rule_key] = verdict
    return out
