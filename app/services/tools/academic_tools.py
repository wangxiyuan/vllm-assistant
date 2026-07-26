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


async def handle_search_arxiv(args: dict) -> dict:
    """搜索 arXiv 论文"""
    query = args.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    max_results = min(args.get("max_results", 5), 10)
    encoded = urllib.parse.quote(query)
    url = f"https://export.arxiv.org/api/query?search_query=all:{encoded}&max_results={max_results}&sortBy=relevance"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "vllm-assistant/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8")
    except Exception as e:
        return {"error": f"arxiv search failed: {e}"}

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

    return {"results": results, "query": query}


# ======================================================================
# 注册
# ======================================================================

register_tool("search_arxiv", SEARCH_ARXIV, handle_search_arxiv)