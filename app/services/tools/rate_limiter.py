"""
简单的速率限制器

用于工具执行层，防止短时间内大量调用 GitHub API 等外部服务。
"""
import asyncio
import logging
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """令牌桶速率限制器

    每个工具有独立的桶，桶满后继续调用会等待直到有令牌可用。

    Args:
        rate: 每秒允许的请求数
        burst: 桶容量（允许的瞬时峰值）
    """

    def __init__(self, rate: float = 1.0, burst: int = 3):
        self.rate = rate
        self.burst = burst
        self._tokens: float = burst
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    async def acquire(self) -> float:
        """获取一个令牌。等待直到有令牌可用。

        Returns:
            等待时间（秒）
        """
        async with self._async_lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            # 需要等待
            wait_time = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
        await asyncio.sleep(wait_time)
        return wait_time

    def acquire_sync(self) -> float:
        """同步版本的 acquire，用于非 asyncio 环境"""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return 0.0
            wait_time = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
        if wait_time > 0:
            time.sleep(wait_time)
        return wait_time

    def _refill(self):
        """补充令牌"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now


# 全局速率限制器映射
_limiters: Dict[str, RateLimiter] = {}

# 默认限流配置
# GitHub Search API 限额 30 req/min（搜索类工具），REST API 限额 5000 req/h（详情类工具）
DEFAULT_LIMITS = {
    "github_search": RateLimiter(rate=0.4, burst=3),   # Search API: 30 req/min
    "github_rest": RateLimiter(rate=1.0, burst=5),      # REST API: 5000 req/h
    "arxiv": RateLimiter(rate=1.0, burst=3),             # arXiv API: 较宽松
}


def get_limiter(name: str) -> Optional[RateLimiter]:
    """获取指定名称的速率限制器"""
    return DEFAULT_LIMITS.get(name)


def get_limiter_for_tool(tool_name: str) -> Optional[RateLimiter]:
    """根据工具名获取对应的速率限制器

    - search_issues 走 GitHub Search API（30 req/min，更严格）
    - get_issue_detail / get_pr_diff / get_github_releases 走 GitHub REST API（5000 req/h）
    - search_arxiv 走 arXiv API
    """
    if tool_name == "search_issues":
        return get_limiter("github_search")
    if tool_name in ("get_issue_detail", "get_pr_diff", "get_github_releases"):
        return get_limiter("github_rest")
    if tool_name == "search_arxiv":
        return get_limiter("arxiv")
    return None