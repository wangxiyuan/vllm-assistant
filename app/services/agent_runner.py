"""
Agent 执行引擎

只做流程控制，不做业务逻辑。
- chat(): streaming 对话，内部自动循环处理 tool_calls
- run_task(): 异步任务执行

流程：
1. 从 MemoryService 检索相关记忆，注入 system prompt
2. 调 LLMClient streaming chat API
3. 流式返回 token 事件
4. 遇到 tool_calls -> 查 tools/registry 获取 handler -> 执行
5. 工具结果返回给模型继续推理
6. 对话结束后自动 remember() 新知识
"""
import asyncio
import json
import logging
import re
import uuid
from typing import AsyncIterator, List, Dict, Optional, Any

from app.config import Config
from app.services.llm import LLMClient, EVENT_TOKEN, EVENT_THINKING, EVENT_TOOL_CALL, EVENT_TOOL_RESULT, EVENT_DONE, EVENT_ERROR
from app.services.tools import registry as tool_registry

logger = logging.getLogger(__name__)


class AgentRunner:
    """Agent 执行引擎——只做流程控制，不做业务逻辑"""

    # 最大 tool 循环轮次（防止无限循环、低效读取）
    MAX_TOOL_ROUNDS = 30
    # 还剩多少轮时提醒模型收尾
    WRAP_UP_REMAINING_ROUNDS = 5
    # 单次 tool 执行超时（秒）
    TOOL_TIMEOUT = 30.0

    def __init__(self):
        self.llm = LLMClient()
        self._memory_service = None
        # 工具调用缓存：同 (tool_name, args) 不重复执行，节省时间和 token
        self._tool_cache: Dict[str, dict] = {}

    async def close(self):
        """显式关闭 HTTP 客户端，避免资源泄漏"""
        await self.llm.aclose()

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
        logger.info(
            "Agent chat start: model=%s, tool_count=%d, history_len=%d",
            self.llm.model, len(tool_schemas), len(full_messages),
        )
        for round_num in range(self.MAX_TOOL_ROUNDS):
            logger.info("Agent round %d begin", round_num + 1)
            kwargs = {
                "messages": full_messages,
            }
            if tool_schemas:
                kwargs["tools"] = tool_schemas

            # 用 LLMClient.chat_stream 调用（含重试 + streaming 解析）
            try:
                if stream:
                    assistant_message, text_content = await self.llm.chat_stream(**kwargs)
                else:
                    assistant_message, text_content = await self.llm.chat_async(**kwargs)
            except Exception as e:
                logger.exception("AI chat failed after 10 attempts")
                yield {"type": EVENT_ERROR, "data": str(e)}
                return

            # 文本回落：模型可能不支持 function calling，把工具调用意图以 JSON 形式写在文本里
            # 如果没有拿到 tool_calls 字段但文本里能解析出 JSON 工具调用，照样识别
            if not assistant_message.get("tool_calls") and text_content:
                parsed = self._try_parse_text_tool_call(text_content)
                if parsed:
                    assistant_message["tool_calls"] = parsed
                    logger.info(
                        "Parsed %d tool call(s) from text content (model may lack function calling support)",
                        len(parsed),
                    )

            # 如果有文本内容，区分 thinking 和最终回答
            if text_content:
                if assistant_message.get("tool_calls"):
                    # 工具调用之前的文本视为思考过程，多次 thinking 用分隔线区分
                    prefix = "\n\n---\n\n" if round_num > 0 else ""
                    yield {"type": EVENT_THINKING, "data": prefix + text_content, "round": round_num + 1}
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
                            "args": self.llm.safe_json_loads(tc["function"]["arguments"]),
                        },
                        "round": round_num + 1,
                    }

                # 执行所有 tool_calls（带去重缓存 + 收尾提醒）
                for tc in assistant_message["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    tool_args = self.llm.safe_json_loads(tc["function"]["arguments"])

                    # 剔除 schema 未声明的字段：模型常会塞一些工具不认的 key
                    # （如 search_code 的 file_pattern 旧版），如果不剔除，同语义不同
                    # 噪声字段会导致缓存 miss、重复执行。
                    declared = self._get_declared_tool_props(tool_name)
                    if declared is not None:
                        filtered_args = {k: v for k, v in tool_args.items() if k in declared}
                    else:
                        filtered_args = tool_args

                    # 去重：缓存 key 只按 handler 真正使用的字段计算
                    cache_key = f"{tool_name}::{json.dumps(filtered_args, sort_keys=True, ensure_ascii=False)}"
                    if cache_key in self._tool_cache:
                        result = self._tool_cache[cache_key]
                        logger.info("Agent tool %s cache hit (filtered args=%s)", tool_name, filtered_args)
                    else:
                        logger.info("Agent executing tool: %s args=%s", tool_name, filtered_args)
                        result = await tool_registry.execute_tool(tool_name, filtered_args)
                        self._tool_cache[cache_key] = result
                        logger.info("Agent tool %s done, result keys=%s", tool_name, list(result.keys()) if isinstance(result, dict) else type(result).__name__)

                    # 发出 tool_result 事件
                    yield {"type": EVENT_TOOL_RESULT, "data": {"name": tool_name, "result": result}, "round": round_num + 1}

                    # 将 tool 结果加入消息列表
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })

                # 接近预算上限时，下一轮插入收尾提醒，让模型强制收敛
                remaining = self.MAX_TOOL_ROUNDS - (round_num + 1)
                if remaining == self.WRAP_UP_REMAINING_ROUNDS:
                    full_messages.append({
                        "role": "system",
                        "content": (
                            f"⚠️ 还剩 {remaining} 轮迭代预算。立即停止读取新代码，"
                            "基于已有信息给出最终回答；如果确实缺关键信息，"
                            "用 1 次精准 search_code + 1 次 read_local_code 拿到即可。"
                        ),
                    })
                    logger.warning("Agent wrap-up reminder injected (remaining=%d)", remaining)

                # 继续下一轮循环
                continue

            # 没有 tool_calls，对话结束
            # 自动存储新知识
            if text_content:
                self._auto_remember(messages, text_content)

            yield {"type": EVENT_DONE, "data": None}
            return

        # 超过最大轮次——强制收尾：调用一次模型让它在没有 tools 的情况下给最终回答
        logger.warning("Agent exceeded MAX_TOOL_ROUNDS=%d, forcing final answer", self.MAX_TOOL_ROUNDS)
        try:
            kwargs_final = {
                "messages": full_messages + [{
                    "role": "system",
                    "content": (
                        f"⚠️ 已用尽 {self.MAX_TOOL_ROUNDS} 轮工具调用预算。"
                        "现在不允许再调用工具，立即基于已收集的所有信息给出最终回答。"
                    ),
                }],
            }
            _, final_text = await self.llm.chat_stream(**kwargs_final)
            if final_text:
                yield {"type": EVENT_TOKEN, "data": final_text}
                self._auto_remember(messages, final_text)
        except Exception as e:
            logger.exception("Failed to force final answer after max rounds")
            yield {"type": EVENT_ERROR, "data": f"工具调用超限且收尾失败: {e}"}

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

        # 注入当前日期时间（UTC），让 AI 能正确计算"最近 N 天"等时间范围
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        time_context = (
            f"\n\n## 当前时间\n当前 UTC 时间：{now_utc.strftime('%Y-%m-%d %H:%M:%S')}。\n"
            f"用户问题中的时间范围（如'最近 N 天'）请以这个日期为基准计算。\n"
            f"搜索时优先使用工具的 days_back 参数指定时间范围，而不是依赖默认值。"
        )

        # 构建已配置仓库列表，让 AI 知道它能操作哪些项目
        configured_repos = list(Config.REPOS.keys())
        repo_list_text = ""
        if configured_repos:
            repo_names = "、".join(configured_repos)
            repo_list_text = f"\n\n## 已配置的代码仓库\n当前支持的项目：{repo_names}。GitHub 搜索工具（search_issues 等）可搜索任意 GitHub 仓库，不受此限制。"

        system_prompt = f"""你是一个 vLLM 技术领域的 AI 助手，帮助贡献者分析 issue/PR、搜索技术资料、搜索互联网新闻、生成报告。

## 工作原则
1. 使用工具获取最新信息，不要编造数据
2. 引用来源时注明 issue/PR 编号或论文标题
3. 搜索时优先用英文关键词（GitHub/arXiv/Web 搜索效果更好）
4. 中文回答，技术术语保留英文
5. 不确定的内容不要编造，说明"需要进一步确认"
6. 你可以同时调用多个工具来提高效率
7. **完全依赖工具返回的数据**，不要根据自己的记忆判断 PR/Issue 的合并状态或内容。工具返回结果的 merged 字段比 state 字段更能准确反映 PR 是否被合并。{time_context}

## 可用工具
你可以在对话中调用工具搜索 GitHub、arXiv、互联网、本地代码库和知识库。
当需要获取最新信息时，主动使用工具，尤其是：
- **search_web**：搜索互联网上的行业新闻、技术文章、博客等
- **extract_web_content**：从 URL 提取清洁的正文内容（当搜索结果需要深入阅读时调用）
- **search_issues**：搜索 GitHub issue/PR
- **search_arxiv**：搜索学术论文

## 工具调用格式
优先使用 function calling（如果模型支持）。如果不支持，请在文本中输出如下 JSON 表达工具调用：
```json
{{"name": "<tool_name>", "arguments": {{...}}}}
```
收到工具返回结果后请继续推理，不要在最终回答里重复工具调用 JSON。

## 高效读取代码（重要）
读取本地代码有 **总轮次预算**（默认 30 轮），过度读取会被强制收尾。请遵循：
- 先用 `search_code` 搜索关键词/类名/函数名定位关键行号（可用 `file_pattern` 限定目录前缀，如 `vllm/v1/metrics/`）
- 再用 `read_local_code` 精准读取：`file_path` 必填，`repo` 默认 'vllm'，`start_line` 0-based（含），`max_lines` 默认 100、上限 1500
- 大文件分**不重叠**的连续区间读：上一段结束行 = 下一段 `start_line`，避免重叠浪费
- 拿到关键信息后**立即给最终回答**，不要无限读文件
- 不要对同一文件同一区间重复调用（已自动去重）
- **工具返回 `error` 字段就说明该路径/参数不存在或失败，不要再用相同参数重试；调整 `file_path` / `keyword` / `repo` 后再试**{repo_list_text}{memory_context}"""

        if custom_prompt:
            system_prompt = f"{custom_prompt}\n\n{system_prompt}"

        return system_prompt

    def _last_user_message(self, messages: List[dict]) -> str:
        """获取最后一条用户消息"""
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")[:200]
        return ""

    @staticmethod
    def _get_declared_tool_props(tool_name: str):
        """从 tool schema 里取出声明的属性名集合。

        用来在执行/缓存前剔除模型塞进来的 schema 外字段，避免同语义不同噪声
        key 导致缓存 miss、重复执行。
        """
        from app.services.tools._shared import get_declared_tool_props
        return get_declared_tool_props(tool_name)

    def _try_parse_text_tool_call(self, text: str) -> Optional[List[dict]]:
        """从模型输出文本中解析 tool call（用于不支持 function calling 的模型）。

        部分模型（如某些国产模型的 coding API 代理）会忽略 OpenAI 的 ``tools``
        字段，把调用工具的意图以 JSON 形式写在 ``content`` 里。本方法扫描
        文本中的 JSON 对象，按 OpenAI function calling schema 还原成 ``tool_calls``。

        支持格式：
        1. JSON 代码块：```json\\n{"name": "...", "arguments": {...}}\\n```
        2. 行内 JSON：{"name": "...", "arguments": {...}}
        3. 字段名兼容：``name`` / ``function`` / ``tool``；``arguments`` / ``args`` / ``parameters``

        Returns:
            解析成功返回 OpenAI 格式 tool_call 列表；解析失败返回 ``None``
        """
        if not text:
            return None

        candidates: List[str] = []

        # 候选 1：JSON 代码块
        code_block_pattern = re.compile(
            r"```(?:json)?\s*\n?\s*(\{.*?\})\s*\n?\s*```",
            re.DOTALL,
        )
        for m in code_block_pattern.finditer(text):
            candidates.append(m.group(1))

        # 候选 2：行内 JSON（用括号匹配处理嵌套对象）
        for raw_obj in self._iter_top_level_json(text):
            candidates.append(raw_obj)

        for raw in candidates:
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            name = obj.get("name") or obj.get("function") or obj.get("tool")
            if not isinstance(name, str) or not name:
                continue

            # 必须是已注册的工具，防止把模型回答里偶然出现的 JSON 误判成 tool_call
            if tool_registry.get_tool(name) is None:
                continue

            args = obj.get("arguments")
            if args is None:
                args = obj.get("args") or obj.get("parameters") or {}
            if isinstance(args, str):
                args = self.llm.safe_json_loads(args)
            if not isinstance(args, dict):
                args = {}

            return [{
                "id": f"call_{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }]

        return None

    @staticmethod
    def _iter_top_level_json(text: str):
        """遍历文本中所有顶层 JSON 对象（按括号匹配处理嵌套 {}）。

        只在对象的顶层 key 包含 ``"name"`` / ``"function"`` / ``"tool"`` 时 yield，
        避免无意义的 JSON 片段。
        """
        i = 0
        n = len(text)
        while i < n:
            if text[i] != "{":
                i += 1
                continue
            depth = 0
            j = i
            in_str = False
            esc = False
            while j < n:
                c = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                else:
                    if c == '"':
                        in_str = True
                    elif c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            j += 1
                            break
                j += 1
            if depth == 0 and j > i + 1:
                snippet = text[i:j]
                # 顶层 key 必须是 name/function/tool 之一
                if re.search(r'"(?:name|function|tool)"\s*:', snippet):
                    yield snippet
            i = j if j > i else i + 1

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
                content=f"## 用户问题\n{user_msg}\n\n## AI 回答\n{response_content}",
                source_type="conversation",
                tags=["auto", "conversation"],
            )