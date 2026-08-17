"""
统一 LLM 客户端（同步）

职责：
- 管理同步 HTTP 客户端生命周期（httpx.Client）
- 统一的 retry/退避策略
- 统一的 JSON 安全解析

自 Agent 迁移到 OpenAI Agents SDK 后，聊天/报告走 agent_sdk（agent_sdk/model.py
的自定义 AsyncOpenAI 客户端），本模块仅服务 AIAssistant 等需要同步单次调用的场景。
"""
import json
import logging
import re
import time
from typing import Optional, Any

import httpx
from openai import OpenAI

from app.config import Config

logger = logging.getLogger(__name__)

# SSE 事件类型（保留导出，供 agent_sdk 复用协议常量）
EVENT_TOKEN = "token"
EVENT_THINKING = "thinking"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_DONE = "done"
EVENT_ERROR = "error"

# 模型 max_tokens 硬上限（实际由模型决定，配置值超过此值时截断）
MODEL_MAX_TOKENS_LIMIT = 393216

# 默认超时
DEFAULT_TIMEOUT = 120.0
CHAT_TIMEOUT = 600.0


class LLMClient:
    """统一同步 LLM 客户端"""

    def __init__(self):
        self._sync_client = httpx.Client(
            proxy=None,
            timeout=DEFAULT_TIMEOUT,
            trust_env=False,
        )
        self._sync_openai = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL,
            http_client=self._sync_client,
        )
        self.model = Config.OPENAI_MODEL

    def close(self):
        """显式关闭 HTTP 客户端，避免资源泄漏"""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None

    # ======================================================================
    # 统一的 retry/退避策略
    # ======================================================================

    @staticmethod
    def parse_retry_after(e: Exception) -> float:
        """从 OpenAI API 异常中解析 Retry-After 时间。

        优先读取异常中的 ``response`` 属性（httpx 或 requests 响应对象），
        取 ``Retry-After`` 头或 ``X-RateLimit-Reset`` 头；解析失败返回 0
        让调用方用指数退避兜底。
        """
        try:
            resp = getattr(e, "response", None)
            if resp is not None and hasattr(resp, "headers"):
                ra = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
                if ra:
                    return min(float(ra), 10.0)
                reset = resp.headers.get("x-ratelimit-reset") or resp.headers.get("X-RateLimit-Reset")
                if reset:
                    wait = float(reset) - time.time()
                    if wait > 0:
                        return min(wait, 10.0)
            msg = str(e).lower()
            m = re.search(r"(?:retry after|try again in)\s*([\d.]+)\s*s", msg)
            if m:
                return min(float(m.group(1)), 10.0)
        except (ValueError, TypeError, AttributeError):
            pass
        return 0.0

    # ======================================================================
    # 统一的 JSON 安全解析
    # ======================================================================

    @staticmethod
    def safe_json_loads(s: str) -> dict:
        """安全解析 JSON 字符串"""
        if not s:
            return {}
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def safe_json(content: str, default: Any = None) -> Any:
        """解析 AI 返回的 JSON，失败时尝试自动修复常见格式错误"""
        if not content:
            return default
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
        # 尝试修复常见问题：字段名缺少引号、值缺少引号、末尾逗号
        try:
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
            cleaned = re.sub(r'\n```\s*$', '', cleaned)
            cleaned = re.sub(r'(?<=[{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'"\1":', cleaned)
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError, re.error):
            return default

    # ======================================================================
    # 同步调用（供 AIAssistant / single-shot 翻译等使用）
    # ======================================================================

    def chat_sync(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """同步 chat 调用 + 重试 + 错误处理"""
        last_exc: Optional[Exception] = None
        max_tokens = min(max_tokens, MODEL_MAX_TOKENS_LIMIT)
        for attempt in range(10):
            try:
                response = self._sync_openai.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=DEFAULT_TIMEOUT,
                )
                content = response.choices[0].message.content
                if not content:
                    logger.warning("AI returned empty content")
                return content or ""
            except Exception as e:
                last_exc = e
                if attempt < 9:
                    retry_after = self.parse_retry_after(e)
                    wait = min(retry_after if retry_after > 0 else (2 ** attempt), 10.0)
                    logger.warning(
                        "AI chat failed (attempt %d/10, retry in %.1fs): %s",
                        attempt + 1, wait, e
                    )
                    time.sleep(wait)
                else:
                    logger.exception("AI chat failed after 10 attempts")
        raise last_exc  # type: ignore[misc]