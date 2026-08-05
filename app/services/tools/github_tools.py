"""
GitHub 工具集

迁移自 intelligence_report.py 的 5 个 tool 函数：
- search_issues: 搜索 GitHub issue/PR
- get_issue_detail: 获取 issue/PR 正文和评论
- get_pr_diff: 获取 PR diff
- search_arxiv: 搜索 arXiv 论文（已迁移到 academic_tools.py）
- get_github_releases: 获取仓库 release 列表
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services._shared import get_github_client
from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)

# ======================================================================
# Tool 1: search_issues
# ======================================================================

SEARCH_ISSUES = {
    "type": "function",
    "function": {
        "name": "search_issues",
        "description": "在指定 GitHub 仓库搜索 issue/PR。可按关键词、状态、时间过滤。用于发现与任务相关的讨论。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，空字符串则返回最近创建的 issue/PR",
                },
                "repo": {
                    "type": "string",
                    "description": "仓库全名，如 'vllm-project/vllm'",
                },
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "all"],
                    "description": "issue/PR 状态过滤，默认 all",
                },
                "days_back": {
                    "type": "integer",
                    "description": "只搜索最近 N 天内创建的，默认 90",
                },
            },
            "required": ["repo"],
        },
    },
}


async def handle_search_issues(args: dict) -> dict:
    """搜索 issue/PR"""
    repo = args.get("repo", "")
    if not repo:
        return {"error": "repo is required"}

    client = get_github_client()
    query_parts = [f"repo:{repo}"]
    state = args.get("state", "all")
    if state in ("open", "closed"):
        query_parts.append(f"is:{state}")

    days_back = args.get("days_back", 90)
    if days_back:
        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
        query_parts.append(f"created:>={since}")

    keywords = args.get("query", "").strip()
    if keywords:
        query_parts.append(keywords)

    # 搜索条数上限（AI 有轮次限制，返回太多会导致选择困难）
    SEARCH_LIMIT = 20

    query = " ".join(query_parts)
    result = client._search_issues_with_count(query)
    items = result.get("items") or []
    total_count = result.get("total_count", len(items))

    results = []
    for item in items[:SEARCH_LIMIT]:
        if not isinstance(item, dict):
            continue
        html_url = item.get("html_url", "")
        item_type = "pr" if "/pull/" in html_url else "issue"
        results.append({
            "number": item.get("number"),
            "title": item.get("title", ""),
            "state": item.get("state", "unknown"),
            "type": item_type,
            "merged": item.get("merged", False),
            "created_at": item.get("created_at"),
            "comments": item.get("comments", 0),
            "url": html_url,
            "labels": [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)][:5],
        })

    return {
        "results": results,
        "total": min(total_count, SEARCH_LIMIT),
        "total_count": total_count,
        "query": query,
        "truncated": total_count > SEARCH_LIMIT,
    }


# ======================================================================
# Tool 2: get_issue_detail
# ======================================================================

GET_ISSUE_DETAIL = {
    "type": "function",
    "function": {
        "name": "get_issue_detail",
        "description": "获取某个 issue/PR 的正文内容和评论。当 search_issues 发现感兴趣的条目时调用此函数深入了解。",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "仓库全名，如 'vllm-project/vllm'",
                },
                "number": {
                    "type": "integer",
                    "description": "issue/PR 编号",
                },
            },
            "required": ["repo", "number"],
        },
    },
}


async def handle_get_issue_detail(args: dict) -> dict:
    """获取 issue/PR 正文和评论"""
    repo = args.get("repo", "")
    number = args.get("number")
    if not repo or not number:
        return {"error": "repo and number are required"}

    client = get_github_client()
    url = f"https://api.github.com/repos/{repo}/issues/{number}"
    item = client._request_with_retry("GET", url)

    if not item or not isinstance(item, dict):
        return {"error": f"not found: {repo}#{number}"}

    # 获取评论
    comments = []
    comment_count = item.get("comments", 0)
    if comment_count > 0:
        comments_url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
        raw_comments = client._request_with_retry("GET", comments_url, params={"per_page": 20})
        if isinstance(raw_comments, list):
            for c in raw_comments[:20]:
                if isinstance(c, dict):
                    comments.append({
                        "author": (c.get("user") or {}).get("login", ""),
                        "body": (c.get("body") or "")[:500],
                        "created_at": c.get("created_at"),
                    })

    html_url = item.get("html_url", "")
    item_type = "pr" if "/pull/" in html_url else "issue"

    return {
        "number": item.get("number"),
        "title": item.get("title", ""),
        "state": item.get("state", "unknown"),
        "type": item_type,
        "body": (item.get("body") or "")[:3000],
        "author": (item.get("user") or {}).get("login", ""),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "labels": [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)],
        "comments_count": comment_count,
        "comments": comments,
        "url": html_url,
    }


# ======================================================================
# Tool 3: get_pr_diff
# ======================================================================

GET_PR_DIFF = {
    "type": "function",
    "function": {
        "name": "get_pr_diff",
        "description": "获取某个 PR 的 diff 内容。当需要分析 PR 的具体代码变更时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "仓库全名，如 'vllm-project/vllm'",
                },
                "number": {
                    "type": "integer",
                    "description": "PR 编号",
                },
            },
            "required": ["repo", "number"],
        },
    },
}


async def handle_get_pr_diff(args: dict) -> dict:
    """获取 PR diff"""
    repo = args.get("repo", "")
    number = args.get("number")
    if not repo or not number:
        return {"error": "repo and number are required"}

    client = get_github_client()
    url = f"https://api.github.com/repos/{repo}/pulls/{number}"
    diff = client._request_with_retry(
        "GET", url, headers={"Accept": "application/vnd.github.v3.diff"}
    )
    if not isinstance(diff, str):
        return {"error": "diff not available"}

    return {
        "number": number,
        "repo": repo,
        "diff": diff[:6000],
        "truncated": len(diff) > 6000,
    }


# ======================================================================
# Tool 4: get_github_releases
# ======================================================================

GET_GITHUB_RELEASES = {
    "type": "function",
    "function": {
        "name": "get_github_releases",
        "description": "获取 GitHub 仓库最近的 release 列表。用于了解项目的版本发布动态，避免编造版本号。",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "仓库全名，如 'vllm-project/vllm'",
                },
                "per_page": {
                    "type": "integer",
                    "description": "返回数量，默认 5",
                },
            },
            "required": ["repo"],
        },
    },
}


async def handle_get_github_releases(args: dict) -> dict:
    """获取 GitHub 仓库最近的 release 列表"""
    repo = args.get("repo", "")
    if not repo:
        return {"error": "repo is required"}

    per_page = min(args.get("per_page", 5), 10)
    client = get_github_client()
    url = f"https://api.github.com/repos/{repo}/releases"
    releases = client._request_with_retry("GET", url, params={"per_page": per_page})

    if not isinstance(releases, list):
        return {"error": "releases not available"}

    results = []
    for r in releases[:per_page]:
        if not isinstance(r, dict):
            continue
        results.append({
            "tag": r.get("tag_name", ""),
            "name": r.get("name", ""),
            "published_at": r.get("published_at"),
            "prerelease": r.get("prerelease", False),
            "draft": r.get("draft", False),
            "body": (r.get("body") or "")[:1000],
            "url": r.get("html_url", ""),
        })

    return {"results": results, "repo": repo}


# ======================================================================
# 注册所有工具
# ======================================================================

register_tool("search_issues", SEARCH_ISSUES, handle_search_issues)
register_tool("get_issue_detail", GET_ISSUE_DETAIL, handle_get_issue_detail)
register_tool("get_pr_diff", GET_PR_DIFF, handle_get_pr_diff)
register_tool("get_github_releases", GET_GITHUB_RELEASES, handle_get_github_releases)