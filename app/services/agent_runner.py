"""
Agent 执行引擎

只做流程控制，不做业务逻辑。
- chat(): streaming 对话，内部自动循环处理 tool_calls
- run_task(): 异步任务执行

流程：
1. 从 MemoryService 检索相关记忆，注入 system prompt
2. 调 OpenAI SDK streaming chat API
3. 流式返回 token 事件
4. 遇到 tool_calls -> 查 tools/registry 获取 handler -> 执行
5. 工具结果返回给模型继续推理
6. 对话结束后自动 remember() 新知识
"""
import asyncio
import json
import logging
from typing import AsyncIterator, List, Dict, Optional, Any

from openai import AsyncOpenAI

from app.config import Config
from app.services.tools import registry as tool_registry

logger = logging.getLogger(__name__)

# SSE 事件类型
EVENT_TOKEN = "token"
EVENT_THINKING = "thinking"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_DONE = "done"
EVENT_ERROR = "error"


class AgentRunner:
    """Agent 执行引擎——只做流程控制，不做业务逻辑"""

    # 最大 tool 循环轮次（防止无限循环）
    MAX_TOOL_ROUNDS = 100
    # 单次 tool 执行超时（秒）
    TOOL_TIMEOUT = 30.0
    # 全局超时（秒）
    CHAT_TIMEOUT = 600.0

    def __init__(self):
        import httpx
        self._http_client = httpx.AsyncClient(
            proxy=None, timeout=self.CHAT_TIMEOUT, trust_env=False
        )
        self.client = AsyncOpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL,
            http_client=self._http_client,
        )
        self.model = Config.OPENAI_MODEL
        self._memory_service = None

    async def close(self):
        """显式关闭 HTTP 客户端，避免资源泄漏"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    @property
    def memory_service(self):
        if self._memory_service is None:
            from app.services.memory_service import MemoryService
            self._memory_service = MemoryService()
        return self._memory_service

    async def chat(
        self,
        messages: List[dict],
        tools: Optional[List[str]] = None,
        stream: bool = True,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[dict]:
        """streaming 对话。返回事件流，每个事件是 dict。

        内部自动循环处理 tool_calls：
        1. 注入记忆到 system prompt
        2. 调 OpenAI streaming API
        3. 遇到 tool_calls -> 执行 -> 继续
        4. 直到模型返回纯文本为止

        Args:
            messages: 对话消息列表
            tools: 可用工具名称列表，None 使用全部，[] 不使用工具
            stream: 是否 stream（默认 True）
            system_prompt: 可选的 system prompt 覆盖

        Yields:
            {"type": "token", "data": "..."}
            {"type": "tool_call", "data": {"name": ..., "args": ...}}
            {"type": "tool_result", "data": {...}}
            {"type": "done", "data": null}
            {"type": "error", "data": "..."}
        """
        # 1. 构建 system prompt（注入记忆 + 自定义 prompt）
        system = self._build_system_prompt(messages, system_prompt)

        # 2. 构建完整消息列表
        full_messages = [{"role": "system", "content": system}]
        for m in messages:
            if m.get("role") != "system":
                full_messages.append(m)

        # 3. 获取 tool schemas
        #    None -> 使用全部；[] -> 不使用工具
        if tools is not None:
            tool_schemas = tool_registry.get_tool_schemas(tools)  # 空列表 = 不使用
        else:
            tool_schemas = tool_registry.get_tool_schemas()  # 全部

        # 4. Tool 循环
        for round_num in range(self.MAX_TOOL_ROUNDS):
            kwargs = {
                "model": self.model,
                "messages": full_messages,
                "max_tokens": 4096,
                "temperature": 0.7,
                "timeout": self.CHAT_TIMEOUT,
            }
            if tool_schemas:
                kwargs["tools"] = tool_schemas

            # 带重试的 API 调用（429/500 等错误最多重试 10 次）
            # 退避策略：优先用 Retry-After 头，否则指数退避（1s→max 10s）
            for attempt in range(10):
                try:
                    if stream:
                        response = await self.client.chat.completions.create(**kwargs, stream=True)
                        assistant_message, text_content = await self._handle_streaming_response(response)
                    else:
                        response = await self.client.chat.completions.create(**kwargs, stream=False)
                        assistant_message, text_content = await self._handle_non_streaming_response(response)
                    break
                except Exception as e:
                    if attempt < 9:
                        retry_after = self._parse_openai_retry_after(e)
                        wait = min(retry_after if retry_after > 0 else (2 ** attempt), 10.0)
                        logger.warning(
                            "AI chat failed (attempt %d/10, retry in %.1fs): %s",
                            attempt + 1, wait, e
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.exception("AI chat failed after 10 attempts")
                        yield {"type": EVENT_ERROR, "data": str(e)}
                        return

            # 如果有文本内容，区分 thinking 和最终回答
            if text_content:
                if assistant_message.get("tool_calls"):
                    # 工具调用之前的文本视为思考过程，多次 thinking 用分隔线区分
                    prefix = "\n\n---\n\n" if round_num > 0 else ""
                    yield {"type": EVENT_THINKING, "data": prefix + text_content}
                else:
                    # 没有工具调用，是最终回答
                    yield {"type": EVENT_TOKEN, "data": text_content}

            full_messages.append(assistant_message)

            # 检查是否有 tool_calls
            if assistant_message.get("tool_calls"):
                # 发出 tool_call 事件
                for tc in assistant_message["tool_calls"]:
                    yield {
                        "type": EVENT_TOOL_CALL,
                        "data": {
                            "name": tc["function"]["name"],
                            "args": self._safe_json_loads(tc["function"]["arguments"]),
                        },
                    }

                # 执行所有 tool_calls
                for tc in assistant_message["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    tool_args = self._safe_json_loads(tc["function"]["arguments"])

                    result = await tool_registry.execute_tool(tool_name, tool_args)

                    # 发出 tool_result 事件
                    yield {"type": EVENT_TOOL_RESULT, "data": {"name": tool_name, "result": result}}

                    # 将 tool 结果加入消息列表
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                # 继续下一轮循环
                continue

            # 没有 tool_calls，对话结束
            # 自动存储新知识
            if text_content:
                self._auto_remember(messages, text_content)

            yield {"type": EVENT_DONE, "data": None}
            return

        # 超过最大轮次
        yield {"type": EVENT_ERROR, "data": f"Exceeded maximum tool rounds ({self.MAX_TOOL_ROUNDS})"}
        yield {"type": EVENT_DONE, "data": None}

    async def run_task(self, task_type: str, params: dict) -> dict:
        """异步任务——查 tasks/registry -> 执行，返回结果

        Args:
            task_type: 任务类型（如 "daily_report", "tech_news"）
            params: 任务参数

        Returns:
            任务结果 dict
        """
        from app.services.tasks import registry as task_registry

        handler = task_registry.get_task(task_type)
        if not handler:
            return {"error": f"Task type '{task_type}' not found"}

        try:
            result = await handler(params)
            return result if isinstance(result, dict) else {"result": result}
        except Exception as e:
            logger.exception(f"Task '{task_type}' failed")
            return {"error": str(e)}

    # ======================================================================
    # 内部方法
    # ======================================================================

    def _parse_openai_retry_after(self, e: Exception) -> float:
        """从 OpenAI API 异常中解析 Retry-After 时间。

        优先读取异常中的 ``response`` 属性（httpx 或 requests 响应对象），
        取 ``Retry-After`` 头或 ``X-RateLimit-Reset-`` 头；解析失败返回 0
        让调用方用指数退避兜底。
        """
        try:
            # openai 库抛出的 APIError 或 RateLimitError 有 response 属性
            resp = getattr(e, "response", None)
            if resp is not None and hasattr(resp, "headers"):
                # httpx Response
                ra = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
                if ra:
                    parsed = float(ra)
                    return min(parsed, 10.0)

                # X-RateLimit-Reset-Reset 是 epoch 秒
                reset = resp.headers.get("x-ratelimit-reset") or resp.headers.get("X-RateLimit-Reset")
                if reset:
                    import time
                    wait = float(reset) - time.time()
                    if wait > 0:
                        return min(wait, 10.0)

            # 某些异常以字符串形式包含 "try again in X.Xs"
            msg = str(e).lower()
            import re
            m = re.search(r"(?:retry after|try again in)\s*([\d.]+)\s*s", msg)
            if m:
                return min(float(m.group(1)), 10.0)
        except (ValueError, TypeError, AttributeError):
            pass
        return 0.0

    def _build_system_prompt(self, messages: List[dict], custom_prompt: Optional[str] = None) -> str:
        """构建 system prompt，注入相关记忆"""
        user_query = self._last_user_message(messages)

        memories = []
        if user_query.strip():
            memories = self.memory_service.recall(query=user_query, top_k=3)

        memory_context = ""
        if memories:
            memory_lines = []
            for i, mem in enumerate(memories, 1):
                content_preview = mem.get("content", "")[:300]
                source_ref = mem.get("source_ref", "")
                source_type = mem.get("source_type", "")
                tags = ", ".join(mem.get("tags", [])[:5])
                memory_lines.append(
                    f"[{i}] 来源: {source_type} | 引用: {source_ref} | 标签: {tags}\n{content_preview}"
                )
            memory_context = "\n\n---\n### 相关上下文（来自知识库）\n" + "\n\n".join(memory_lines)

        # 构建已配置仓库列表，让 AI 知道它能操作哪些项目
        configured_repos = list(Config.REPOS.keys())
        repo_list_text = ""
        if configured_repos:
            repo_names = "、".join(configured_repos)
            repo_list_text = f"\n\n## 已配置的代码仓库\n当前支持的项目：{repo_names}。GitHub 搜索工具（search_issues 等）可搜索任意 GitHub 仓库，不受此限制。"

        system_prompt = f"""你是一个 vLLM 技术领域的 AI 助手，帮助贡献者分析 issue/PR、搜索技术资料、生成报告。

