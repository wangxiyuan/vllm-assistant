"""
OpenAI Agents SDK — 洞察报告三阶段流水线

阶段1 搜索（search_issues / search_arxiv / search_web / get_github_releases / search_by_tags）
阶段2 深入（get_issue_detail / get_pr_diff / search_code / read_local_code）
阶段3 报告（无工具，基于阶段1+2 产出生成 Markdown）

三阶段共用同一个 ToolRunContext（工具结果跨阶段去重）。
"""
import asyncio
import json
import logging
from time import time
from typing import List, Optional

from app.config import Config
from app.services.agent_sdk.core import AgentStage, ToolRunContext, run_stage_with_meta
from app.services.agent_sdk.model import build_chat_model
from app.services.report_progress import (
    add_tool, clear_report_progress, init_report_progress, complete_report, update_stage,
)

logger = logging.getLogger(__name__)

SEARCH_TOOLS = [
    "search_issues",
    "search_arxiv",
    "search_web",
    "get_github_releases",
    "search_by_tags",
    "extract_web_content",
]

DETAIL_TOOLS = [
    "get_issue_detail",
    "get_pr_diff",
    "search_code",
    "read_local_code",
    "search_by_tags",
]

# ======================================================================
# 阶段 prompt 构建
# ======================================================================


def _build_search_instructions(
    task_title: str, task_description: str,
    effective_sources: List[str], github_repos: List[str],
) -> str:
    parts = [
        "你是 vLLM 项目深度调研助手。当前进入【搜索调研】阶段。",
        f"本次调研主题：{task_title}",
        f"主题说明/背景：{task_description}",
    ]
    repos_str = ", ".join(github_repos) if github_repos else "无"
    parts.append(f"调研仓库：{repos_str}")
    parts.append(
        "请紧扣主题进行搜索，不要泛泛罗列仓库里所有 issue/PR。"
        "先从主题提取 3-5 个核心概念/关键词（如主题是'Q3 roadmap'，则搜 roadmap、milestone、planning、"
        "2025-Q3、roadmap issue 等），再据此精准搜索最相关的内容。"
        "不要编造不存在的内容，搜不到主题相关条目时如实说明。"
    )
    parts.append("可以并行调用多个 search_issues，用不同关键词避免重复。")
    if "academic" in effective_sources:
        parts.append(
            "同时调用 search_arxiv 搜索与主题相关的论文。**注意：arXiv 搜索必须用英文关键词。**"
            "如果主题包含中文，请先翻译成英文核心关键词再搜索。"
        )
    if "news" in effective_sources:
        parts.append(
            "同时调用 search_web 搜索与主题相关的行业新闻，优先英文关键词。"
            "**每引用一条新闻，必须提供 search_web 返回的真实来源 URL；没有 URL 的新闻不要写。**"
            "如有感兴趣的文章可调用 extract_web_content 提取正文。"
        )
    if "slack" in effective_sources:
        parts.append(
            "调用 search_by_tags 搜索 Slack 社群讨论，指定 tags 参数为 `slack` 获取相关 Slack 内容。"
        )
    parts.append(
        "搜索完成后，整理一份简要搜索结果小结，说明搜到了哪些与主题强相关或弱相关的内容。"
        "不要在这一阶段写最终报告。"
    )
    return "\n".join(parts)


def _build_detail_instructions(
    task_title: str, task_description: str, extra_prompt: str,
) -> str:
    parts = [
        "你是 vLLM 项目深度调研助手。当前进入【深入研读】阶段。",
        f"本次调研主题：{task_title}",
        f"主题说明/背景：{task_description}",
    ]
    if extra_prompt:
        parts.append(f"用户补充信息：{extra_prompt}")
    parts.append(
        "请从前一阶段搜索结果中，选取与主题最相关的条目深入研读（正文与评论），调用 get_issue_detail。"
        "优先选择能揭示主题全貌的关键内容，如 roadmap/milestone 讨论、RFC、规划类 issue、关键 PR。"
        "可以并行调用多个 get_issue_detail。"
    )
    parts.append(
        "对理解主题至关重要的 PR，可调用 get_pr_diff 查看代码变更要点。"
        "涉及代码功能是否存在时，用 search_code 搜索本地缓存代码验证，搜到后调 read_local_code 读关键文件确认。"
    )
    parts.append(
        "深入研读完成后，整理一份小结：主题的全貌、关键里程碑/条目、存在的分歧或待定事项。"
        "不要写最终报告。"
    )
    return "\n".join(parts)


