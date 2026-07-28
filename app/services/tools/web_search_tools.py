"""
Web 搜索工具

使用 Tavily 兼容协议搜索互联网上的行业新闻、技术文章等。
默认使用公益服务 https://tavily.claude-code-best.win（无需 API Key），
也可通过 TAVILY_API_URL 和 TAVILY_API_KEY 环境变量配置为官方 Tavily 或其他兼容服务。

Tavily 协议专为 AI Agent 设计——搜索返回结构化结果（title/url/content），
页面提取返回清洁文本，不需要 Agent 自己解析 HTML。
"""
import logging

from httpx import AsyncClient, HTTPStatusError

from app.config import Config
from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)

# 默认 Tavily 兼容服务（公益服务，无需 API Key）
DEFAULT_TAVILY_URL = "https://tavily.claude-code-best.win"


# ======================================================================
# Tool: search_web
# ======================================================================

SEARCH_WEB = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "在互联网上搜索行业新闻、技术文章、博客等。"
            "用于了解业界动态、竞品信息、版本发布、技术趋势等。"
            "当需要新闻动态或行业信息时调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，如 'vLLM latest release'、'LLM inference optimization'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5，最多 10",
                },
                "search_depth": {
                    "type": "string",
                    "enum": ["basic", "advanced"],
                    "description": "搜索深度，basic 返回快，advanced 更深入，默认 basic",
                },
                "include_answer": {
                    "type": "boolean",
                    "description": "是否让搜索引擎生成摘要回答，默认 false",
                },
            },
            "required": ["query"],
        },
    },
}


async def handle_search_web(args: dict) -> dict:
    """使用 Tavily 兼容协议搜索互联网"""
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    max_results = min(args.get("max_results", 5), 10)
    search_depth = args.get("search_depth", "basic")
    include_answer = args.get("include_answer", False)

    # 从环境变量读取配置，未配置则使用默认值
    tavily_url = (Config.TAVILY_API_URL or DEFAULT_TAVILY_URL).rstrip("/")
    tavily_key = Config.TAVILY_API_KEY or ""

    payload = {
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": include_answer,
    }

    headers = {"Content-Type": "application/json"}
    if tavily_key:
        headers["Authorization"] = f"Bearer {tavily_key}"

    try:
        async with AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{tavily_url}/search",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except HTTPStatusError as e:
        status = e.response.status_code
        if status == 401:
            return {"error": "Tavily API 认证失败（401），请检查 TAVILY_API_KEY 配置"}
        if status == 429:
            return {"error": "Tavily API 请求过于频繁（429），请稍后重试"}
        return {"error": f"Tavily search failed (HTTP {status}): {e}"}
    except Exception as e:
        return {"error": f"web search failed: {e}"}

    # 提取结果（兼容 Tavily 官方格式）
    raw_results = data.get("results", [])
    results = []
    for item in raw_results[:max_results]:
        if not isinstance(item, dict):
            continue
        snippet = item.get("content") or item.get("snippet", "")
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": snippet[:500],
            "score": item.get("score", 0),
        })

    # 如果有搜索引擎生成的摘要回答，一并返回
    answer = data.get("answer")

    response = {
        "results": results,
        "total": len(results),
        "query": query,
    }
    if answer:
        response["answer"] = answer

    return response


# ======================================================================
# Tool: extract_web_content
# ======================================================================

EXTRACT_WEB_CONTENT = {
    "type": "function",
    "function": {
        "name": "extract_web_content",
        "description": (
            "从指定 URL 提取清洁的文本内容，去除广告、导航等干扰信息。"
            "返回纯文本，适合 AI 阅读和分析。"
            "当需要深入了解某个搜索结果的详细信息时调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要提取内容的网页 URL",
                },
            },
            "required": ["url"],
        },
    },
}


async def handle_extract_web_content(args: dict) -> dict:
    """使用 Tavily 兼容协议提取网页内容"""
    url = args.get("url", "").strip()
    if not url:
        return {"error": "url is required"}

    tavily_url = (Config.TAVILY_API_URL or DEFAULT_TAVILY_URL).rstrip("/")
    tavily_key = Config.TAVILY_API_KEY or ""

    payload = {"url": url}
    headers = {"Content-Type": "application/json"}
    if tavily_key:
        headers["Authorization"] = f"Bearer {tavily_key}"

    try:
        async with AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{tavily_url}/extract",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except HTTPStatusError as e:
        return {"error": f"Content extraction failed (HTTP {e.response.status_code}): {e}"}
    except Exception as e:
        return {"error": f"content extraction failed: {e}"}

    # 提取清洁文本内容
    raw_content = data.get("content", "") or data.get("raw_content", "")
    if raw_content:
        return {
            "url": url,
            "content": raw_content[:8000],
            "truncated": len(raw_content) > 8000,
        }

    return {"url": url, "content": "", "note": "未提取到内容"}


# ======================================================================
# 注册
# ======================================================================

register_tool("search_web", SEARCH_WEB, handle_search_web)
register_tool("extract_web_content", EXTRACT_WEB_CONTENT, handle_extract_web_content)