## 工作原则
1. 使用工具获取最新信息，不要编造数据
2. 引用来源时注明 issue/PR 编号或论文标题
3. 搜索时优先用英文关键词（GitHub/arXiv 搜索效果更好）
4. 中文回答，技术术语保留英文
5. 不确定的内容不要编造，说明"需要进一步确认"
6. 你可以同时调用多个工具来提高效率

## 可用工具
你可以在对话中调用工具搜索 GitHub、arXiv、本地代码库和知识库。
当需要获取最新信息时，主动使用工具。{repo_list_text}{memory_context}"""

        if custom_prompt:
            system_prompt = f"{custom_prompt}\n\n{system_prompt}"

        return system_prompt

    def _last_user_message(self, messages: List[dict]) -> str:
        """获取最后一条用户消息"""
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")[:200]
        return ""

    async def _handle_streaming_response(self, response) -> tuple:
        """处理 streaming 响应。

        使用 async for 迭代以避免阻塞事件循环。

        Returns:
            (assistant_message_dict, text_content_str)
        """
        content_parts = []
        tool_calls = {}

        async for chunk in response:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if not delta:
                continue

            if delta.content:
                content_parts.append(delta.content)

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {
                            "id": tc_delta.id or "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    # OpenAI streaming: id 可能在后续 chunk 才出现
                    if tc_delta.id:
                        tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls[idx]["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

        text_content = "".join(content_parts) if content_parts else ""

        assistant_message = {"role": "assistant", "content": text_content or None}
        if tool_calls:
            assistant_message["tool_calls"] = [
                tool_calls[i] for i in sorted(tool_calls.keys())
            ]

        return assistant_message, text_content

    def _handle_non_streaming_response(self, response) -> tuple:
        """处理非 streaming 响应

        Returns:
            (assistant_message_dict, text_content_str)
        """
        choice = response.choices[0]
        msg = choice.message

        text_content = msg.content or ""
        assistant_message = {"role": "assistant", "content": text_content or None}

        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]

        return assistant_message, text_content

    def _safe_json_loads(self, s: str) -> dict:
        """安全解析 JSON 字符串"""
        if not s:
            return {}
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return {}

    def _auto_remember(self, messages: List[dict], response_content: str) -> None:
        """自动存储对话中的新知识

        从最后一条 user message 和 AI 的最终回答中提取有价值的对话知识。
        """
        if not response_content or len(response_content) < 100:
            return

        user_msg = self._last_user_message(messages)
        if not user_msg:
            return

        if len(response_content) > 200 and not any(
            kw in response_content[:50] for kw in ["好的", "明白", "可以", "没问题", "抱歉"]
        ):
            self.memory_service.remember(
                content=f"## 用户问题\n{user_msg[:200]}\n\n## AI 回答\n{response_content[:1000]}",
                source_type="conversation",
                tags=["auto", "conversation"],
            )