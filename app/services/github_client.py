"""
GitHub API客户端封装
"""
import logging
import time
import requests
from typing import List, Dict, Any, Optional
import base64

from tenacity import (
    Retrying,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.config import Config


def _get_limiter():
    from app.services.tools.rate_limiter import get_limiter
    return get_limiter("github_rest")

logger = logging.getLogger(__name__)

# 默认单页大小
DEFAULT_PER_PAGE = 30
# 硬上限，避免循环失控
MAX_PAGES = 20

# 可重试的 HTTP 状态码：429（频率限制）/ 403（含 rate-limit）/ 5xx（服务端抖动）
# 401（PAT 失效）、404（无数据）不重试
RETRYABLE_STATUS = {429, 403, 500, 502, 503, 504}


class RateLimitError(Exception):
    """可重试的 GitHub API 错误（429 / 403-rate-limit / 5xx）。

    被 tenacity 捕获后按指数退避重试；401/404 等不抛此异常，直接返回。
    """

    def __init__(self, status_code: int, retry_after: float = 0.0):
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"GitHub API retryable error: {status_code}")


def _parse_retry_after(response: requests.Response) -> float:
    """从响应计算需要睡眠的秒数。

    优先级：``Retry-After`` 头 → ``X-RateLimit-Reset``（epoch 秒）→ 指数退避默认。
    返回值硬上限 60 秒，避免单次阻塞过久。
    """
    # 1. Retry-After 头（秒数或 HTTP 日期，这里只处理秒数）
    ra = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if ra:
        try:
            return min(float(ra), 60.0)
        except (ValueError, TypeError):
            pass

    # 2. X-RateLimit-Reset（epoch 秒，UTC）
    reset = response.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            wait = float(reset) - time.time()
            if wait > 0:
                return min(wait, 60.0)
        except (ValueError, TypeError):
            pass

    # 3. fallback：交给 tenacity 的指数退避
    return 0.0


