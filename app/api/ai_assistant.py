"""
AI Assistant API - AI辅助功能
提供Review意见生成、PR影响范围分析、Issue/PR 摘要等功能。

⚠️ 重要：本模块只调用 GitHub REST API 的**只读**接口和 OpenAI 兼容 API，
**绝不会**对 GitHub 做任何写操作（不会自动评论、自动修改 PR/Issue 状态）。
所有 AI 输出仅作为本地参考，需用户手动确认后再做任何外部操作。

AI 输出会缓存到本地 SQLite（ai_cache 表），刷新页面后仍可查看。
"""
import json
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import Config
from app.services.ai_assistant import AIAssistant
from app.services.ai_cache import ai_cache as cache_service
from app.services._shared import get_github_client as _get_github_client
from app.schemas import (
    AIReviewRequest,
    AIAnalyzeRequest,
    AISuggestLabelRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_api_key() -> None:
    if not Config.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")


@router.post("/generate-review")
def generate_review(request: AIReviewRequest):
    """基于 PR diff 生成结构化 review 意见（结果缓存到本地 ai_cache 表）

    用 def（非 async）让 FastAPI 在线程池执行，避免同步的 GitHub/OpenAI
    调用阻塞事件循环导致其他请求（如 PR 详情加载）卡住。
    """
    import time
    t0 = time.time()
    logger.info(f"[generate_review] START PR#{request.pr_number} include_diff={request.include_diff}")
    try:
        _require_api_key()

        # 先读缓存（回溯兼容：旧缓存为 dict，新缓存为字符串）
        cached = cache_service.get("pr", request.pr_number, "review")
        if cached:
            if isinstance(cached, dict):
                return _legacy_review_to_markdown(cached)
            return cached

        pr = _get_github_client().get_pull(request.pr_number, repo=request.repo)
        if not pr:
            raise HTTPException(status_code=404, detail="PR not found")

        diff = ""
        if request.include_diff:
            diff = _get_github_client().get_pull_diff(request.pr_number, repo=request.repo) or ""
        logger.info(f"[generate_review] fetched PR+diff PR#{request.pr_number} ({time.time()-t0:.1f}s, diff={len(diff)} chars)")

        ai = AIAssistant()
        result = ai.generate_review(
            pr_title=pr.get("title", ""),
            pr_diff=diff,
            pr_number=request.pr_number,
        )
        logger.info(f"[generate_review] DONE PR#{request.pr_number} ({time.time()-t0:.1f}s)")
        # 缓存结果
        cache_service.set("pr", request.pr_number, "review", result)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in generate_review")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/analyze-impact")
def analyze_impact(request: AIAnalyzeRequest):
    """分析 PR 影响范围"""
    try:
        _require_api_key()
        ai = AIAssistant()
        return ai.analyze_impact(request.changed_files)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in analyze-impact")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/suggest-labels")
def suggest_labels(request: AISuggestLabelRequest):
    """根据 issue 内容推荐标签和领域（DESIGN.md 135 行）"""
    try:
        _require_api_key()
        ai = AIAssistant()
        labels = ai.suggest_labels(request.issue_title, request.issue_body)
        return {"suggested_labels": labels}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in suggest_labels")
        raise HTTPException(status_code=500, detail="Internal server error")


class SummarizeRequest(BaseModel):
    """Issue/PR 摘要请求"""
    item_type: str  # 'issue' or 'pr'
    number: int
    title: str = ""
    body: str = ""


@router.post("/summarize")
def summarize(request: SummarizeRequest):
    """为 Issue/PR 生成简短摘要（仅本地展示，不做任何 GitHub 写操作；结果缓存到本地）

    用 def（非 async）避免同步 AI 调用阻塞事件循环。
    """
    if request.item_type not in ("issue", "pr"):
        raise HTTPException(status_code=400, detail="item_type must be 'issue' or 'pr'")
    try:
        _require_api_key()

        # 先读缓存（回溯兼容：旧缓存为 dict，新缓存为字符串）
        cached = cache_service.get(request.item_type, request.number, "summary")
        if cached:
            if isinstance(cached, dict):
                return _legacy_summary_to_markdown(cached)
            return cached

        ai = AIAssistant()
        result = ai.summarize(
            title=request.title,
            body=request.body,
            item_type=request.item_type,
        )
        cache_service.set(request.item_type, request.number, "summary", result)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in summarize")
        raise HTTPException(status_code=500, detail="Internal server error")


