"""
学术论文搜索工具

从 intelligence_report.py 迁移。
"""
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)

ARXIV_TIMEOUT = 30


# ======================================================================
# Tool: search_arxiv
# ======================================================================

SEARCH_ARXIV = {
    "type": "function",
    "function": {
        "name": "search_arxiv",
        "description": "在 arXiv 搜索与任务相关的学术论文。用于学术动态调研。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，英文效果更好，如 'flash attention triton kernel'",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回数量，默认 5",
                },
            },
            "required": ["query"],
        },
    },
}


def _arxiv_fetch(url: str, timeout: int = ARXIV_TIMEOUT) -> str:
    """请求 arXiv API，返回 XML 文本"""
    req = urllib.request.Request(url, headers={"User-Agent": "vllm-assistant/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _parse_arxiv_response(xml_data: str, max_results: int) -> list:
    """解析 arXiv API 返回的 XML，提取论文列表"""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)
    entries = root.findall("atom:entry", ns)

    results = []
    for entry in entries[:max_results]:
        title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")
        published = entry.findtext("atom:published", "", ns)
        arxiv_url = entry.findtext("atom:id", "", ns)

        authors = []
        for author in entry.findall("atom:author", ns):
            name = author.findtext("atom:name", "", ns)
            if name:
                authors.append(name)

        results.append({
            "title": title,
            "authors": authors[:5],
            "summary": summary[:500],
            "published": published,
            "url": arxiv_url,
        })
    return results


async def handle_search_arxiv(args: dict) -> dict:
    """搜索 arXiv 论文

    搜索策略（按优先级）：
    1. 先按标题搜索 (ti:)，速度快，结果精准
    2. 标题搜索无结果时，按摘要搜索 (abs:)
    3. 都失败时，用单个核心词按全文搜索 (all:) 再试一次
    """
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    max_results = min(args.get("max_results", 5), 10)
    encoded = urllib.parse.quote(query)

    # 提取核心词（取第一个有意义的词作为备选）
    core_terms = [w for w in query.split() if len(w) > 2 and w.lower() not in ("the", "for", "and", "with", "from")]
    core_word = core_terms[0] if core_terms else query.split()[0]

    # 策略 1: 标题搜索
    for search_field in ["ti", "abs"]:
        url = (
            f"https://export.arxiv.org/api/query?"
            f"search_query={search_field}:{encoded}&max_results={max_results}&sortBy=relevance"
        )
        try:
            xml_data = _arxiv_fetch(url, timeout=ARXIV_TIMEOUT)
            results = _parse_arxiv_response(xml_data, max_results)
            if results:
                return {"results": results, "query": query}
        except Exception:
            logger.warning(f"arXiv {search_field} search failed for: {query}")

    # 策略 2: 全文搜索核心词（备选）
    try:
        url = (
            f"https://export.arxiv.org/api/query?"
            f"search_query=all:{urllib.parse.quote(core_word)}&max_results={max_results}&sortBy=relevance"
        )
        xml_data = _arxiv_fetch(url, timeout=ARXIV_TIMEOUT)
        results = _parse_arxiv_response(xml_data, max_results)
        if results:
            return {"results": results, "query": core_word}
    except Exception:
        logger.warning(f"arXiv fallback search failed for: {core_word}")

    return {"results": [], "query": query, "note": "arXiv search timed out or returned no results"}


# ======================================================================
# 注册
# ======================================================================

register_tool("search_arxiv", SEARCH_ARXIV, handle_search_arxiv)