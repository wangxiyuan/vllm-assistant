"""
OpenAI Agents SDK — LLM 模型构造

统一构造 OpenAIChatCompletionsModel，指向项目现有的 OpenAI 兼容端点
（Config.OPENAI_BASE_URL / OPENAI_API_KEY）。非 OpenAI 平台，关闭官方 tracing。
"""
import httpx
from openai import AsyncOpenAI

from app.config import Config

# 读超时（与旧 LLMClient 保持一致）
CHAT_TIMEOUT = 600.0

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    """全局单例 AsyncOpenAI 客户端（每次请求复用）"""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL,
            timeout=httpx.Timeout(
                CHAT_TIMEOUT,
                connect=15.0,
                read=CHAT_TIMEOUT,
                write=30.0,
                pool=None,
            ),
        )
    return _client


def build_chat_model():
    """构造 ChatCompletions 模型（OpenAI Compatible 端点）"""
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
    return OpenAIChatCompletionsModel(
        model=Config.OPENAI_MODEL,
        openai_client=get_openai_client(),
        buffer_streamed_tool_calls=True,
    )


def disable_tracing() -> None:
    """非 OpenAI 平台必须关闭官方 tracing，否则每请求报 401。"""
    from agents import set_tracing_disabled
    set_tracing_disabled(disabled=True)