# ======================================================================
# 执行入口
# ======================================================================


def _report_system_prompt(
    task_title: str, task_description: str, effective_sources: List[str],
    extra_prompt: str, github_repos: List[str], source_config: dict,
    memory_context: str, is_daily: bool,
) -> str:
    """构建报告阶段 system prompt（复用旧模板逻辑）。"""
    from app.services.prompt_utils import render_prompt

    source_descriptions = []
    for s in effective_sources:
        cfg = source_config.get(s, {})
        name = cfg.get("display_name", s)
        if cfg.get("type") == "github":
            repos = ", ".join(cfg.get("repos", []))
            source_descriptions.append(f"- {name}（GitHub 仓库: {repos}）")
        elif s == "academic":
            source_descriptions.append(f"- {name}（用户提供的论文信息，见下方补充）")
        elif s == "news":
            source_descriptions.append(f"- {name}（基于你的已有知识）")
        elif s == "slack":
            source_descriptions.append(f"- {name}（通过 search_memory 搜索 tags=slack 获取）")

    sources_text = "\n".join(source_descriptions) if source_descriptions else "无"
    repos_text = ", ".join(github_repos) if github_repos else "无"
    extra_section = f"\n\n## 用户补充信息\n{extra_prompt}" if extra_prompt else ""

    if is_daily:
        from app.services.prompt_utils import render_prompt
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return render_prompt("daily_report", "system_prompt.md",
            task_title=task_title, task_description=task_description,
            sources_text=sources_text, repos_text=repos_text,
            memory_context=memory_context, report_template=render_prompt("daily_report", "template.md", today=today),
        )

    # 自定义报告：主题驱动，不套固定社区扫描模板
    return (
        "你是 vLLM 项目深度调研报告撰写专家。请围绕下面的主题，基于已调研信息，生成一份有洞察的分析报告。\n\n"
        f"## 报告主题\n{task_title}\n\n"
        f"## 主题说明/背景\n{task_description or '（用户未提供更多说明）'}{extra_section}\n"
        "（实际报告正文不把这些标题原样输出，而是据此确定内容方向。）\n\n"
        f"## 可依据的调研来源\n{sources_text}\n\n"
        f"## 本地代码仓库\n{repos_text}\n"
        f"{memory_context}\n\n"
        "## 你掌握的调研材料\n"
        "搜勘与深入阶段所得的搜索结果小结、关键 issue/PR 的正文与评论、论文、新闻、仓库代码等，"
        "下文『搜索阶段结果』与『深入阶段结果』会完整给出。\n\n"
        "## 撰写要求\n"
        "1. 使用中文，直接输出 Markdown，不要包裹在代码块中。\n"
        "2. **报告的结构与逻辑必须由主题主导，而不是套固定的社区扫描模板。**\n"
        "3. 动笔前先想清楚：这个主题要回答什么问题、面向谁、期望的产出形态（解析、规划梳理、"
        "优劣势对比、决策建议等），据此设计最贴切的章节结构。\n"
        "4. 例如主题是『Q3 roadmap 解析』，报告就应围绕 roadmap 展开：Q3 的目标与优先事项、"
        "关键里程碑及其对应 issue/PR、当前进展（已合并/进行中/计划）、风险与依赖、对社区的启示。\n"
        "5. 除摘要外不强制固定章节；请设计能最好诠释该主题的结构。\n"
        "6. 引用 issue/PR 时带编号与链接；没有直接证据的观点明确标注为推断；不编造版本号、新闻、论文、会议或演讲。\n"
        "7. 内容要有实质价值，聚焦主题，不泛泛罗列无关的 repo 动态。\n"
    )