class GitHubClient:
    """GitHub REST API客户端"""

    def __init__(self):
        self.headers = Config.get_github_headers()
        # 连接池大小适配并行 tool calls 场景（默认 10 不够用）
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(self.headers)

    def _do_request(self, method: str, url: str, params, kwargs) -> Any:
        """单次 HTTP 请求（不含重试逻辑）。

        - 可重试状态（429/403/5xx）抛 ``RateLimitError``，由外层 tenacity 退避重试。
        - 401/404 等不可重试状态记日志后返回 None。
        - 2xx 按 Accept 头解析 JSON 或返回文本。
        """
        response = self.session.request(method, url, params=params, **kwargs)
        status = response.status_code

        if status in RETRYABLE_STATUS:
            wait = _parse_retry_after(response)
            # 403 可能是 rate-limit，也可能是权限不足（非 rate-limit 的 403 重试无意义，
            # 但无法可靠区分；统一当作可重试，最多 3 次，重试不到就退）。
            logger.warning(
                f"GitHub API {status} (retryable) - URL: {url} - wait {wait:.1f}s"
            )
            raise RateLimitError(status, retry_after=wait)

        response.raise_for_status()

        if not response.content:
            return ""
        accept = (kwargs.get("headers") or {}).get("Accept", "").lower()
        if "json" in accept or not accept:
            return response.json()
        return response.text

    def _request_with_retry(
        self, method: str, url: str, params: Optional[Dict] = None, **kwargs
    ) -> Optional[Any]:
        """带退避重试的 HTTP 请求内核。

        ``_make_request``（仓库 REST API）与 ``_search_issues``（全局 Search API）
        共用此方法，统一退避策略。
        """
        limiter = _get_limiter()
        if limiter:
            wait = limiter.acquire_sync()
            if wait > 0:
                time.sleep(wait)
        try:
            for attempt in Retrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
                retry=retry_if_exception_type(RateLimitError),
                reraise=True,
            ):
                with attempt:
                    return self._do_request(method, url, params, kwargs)
        except RateLimitError as e:
            # 重试耗尽：若 Retry-After 指定了睡眠，最后一次已经睡过；
            # 这里仍可能未恢复，返回 None 让调用方用 ``or []`` 兜底，不清缓存。
            logger.error(
                f"GitHub API still {e.status_code} after retries - URL: {url}"
            )
            return None
        except requests.exceptions.HTTPError as e:
            # 401/404 等 raise_for_status 抛出的不可重试错误
            logger.error(f"GitHub API Error: {e} - URL: {url}")
            return None
        except Exception as e:
            logger.error(f"Request Error: {e} - URL: {url}")
            return None

    def _make_request(
        self, method: str, endpoint: str, params: Optional[Dict] = None,
        repo: Optional[str] = None, **kwargs
    ) -> Optional[Any]:
        """发送API请求（仓库 REST API 端点）

        默认按 JSON 解析响应。调用方传入 ``Accept`` header 为非 JSON media type
        （如 ``application/vnd.github.v3.diff``）时，返回原始文本。

        Args:
            repo: 完整 owner/repo（如 ``vllm-project/vllm``），必传。
        """
        if repo:
            url = f"https://api.github.com/repos/{repo}{endpoint}"
        else:
            raise ValueError("repo parameter is required")
        return self._request_with_retry(method, url, params, **kwargs)

    # ==================== Issues API ====================

    def get_issues(
        self,
        state: str = "open",
        per_page: int = DEFAULT_PER_PAGE,
        sort: str = "created",
        direction: str = "desc",
        labels: Optional[List[str]] = None,
        since: Optional[str] = None,
        page: int = 1,
        repo: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取issue列表

        Args:
            since: ISO 8601 时间戳，仅返回此时间之后更新的 issues（增量拉取用）
            page: 页码（从 1 开始），配合 ``per_page`` 实现分页
            repo: 完整 owner/repo，None 时用 Config 默认仓库
        """
        params = {
            "state": state,
            "per_page": per_page,
            "sort": sort,
            "direction": direction,
            "page": page,
        }
        if labels:
            params["labels"] = ",".join(labels)
        if since:
            params["since"] = since

        result = self._make_request("GET", "/issues", params=params, repo=repo)
        return result if isinstance(result, list) else []

    def get_issue(self, number: int, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取单个issue详情"""
        return self._make_request("GET", f"/issues/{number}", repo=repo)

    # ==================== Pull Requests API ====================

    def get_pulls(
        self,
        state: str = "open",
        per_page: int = DEFAULT_PER_PAGE,
        sort: str = "created",
        direction: str = "desc",
        page: int = 1,
        repo: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取PR列表

        Args:
            page: 页码（从 1 开始），配合 ``per_page`` 实现分页
            repo: 完整 owner/repo，None 时用 Config 默认仓库
        """
        params = {
            "state": state,
            "per_page": per_page,
            "sort": sort,
            "direction": direction,
            "page": page,
        }
        result = self._make_request("GET", "/pulls", params=params, repo=repo)
        return result if isinstance(result, list) else []

    def get_pull(self, number: int, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取单个PR详情"""
        return self._make_request("GET", f"/pulls/{number}", repo=repo)

    def get_user_pulls(self, username: str, state: str = "all",
                       repo: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取用户在指定仓库的 PR 列表（Search API，author 过滤）"""
        if not username:
            return []
        q_parts = [f"author:{username}", "type:pr"]
        if repo:
            q_parts.append(f"repo:{repo}")
        if state in ("open", "closed"):
            q_parts.append(f"is:{state}")
        elif state == "merged":
            q_parts.append("is:merged")
        return self._search_issues(" ".join(q_parts))

    def get_user_issues(self, username: str, state: str = "all",
                        repo: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取用户在指定仓库创建的 Issue 列表（Search API）"""
        if not username:
            return []
        q_parts = [f"author:{username}", "type:issue"]
        if repo:
            q_parts.append(f"repo:{repo}")
        if state in ("open", "closed"):
            q_parts.append(f"is:{state}")
        return self._search_issues(" ".join(q_parts))

    def get_user_issues_with_body(self, username: str, state: str = "all",
                                  repo: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取用户 issue 列表，包含完整 body（Search API + 单个 issue 拉取）

        Search API 不返回 body，需要逐个调 get_issue。数量通常 < 50，可接受。
        """
        issues = self.get_user_issues(username, state=state, repo=repo) or []
        enriched = []
        for it in issues:
            if not isinstance(it, dict):
                continue
            num = it.get("number")
            if not num:
                continue
            detail = self.get_issue(num, repo=repo)
            if detail and isinstance(detail, dict):
                # 合并：search API 的字段 + detail 的 body
                enriched.append({**it, "body": detail.get("body") or ""})
            else:
                enriched.append({**it, "body": ""})
        return enriched

    def _search_issues(self, query: str) -> List[Dict[str, Any]]:
        """统一的 GitHub Search API 调用（30/min 限额，同样走退避重试）

        Returns:
            items 列表
        """
        url = "https://api.github.com/search/issues"
        params = {"q": query, "per_page": 100, "sort": "created", "order": "desc"}
        result = self._request_with_retry("GET", url, params=params)
        if isinstance(result, dict):
            return result.get("items") or []
        return []

    def _search_issues_with_count(self, query: str) -> dict:
        """同 _search_issues，但返回包含 total_count 的 dict 结构

        Returns:
            {"items": [...], "total_count": int}
        """
        url = "https://api.github.com/search/issues"
        params = {"q": query, "per_page": 100, "sort": "created", "order": "desc"}
        result = self._request_with_retry("GET", url, params=params)
        if isinstance(result, dict):
            return {
                "items": result.get("items") or [],
                "total_count": result.get("total_count", 0),
            }
        return {"items": [], "total_count": 0}

    def get_pull_files(self, number: int, repo: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取PR的文件变更"""
        return self._make_request("GET", f"/pulls/{number}/files", repo=repo) or []

    def get_pull_diff(self, number: int, repo: Optional[str] = None) -> Optional[str]:
        """获取PR的diff文本"""
        if repo:
            url = f"https://api.github.com/repos/{repo}/pulls/{number}"
        else:
            url = f"{self.base_url}/pulls/{number}"
        headers = {"Accept": "application/vnd.github.v3.diff"}
        try:
            response = self.session.get(url, headers=headers)
            if response.status_code == 406:
                logger.warning(f"PR #{number} diff too large, GitHub returned 406")
                return None
            response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError as e:
            logger.error(f"GitHub API Error: {e} - URL: {url}")
            return None

    # ==================== Checks API ====================

    def get_check_runs(self, ref: str, repo: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取 commit 的 check runs（GitHub Actions）

        GitHub 返回 ``{"total_count": N, "check_runs": [...]}`` 包装；
        这里拆包只返回 check_runs 列表，方便调用方迭代。
        """
        result = self._make_request("GET", f"/commits/{ref}/check-runs", repo=repo)
        if isinstance(result, dict):
            return result.get("check_runs") or []
        if isinstance(result, list):
            return result
        return []

    def get_commit_status(self, ref: str, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取 commit 的 combined status（传统 status API，pre-GitHub-Actions CI）

        Returns: ``{"state": "success"|"failure"|"pending", "statuses": [...]}`` 或 None
        """
        return self._make_request("GET", f"/commits/{ref}/status", repo=repo)

    def get_combined_ci(self, ref: str, repo: Optional[str] = None) -> Dict[str, Any]:
        """聚合 check runs + commit status 给出统一 CI 状态

        Returns: ``{"status": "pass"|"fail"|"pending"|"unknown", "check_runs": N, "statuses": N}``

        性能优化：check_runs 是 Actions 主流路径，commit status 是兼容老 CI。
        当 check_runs 有结果时不重复调 status API。
        """
        if not ref:
            return {"status": "unknown", "check_runs": 0, "statuses": 0}

        check_runs = self.get_check_runs(ref, repo=repo) or []
        statuses: list = []
        # 只有 check_runs 看起来空或返回 404/无 actions 时，才 fallback 到 commit status
        # 注意：check_runs 不会 404，所以如果返回空就说明没用 Actions
        if not check_runs:
            commit_status = self.get_commit_status(ref, repo=repo) or {}
            statuses = commit_status.get("statuses") or []

        # 综合所有信号，按 fail > pending > pass 优先级
        statuses_all = []
        for cr in check_runs:
            if not isinstance(cr, dict):
                continue
            conclusion = cr.get("conclusion")
            s = cr.get("status")
            if conclusion in ("failure", "cancelled", "timed_out", "action_required"):
                statuses_all.append(("fail", "check_run"))
            elif conclusion == "success":
                statuses_all.append(("pass", "check_run"))
            elif s in ("queued", "in_progress", "waiting", "requested", "pending"):
                statuses_all.append(("pending", "check_run"))
        for st in statuses:
            if not isinstance(st, dict):
                continue
            s = st.get("state")
            if s == "success":
                statuses_all.append(("pass", "status"))
            elif s in ("failure", "error"):
                statuses_all.append(("fail", "status"))
            elif s in ("pending"):
                statuses_all.append(("pending", "status"))

        if not statuses_all:
            return {"status": "unknown", "check_runs": len(check_runs), "statuses": len(statuses)}

        # 优先级：fail > pending > pass
        if any(x[0] == "fail" for x in statuses_all):
            final = "fail"
        elif any(x[0] == "pending" for x in statuses_all):
            final = "pending"
        else:
            final = "pass"

        return {"status": final, "check_runs": len(check_runs), "statuses": len(statuses)}

    # ==================== CODEOWNERS API ====================

    def get_codeowners(self, repo: Optional[str] = None) -> Optional[str]:
        """获取CODEOWNERS文件内容"""
        result = self._make_request("GET", "/contents/.github/CODEOWNERS", repo=repo)
        if result and "content" in result:
            # Base64解码
            return base64.b64decode(result["content"]).decode("utf-8")
        return None

    # ==================== Compare API ====================

    def compare_branches(self, base: str, head: str, repo: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """比较两个分支"""
        return self._make_request("GET", f"/compare/{base}...{head}", repo=repo)

    # ==================== Commits API ====================