class CacheDeleteRequest(BaseModel):
    item_type: str
    number: int
    action: str  # 'summary' or 'review'


@router.post("/get-cache")
async def get_ai_cache(request: CacheDeleteRequest):
    """读取 AI 缓存（不触发 AI 调用，仅返回本地缓存结果）"""
    cached = cache_service.get(request.item_type, request.number, request.action)
    if cached is None:
        return {"empty": True}
    # 回溯兼容：旧缓存为 dict（结构化格式），转为 markdown 字符串
    if isinstance(cached, dict):
        if request.action == "review":
            cached = _legacy_review_to_markdown(cached)
        else:
            cached = _legacy_summary_to_markdown(cached)
    return cached


def _legacy_summary_to_markdown(d: dict) -> str:
    """将旧格式的 summarize dict 转为 markdown"""
    parts = []
    if d.get("core_problem"):
        parts.append(f"**核心问题**：{d['core_problem']}")
    if d.get("key_points"):
        parts.append("**关键要点**：")
        for p in d["key_points"]:
            parts.append(f"- {p}")
    if d.get("impact"):
        parts.append(f"**影响范围**：{d['impact']}")
    if d.get("risk"):
        parts.append(f"**注意事项**：{d['risk']}")
    return "\n\n".join(parts) if parts else str(d)


def _legacy_review_to_markdown(d: dict) -> str:
    """将旧格式的 review dict 转为 markdown"""
    parts = []
    if d.get("summary"):
        parts.append(f"### 总体评价\n{d['summary']}")
    sections = [
        ("代码质量", "code_quality"),
        ("性能", "performance"),
        ("测试", "tests"),
        ("文档", "docs"),
    ]
    for title, key in sections:
        items = d.get(key, [])
        if not items:
            continue
        lines = [f"### {title}"]
        for item in items:
            sev = item.get("severity", "")
            sev_tag = f"[{sev}] " if sev else ""
            t = item.get("title", "")
            desc = item.get("description", "")
            if t and desc:
                lines.append(f"- {sev_tag}**{t}**：{desc}")
            elif t:
                lines.append(f"- {sev_tag}**{t}**")
            else:
                lines.append(f"- {sev_tag}{desc}")
        parts.append("\n".join(lines))
    if d.get("error"):
        parts.append(f"**错误**：{d['error']}")
    return "\n\n".join(parts) if parts else str(d)


@router.post("/clear-cache")
async def clear_ai_cache(request: CacheDeleteRequest):
    """清除指定条目的 AI 缓存（用于"重新生成"场景）"""
    cache_service.clear(request.item_type, request.number, request.action)
    return {"ok": True}

class TranslateRequest(BaseModel):
    """翻译请求"""
    item_type: str  # 'issue' or 'pr'
    number: int  # issue/PR 编号，用于缓存
    text: str


@router.post("/translate")
def translate(request: TranslateRequest):
    """将 Issue/PR 描述翻译为中文（结果缓存到本地 ai_cache 表，action='translate'）

    用 def（非 async）避免同步 AI 调用阻塞事件循环。
    """
    if not request.text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        _require_api_key()
        # 先读缓存
        cached = cache_service.get(request.item_type, request.number, "translate")
        if cached and cached.get("translated"):
            return cached
        ai = AIAssistant()
        translated = ai.translate(request.text, request.item_type)
        result = {"translated": translated}
        # 缓存到 ai_cache 表
        cache_service.set(request.item_type, request.number, "translate", result)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error in translate")
        raise HTTPException(status_code=500, detail="Translation failed")