def _persist_stage_trace(
    report_id: Optional[int],
    stage_name: str,
    stage_index: int,
    system_prompt: str,
    user_input: str,
    final_output: str,
    tool_calls: List[dict],
    turns: int,
    usage: dict,
    temperature: Optional[float],
    max_turns: Optional[int],
    duration_ms: int,
    fallback: bool = False,
) -> None:
    """将单个阶段的生成痕迹持久化到 intelligence_report_traces。

    使用独立 SessionLocal（后台线程里外层 db 可能已关闭）。失败仅告警，不影响报告流程。
    """
    if report_id is None:
        return
    try:
        from app.database import SessionLocal
        from app.models import IntelligenceReportTrace
        from datetime import datetime, timezone

        db = SessionLocal()
        try:
            rec = IntelligenceReportTrace(
                report_id=report_id,
                stage=stage_name,
                stage_index=stage_index,
                system_prompt=system_prompt,
                user_input=user_input,
                final_output=final_output,
                tool_calls=json.dumps(tool_calls, ensure_ascii=False),
                turns=turns,
                usage=json.dumps(usage, ensure_ascii=False),
                temperature=temperature,
                max_turns=max_turns,
                model=Config.OPENAI_MODEL,
                duration_ms=duration_ms,
                fallback=fallback,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(rec)
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("failed to persist report trace (report_id=%s stage=%s)", report_id, stage_name)


async def _run_stage_collect(
    stage: AgentStage, ctx: ToolRunContext, input, report_id: Optional[int], stage_index: int,
) -> str:
    """执行单个阶段并收集进度 + 痕迹，返回最终文本。

    使用非流式执行（run_stage_with_meta），以获得真实 token 用量与结构化的工具调用明细。
    """
    if report_id is not None:
        update_stage(report_id, stage.name, stage_index)
    start = time()
    meta = await run_stage_with_meta(stage, ctx, input=input)
    tool_calls = meta["tool_calls"]
    if report_id is not None:
        for tc in tool_calls:
            add_tool(report_id, tc.get("name", ""))
    _truncate_tool_outputs(tool_calls, limit=2000)
    _persist_stage_trace(
        report_id=report_id,
        stage_name=stage.name,
        stage_index=stage_index,
        system_prompt=stage.instructions,
        user_input=input,
        final_output=meta["final_output"],
        tool_calls=tool_calls,
        turns=meta["turns"],
        usage=meta["usage"],
        temperature=getattr(stage, "temperature", None),
        max_turns=getattr(stage, "max_turns", None),
        duration_ms=int((time() - start) * 1000),
    )
    return meta["final_output"]


def _truncate_tool_outputs(tool_calls: List[dict], limit: int = 2000) -> None:
    for tc in tool_calls:
        out = tc.get("output") or ""
        if len(out) > limit:
            tc["output"] = out[:limit] + "…[截断]"


async def _generate_report_async(
    task_title: str, task_description: str,
    effective_sources: List[str], extra_prompt: str,
    github_repos: List[str], source_config: dict,
    memory_context: str, is_daily: bool,
    report_id: Optional[int] = None,
) -> str:
    """三阶段流水线（async 核心）。"""
    if report_id is not None:
        init_report_progress(report_id)
    try:
        ctx = ToolRunContext()

        # 搜索阶段：独立轮次预算（不再由仓库数决定，之前 "4 轮" 即仓库数过小所致）
        search_turns = Config.AGENT_SEARCH_TURNS
        detail_turns = max(Config.AGENT_MAX_TURNS - search_turns, 3)

        # 阶段1：搜索
        stage1 = AgentStage(
            name="search",
            instructions=_build_search_instructions(task_title, task_description, effective_sources, github_repos),
            tool_names=SEARCH_TOOLS,
            max_turns=search_turns,
            temperature=0.3,
        )
        search_out = await _run_stage_collect(stage1, ctx, _search_user_prompt(task_title, effective_sources), report_id, 0)
        logger.info("report stage 1 (search) done, len=%d", len(search_out))

        # 阶段2：深入
        stage2 = AgentStage(
            name="detail",
            instructions=_build_detail_instructions(task_title, task_description, extra_prompt),
            tool_names=DETAIL_TOOLS,
            max_turns=detail_turns,
            temperature=0.3,
        )
        detail_in = f"以下是搜索阶段的结果：\n\n{search_out}\n\n请继续深入调研。"
        detail_out = await _run_stage_collect(stage2, ctx, detail_in, report_id, 1)
        logger.info("report stage 2 (detail) done, len=%d", len(detail_out))

        # 阶段3：报告
        system = _report_system_prompt(
            task_title, task_description, effective_sources, extra_prompt,
            github_repos, source_config, memory_context, is_daily,
        )
        stage3 = AgentStage(
            name="report",
            instructions=system,
            tool_names=[],
            max_turns=1,
            temperature=0.5,
        )
        report_in = (
            f"请基于以下两阶段调研信息生成最终洞察报告。\n\n"
            f"### 搜索阶段结果\n{search_out}\n\n"
            f"### 深入阶段结果\n{detail_out}\n"
        )
        report_out = await _run_stage_collect(stage3, ctx, report_in, report_id, 2)
        if report_id is not None:
            complete_report(report_id)
        return report_out
    except Exception:
        if report_id is not None:
            clear_report_progress(report_id)
        raise


def _search_user_prompt(task_title: str, effective_sources: List[str]) -> str:
    sources_str = ", ".join(effective_sources) if effective_sources else "全部"
    return f"请开始搜索并初步调研「{task_title}」相关动态，来源范围：{sources_str}。"


async def _generate_report_fallback(
    task_title: str, task_description: str,
    effective_sources: List[str], extra_prompt: str,
    github_repos: List[str], source_config: dict,
    report_id: Optional[int] = None,
) -> str:
    """单次回退：先批量搜索，再让 AI 一次性生成报告。"""
    from app.services.intelligence_report import IntelligenceReportGenerator
    start = time()
    gen = IntelligenceReportGenerator()
    content = gen.single_shot_report_for_sdk(
        task_title=task_title, task_description=task_description,
        effective_sources=effective_sources, extra_prompt=extra_prompt,
        github_repos=github_repos, source_config=source_config,
    )
    _persist_stage_trace(
        report_id=report_id,
        stage_name="fallback",
        stage_index=0,
        system_prompt="",
        user_input=f"任务主题：{task_title}\n背景：{task_description}",
        final_output=content,
        tool_calls=[],
        turns=0,
        usage={},
        temperature=None,
        max_turns=None,
        duration_ms=int((time() - start) * 1000),
        fallback=True,
    )
    return content


def generate_report_sync(
    task_title: str,
    task_description: str,
    sources: List[str],
    excluded_sources: Optional[List[str]] = None,
    extra_prompt: str = "",
    is_daily: bool = False,
    db=None,
    report_id: Optional[int] = None,
    gen=None,
) -> dict:
    """同步入口（供 API 后台线程 / 调度器调用）。

    与旧 IntelligenceReportGenerator.generate_report 相同签名语义，
    返回 {"content": str, "sources": [..]}。report_id 用于上报生成进度。
    gen：可传入已配置好的 IntelligenceReportGenerator 实例
    （调度器会预设 _cached_source_config，必须复用，不能重建）。
    """
    from app.services.intelligence_report import IntelligenceReportGenerator

    if gen is None:
        gen = IntelligenceReportGenerator(db=db)
    source_config = gen._get_source_config(db)
    effective_sources = gen._resolve_sources(sources, excluded_sources, source_config)

    github_repos = []
    for s in effective_sources:
        cfg = source_config.get(s)
        if cfg and cfg.get("type") == "github":
            github_repos.extend(cfg.get("repos", []))

    memory_context = gen._build_memory_context(f"{task_title} {task_description}", top_k=5)
    try:
        content = asyncio.run(_generate_report_async(
            task_title=task_title, task_description=task_description,
            effective_sources=effective_sources, extra_prompt=extra_prompt,
            github_repos=github_repos, source_config=source_config,
            memory_context=memory_context, is_daily=is_daily,
            report_id=report_id,
        ))
        if not content:
            raise RuntimeError("report generation returned empty")
        return {"content": content, "sources": effective_sources}
    except Exception as e:
        err_str = str(e).lower()
        if any(kw in err_str for kw in ("tool", "function_call", "not support", "unrecognized")):
            logger.warning(f"agent report failed (tools unsupported), falling back: {e}")
            content = asyncio.run(_generate_report_fallback(
                task_title=task_title, task_description=task_description,
                effective_sources=effective_sources, extra_prompt=extra_prompt,
                github_repos=github_repos, source_config=source_config,
                report_id=report_id,
            ))
            return {"content": content, "sources": effective_sources}
        raise