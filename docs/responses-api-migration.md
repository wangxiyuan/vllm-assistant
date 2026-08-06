# Responses API 迁移设计方案

## 目录

- [1. 现状分析](#1-现状分析)
- [2. 目标与范围](#2-目标与范围)
- [3. 架构设计](#3-架构设计)
- [4. Phase 1: 依赖升级与前置验证](#4-phase-1-依赖升级与前置验证)
- [5. Phase 2: 工具 Schema 适配层](#5-phase-2-工具-schema-适配层)
- [6. Phase 3: LLMClient 新增 Responses API 方法](#6-phase-3-llmclient-新增-responses-api-方法)
- [7. Phase 4: AgentRunner 改造](#7-phase-4-agentrunner-改造)
- [8. Phase 5: IntelligenceReportGenerator 改造（可选）](#8-phase-5-intelligencereportgenerator-改造可选)
- [9. Phase 6: API 层适配](#9-phase-6-api-层适配)
- [10. Phase 7: 数据库 Schema 变更](#10-phase-7-数据库-schema-变更)
- [11. Phase 8: 前端适配](#11-phase-8-前端适配)
- [12. 风险与回退策略](#12-风险与回退策略)
- [13. 改动文件清单](#13-改动文件清单)
- [14. 附录：Responses API 与 Chat Completions API 差异对比](#14-附录responses-api-与-chat-completions-api-差异对比)

---

## 1. 现状分析

### 1.1 当前架构

```
┌──────────────────────────────────────────────────────────────┐
│  app/api/ai_agent.py                                         │
│  POST /chat → StreamingResponse(event_stream)                │
│  SSE 协议: token / thinking / tool_call / tool_result / done │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│  app/services/agent_runner.py                                │
│  AgentRunner.chat() → 30 轮 tool 循环                        │
│  每次传完整 full_messages 列表                                │
│  call: self.llm.chat_stream() / chat_async()                 │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│  app/services/llm.py                                         │
│  LLMClient: wraps OpenAI SDK                                 │
│  - chat_sync()   → sync chat.completions.create()            │
│  - chat_async()  → async chat.completions.create()           │
│  - chat_stream() → async chat.completions.create(stream=True)│
│    └─ _handle_streaming_response() → 缓冲整段后一次性返回    │
│  - retry/backoff, safe_json_loads, parse_retry_after         │
└──────────────┬───────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────┐
│  openai SDK 1.59.7                                           │
│  → 仅有 chat.completions.create()                            │
│  → 无 client.responses 或 client.beta.responses              │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 关键问题

| 问题 | 描述 | 严重程度 |
|------|------|----------|
| **伪流式** | `chat_stream()` → `_handle_streaming_response()` 缓冲整个响应后一次性返回 token 事件 | 高 |
| **重复传历史** | 每轮 tool 循环都传完整 `full_messages`，包含已传过的历史，token 浪费 | 中 |
| **SDK 版本过旧** | `openai==1.59.7` 无 `client.responses` 支持 | 阻塞 |
| **参数名不兼容** | Responses API 用 `max_output_tokens` 而非 `max_tokens` | 需适配 |
| **工具格式不兼容** | Chat Completions 格式 `{"type":"function","function":{...}}` 需展平 | 需适配 |

### 1.3 不迁移的部分

`AIAssistant`（`app/services/ai_assistant.py`）的 review/summarize/translate 保持 Chat Completions API，不做改动。

---

## 2. 目标与范围

### 2.1 目标

1. **Agent 交互**（`AgentRunner.chat`）切换到 Responses API，实现真逐 token 流式输出
2. **智能报告生成**（`IntelligenceReportGenerator._agent_loop`）切换到 Responses API（非流式，后台任务）
3. **`AIAssistant`** 保持 Chat Completions API 不变
4. **前端 SSE 协议**尽量不变，感知到的是 token 事件更细粒度到达

### 2.2 非目标

- 不迁移 `AIAssistant`（review/summarize/translate）
- 不改动现有工具注册表（`app/services/tools/*.py`）
- 不改动前端 SSE 事件协议（`token`/`thinking`/`tool_call`/`tool_result`/`done`/`error`）
- 不改动 `AIChatMessage` 表结构

---

## 3. 架构设计

### 3.1 核心架构

```
AgentRunner.chat()  (保留 30 轮循环框架)
  │
  ├─ 第 N 轮: LLMClient.responses_stream_single(input, tools, instructions, prev_id?)
  │    │  (单个 responses.create(stream=True)，返回事件流 + 元数据)
  │    │
  │    ├─ event: response.output_text.delta -> yield {"type":"token","data":delta}  ← 真增量
  │    ├─ event: response.function_call_arguments.done -> 收集 function_call
  │    ├─ event: response.completed -> 记录 response_id (用于 prev_id 链)
  │    └─ event: response.failed/incomplete -> yield error / 降级
  │
  ├─ if 有 function_calls:
  │    for tc in function_calls:
  │      result = execute_tool_cached(...)    ← 保留现有缓存逻辑
  │      input += [{"type":"function_call_output","call_id":……,"output":json(result)}]
  │    continue  ← 进入下一轮 responses.create
  │
  └─ else: yield done
```

### 3.2 Tier A / Tier B 双轨策略

兼容服务对 `previous_response_id` 的支持不确定，采用双轨设计：

| 轨道 | 条件 | 行为 | 收益 |
|------|------|------|------|
| **Tier A** | 服务支持 `store=true` + `previous_response_id` | 首次传完整 `input`，后续只传新 user message + `previous_response_id` | 节省对话历史 token |
| **Tier B** | 服务不支持 / 未确认 | 每次传完整 `input`（消息历史），不传 `previous_response_id` | 兼容性最好，无状态依赖 |

**判断逻辑**：启动时探测 + 运行时异常降级。探测脚本见 [4.1 节](#41-兼容服务探测)。

### 3.3 真流式策略

使用 **hybrid 流式策略**：中间 tool 轮次（古灵精怪）的文本缓冲后作为 `thinking` 块发送，Final 轮次（最终答案）的文本逐 token 实时推送。

**原因**：一个响应中 text delta 和 function_call 可能交错出现，流式消费时无法在 text delta 到达时预知是否会有后续 tool call。因此：

- **中间轮次**（有 tool_call）：缓冲所有 text delta，在 `response.completed` 时判断有 tool_call，一次性 emit `thinking` 事件
- **最终轮次**（无 tool_call）：缓冲所有 text delta，在 `response.completed` 时判断无 tool_call，一次性 emit `token` 事件。由于这个轮次通常是最终答案，可以在 `AgentRunner` 层把所有 text delta 按合适粒度分割后 yield 多个 `token` 事件，模拟流式效果

> **注意**：修改为"在 `response.completed` 时一次性拆分为多个 token 事件发送"——这样可以避免上游流式未知 tool_call 的复杂判断，同时前端能感知到流式效果。

---

## 4. Phase 1: 依赖升级与前置验证

### 4.1 兼容服务探测脚本

在写代码前执行，确认 Responses API 的能力集：

```python
# scripts/check_responses_api.py
"""探测兼容服务是否支持 Responses API 的 key features"""
import asyncio
from openai import AsyncOpenAI
from app.config import Config

async def check():
    client = AsyncOpenAI(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
    )

    # 1. 基础: 是否支持 responses.create
    try:
        resp = await client.responses.create(
            model=Config.OPENAI_MODEL,
            input=[{"role": "user", "content": "say hi"}],
            max_output_tokens=50,
            store=False,
        )
        print(f"[OK] responses.create  works, id={resp.id}")
    except Exception as e:
        print(f"[FAIL] responses.create not supported: {e}")
        return

    # 2. 流式支持
    try:
        stream = await client.responses.create(
            model=Config.OPENAI_MODEL,
            input=[{"role": "user", "content": "count to 3"}],
            max_output_tokens=100,
            stream=True,
            store=False,
        )
        async for event in stream:
            if event.type == "response.output_text.delta":
                print(f"[OK] streaming works, delta: {event.delta}")
                break
    except Exception as e:
        print(f"[FAIL] streaming not supported: {e}")

    # 3. store + previous_response_id
    try:
        resp1 = await client.responses.create(
            model=Config.OPENAI_MODEL,
            input=[{"role": "user", "content": "my favorite color is blue"}],
            max_output_tokens=50,
            store=True,
        )
        resp2 = await client.responses.create(
            model=Config.OPENAI_MODEL,
            input=[{"role": "user", "content": "what is my favorite color?"}],
            previous_response_id=resp1.id,
            max_output_tokens=50,
            store=True,
        )
        print(f"[OK] previous_response_id works, answer: {resp2.output_text}")
    except Exception as e:
        print(f"[WARN] previous_response_id not supported: {e}")

    # 4. function calling
    try:
        resp = await client.responses.create(
            model=Config.OPENAI_MODEL,
            input=[{"role": "user", "content": "what's the weather?"}],
            tools=[{
                "type": "function",
                "name": "get_weather",
                "description": "Get weather",
                "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
            }],
            store=False,
        )
        if resp.output and any(item.type == "function_call" for item in resp.output):
            print(f"[OK] function calling works")
    except Exception as e:
        print(f"[FAIL] function calling not supported: {e}")

    await client.close()

asyncio.run(check())
```

### 4.2 升级 openai SDK

**`requirements.txt`**: `openai==1.59.7` → `openai>=1.66.0`

**影响范围**：仅 `LLMClient` 新增方法，不影响现有 `chat.completions` 调用（`AIAssistant` 层）。

### 4.3 确定 Tier

根据探测结果：

| 结果 | 方案 |
|------|------|
| `previous_response_id` + `store` 均支持 | Tier A：启用 `previous_response_id` |
| 任一不支持 | Tier B：不传 `previous_response_id`，每次传完整 `input` |
| 运行时 `previous_response_id` 抛 400/404 | 捕获异常，降级为 Tier B，清空 `last_response_id` |

---

## 5. Phase 2: 工具 Schema 适配层

### 5.1 格式差异

```
Chat Completions:  {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
Responses API:     {"type": "function", "name": "...", "description": "...", "parameters": {...}}
```

### 5.2 改动：`app/services/tools/registry.py` 新增

```python
def get_tool_schemas_responses(names: Optional[List[str]] = None) -> List[dict]:
    """获取 Responses API 格式的工具 schema"""
    schemas = get_tool_schemas(names)  # 复用现有 Chat Completions 格式
    result = []
    for s in schemas:
        fn = s["function"]
        result.append({
            "type": "function",
            "name": fn["name"],
            "description": fn.get("description", ""),
            "parameters": fn["parameters"],
        })
    return result
```

**优势**：10+ 个工具文件（`github_tools.py` 等）**完全不改**，只在读取层做格式转换。

---

## 6. Phase 3: LLMClient 新增 Responses API 方法

### 6.1 新增方法

在 `app/services/llm.py` 的 `LLMClient` 类中新增，**保留**所有现有方法（`AIAssistant` 继续使用）。

```python
async def responses_stream_single(
    self,
    *,
    input_messages: List[dict],
    tools: List[dict],
    instructions: Optional[str] = None,
    model: Optional[str] = None,
    previous_response_id: Optional[str] = None,
    max_output_tokens: int = 1048576,
    temperature: float = 0.7,
    store: bool = True,
    **kwargs,
) -> AsyncIterator[dict]:
    """单次 Responses API 流式调用。

    返回一个事件流，每个事件是 dict，包含：
    - {"type": "token", "data": "..."}         # text delta（增量文本）
    - {"type": "tool_call_partial", ...}       # function_call_arguments delta（暂不对外暴露）
    - {"type": "tool_calls", "data": [...]}    # 该轮所有 function_call 的完整列表
    - {"type": "response_id", "data": "..."}   # 本次 response 的 ID
    - {"type": "done", "data": None}           # 正常结束
    - {"type": "error", "data": "..."}         # 异常

    Yields 事件后，调用方根据 tool_calls 决定是否发起下一轮。
    """
```

### 6.2 关键实现细节

```python
async def responses_stream_single(self, ...):
    kwargs = {
        "model": model or self.model,
        "input": input_messages,
        "tools": tools,
        "instructions": instructions,
        "max_output_tokens": min(max_output_tokens, MODEL_MAX_TOKENS_LIMIT),
        "temperature": temperature,
        "store": store,
        "stream": True,
    }
    if previous_response_id:
        kwargs["previous_response_id"] = previous_response_id

    # 冲突参数检查
    if "max_tokens" in kwargs:
        del kwargs["max_tokens"]

    for attempt in range(10):
        try:
            stream = await self._async_openai.responses.create(**kwargs)
            break
        except Exception as e:
            if attempt < 9:
                wait = ...  # 复用现有 parse_retry_after + 指数退避
                await asyncio.sleep(wait)
            else:
                yield {"type": "error", "data": str(e)}
                return

    text_buffer = []
    tool_calls = []

    async for event in stream:
        if event.type == "response.output_text.delta":
            text_buffer.append(event.delta)
            yield {"type": "token", "data": event.delta}

        elif event.type == "response.function_call_arguments.delta":
            # 累积 function_call 参数
            ...

        elif event.type == "response.function_call_arguments.done":
            # 解析完整 function_call
            tool_calls.append({
                "call_id": event.call_id,
                "name": event.name,
                "arguments": event.arguments,
            })

        elif event.type == "response.completed":
            yield {"type": "response_id", "data": event.response.id}
            if tool_calls:
                yield {"type": "tool_calls", "data": tool_calls}
            yield {"type": "done", "data": None}

        elif event.type == "response.failed":
            yield {"type": "error", "data": f"Response failed: {event.error}"}

        elif event.type == "response.incomplete":
            yield {"type": "error", "data": "Response incomplete (context limit reached)"}
```

### 6.3 参数名映射

| Chat Completions | Responses API | 备注 |
|-----------------|---------------|------|
| `messages` | `input` | 格式不同 |
| `max_tokens` | `max_output_tokens` | 参数名不同 |
| `temperature` | `temperature` | 相同 |
| `tools` | `tools` | 但格式不同 |
| `top_p` | `top_p` | 相同 |
| `stream` | `stream` | 相同 |
| `model` | `model` | 相同，但类型不同 |
| `timeout` | `timeout` | 相同 |

---

## 7. Phase 4: AgentRunner 改造

### 7.1 核心改动

`app/services/agent_runner.py` 的 `chat()` 方法核心逻辑重写，保留外部接口签名：

```python
async def chat(
    self,
    messages: List[dict],
    tools: Optional[List[str]] = None,
    stream: bool = True,
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AsyncIterator[dict]:
```

### 7.2 改造后流程

```python
async def chat(self, messages, tools, stream, system_prompt, session_id):
    system = self._build_system_prompt(messages, system_prompt)
    tool_schemas = self._get_tool_schemas(tools)  # 改用 get_tool_schemas_responses

    # 构造 input（根据 Tier A/B）
    use_prev_id = bool(session_id) and self._should_use_prev_id(session_id, messages)
    if use_prev_id:
        # Tier A: 只传最后一条 user message
        last_user = self._last_message(messages, role="user")
        input_messages = [{"role": "user", "content": last_user}]
        prev_id = self._get_saved_response_id(session_id)
    else:
        # Tier B: 传完整消息历史
        input_messages = [{"role": "system", "content": system}]
        for m in messages:
            if m.get("role") != "system":
                input_messages.append({"role": m["role"], "content": m["content"]})
        prev_id = None
        system = None  # instructions 已合并到 input

    for round_num in range(self.MAX_TOOL_ROUNDS):
        # 收尾提醒
        if self.MAX_TOOL_ROUNDS - (round_num + 1) == self.WRAP_UP_REMAINING_ROUNDS:
            input_messages.append({"role": "system", "content": "..."})

        events = self.llm.responses_stream_single(
            input_messages=input_messages,
            tools=tool_schemas,
            instructions=system if not use_prev_id else self._get_instructions(session_id, messages, system_prompt),
            previous_response_id=prev_id,
        )

        text_buffer = []
        async for event in events:
            if event["type"] == "token":
                text_buffer.append(event["data"])

            elif event["type"] == "tool_calls":
                # 本轮有 tool calls → 执行
                text_content = "".join(text_buffer)
                if text_content:
                    yield {"type": EVENT_THINKING, "data": text_content, "round": round_num + 1}

                for tc in event["data"]:
                    yield {"type": EVENT_TOOL_CALL, ...}
                    result = await self.execute_tool_cached(tc["name"], ...)
                    yield {"type": EVENT_TOOL_RESULT, ...}
                    input_messages.append({"type": "function_call_output", "call_id": tc["call_id"], "output": json.dumps(result)})

                prev_id = await self._save_response_id(session_id, ...)
                break  # 进入下一轮

            elif event["type"] == "response_id":
                prev_id = event["data"]
                await self._save_response_id(session_id, prev_id)

            elif event["type"] == "done":
                # 无 tool calls → 最终回答
                text_content = "".join(text_buffer)
                yield {"type": EVENT_TOKEN, "data": text_content}
                self._auto_remember(messages, text_content, session_id)
                yield {"type": EVENT_DONE, "data": None}
                return

            elif event["type"] == "error":
                yield {"type": EVENT_ERROR, "data": event["data"]}
                yield {"type": EVENT_DONE, "data": None}
                return
```

### 7.3 保留的逻辑（不变）

- `_build_system_prompt`（记忆注入、时间上下文、仓库列表）
- `_try_parse_text_tool_call`（文本回落）
- `execute_tool_cached`（去重缓存）
- `_auto_remember`
- `MAX_TOOL_ROUNDS` + 收尾提醒
- `_last_user_message`

### 7.4 新增方法

在 `AgentRunner` 新增：

```python
def _get_instructions(self, session_id, messages, custom_prompt) -> str:
    """构建每轮必传的 instructions（Tier A 用）"""
    return self._build_system_prompt(messages, custom_prompt)

async def _save_response_id(self, session_id, response_id) -> None:
    """将 response_id 存入 AIChatSession.last_response_id"""
    ...

def _get_saved_response_id(self, session_id) -> Optional[str]:
    """从 AIChatSession 读取 last_response_id"""
    ...

def _should_use_prev_id(self, session_id, messages) -> bool:
    """判断是否应该使用 previous_response_id
    - 该 session 有 last_response_id
    - 消息数量与 last_response_id 对应（未触发编辑/重试）
    - 服务端未过期（通过异常捕获降级）
    """
    ...
```

### 7.5 编辑/重试场景处理

当 `_sync_and_save_user_message` 检测到消息被截断或编辑时，同时清除 `AIChatSession.last_response_id`：

```python
# 在 _sync_and_save_user_message 结尾
if "截断/编辑" 触发:
    session.last_response_id = None
```

---

## 8. Phase 5: IntelligenceReportGenerator 改造（可选）

### 8.1 改动范围

`app/services/intelligence_report.py` 的 `_agent_loop()` 方法。

### 8.2 改造要点

- `self.TOOLS` property 改用 `get_tool_schemas_responses()`
- `_agent_loop` 中的 `asyncio.run(self.llm.chat_async(...))` → 使用 `responses_stream_single`（非流式模式）
- 报告生成无需 `previous_response_id`（一次性任务），用全量 `input`
- 并行 tool 执行逻辑保留（`ThreadPoolExecutor`）
- 上下文超限截断逻辑保留，但需注意 `truncation` 参数在 Responses API 的语义不同

### 8.3 关键变更

```python
# 改前
assistant_message, text_content = asyncio.run(self.llm.chat_async(
    messages=messages,
    tools=self.TOOLS,
    max_tokens=Config.LLM_MAX_TOKENS,
    temperature=0.3,
))

# 改后
# 使用非流式 responses.create（stream=False），通过 event loop 包装
async def _call_llm(messages, tools):
    full_text = ""
    async for event in self.llm.responses_stream_single(
        input_messages=messages,
        tools=tools,
        max_output_tokens=Config.LLM_MAX_TOKENS,
        temperature=0.3,
    ):
        if event["type"] == "token":
            full_text += event["data"]
        elif event["type"] == "tool_calls":
            # 处理 tool_calls（和改前一样）
            ...
        elif event["type"] == "done":
            return full_text
    return full_text

result = asyncio.run(_call_llm(messages, self.TOOLS))
```

---

## 9. Phase 6: API 层适配

### 9.1 改动范围

`app/api/ai_agent.py` 的 `chat()` 端点和 `ChatRequest` 模型。

### 9.2 ChatRequest 改动

```python
class ChatRequest(BaseModel):
    messages: List[dict]
    session_id: Optional[str] = None
    tools: Optional[List[str]] = None
    stream: bool = True
    system_prompt: Optional[str] = None
    # 新增（可选，后端也可自动从 session 读取）
    previous_response_id: Optional[str] = None
```

### 9.3 event_stream 改动

`event_stream()` 内部调用从 `runner.chat()` 不变（接口签名保持）。SSE 事件协议**保持不变**（`token`/`thinking`/`tool_call`/`tool_result`/`done`/`error`）。

**唯一行为变化**：
- `token` 事件现在是真增量（每次几十字符），而非整段
- 前端 `streamingFinal.value += event.data` 逻辑无需修改，只是更新更频繁

### 9.4 session last_response_id 管理

在 `_sync_and_save_user_message` 和 `_save_assistant_message` 中增加 `last_response_id` 的读写逻辑：

```python
# 在 _sync_and_save_user_message 中
def _sync_and_save_user_message(session_id: str, messages: List[dict]):
    # ... 现有逻辑 ...
    # 如果触发了消息截断/编辑，清空 last_response_id
    session = db.query(AIChatSession).filter(AIChatSession.id == session_id).first()
    if session and session.last_response_id is not None:
        if "截断逻辑" 触发:
            session.last_response_id = None
```

---

## 10. Phase 7: 数据库 Schema 变更

### 10.1 变更内容

`AIChatSession` 表增加一列，用于存储 `previous_response_id` 链的最后一个 response ID。

```python
# app/models.py - AIChatSession
class AIChatSession(Base):
    __tablename__ = "ai_chat_sessions"

    id = Column(String(36), primary_key=True)
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    message_count = Column(Integer, default=0)
    last_response_id = Column(String(128), nullable=True)  # 新增
```

### 10.2 向后兼容策略

- `nullable=True`，旧数据为 NULL，不影响现有实例
- 旧 session 没有 `last_response_id` 时，自动走 Tier B（全量消息模式）
- `AIChatMessage` 表**保持不变**（仍用于历史展示和 DB 持久化）

### 10.3 迁移脚本

沿用项目现有的 `_ensure_*` 模式（`app/database.py` 中已有多个类似例子）：

```python
def _ensure_ai_chat_sessions_response_id():
    """确保 ai_chat_sessions 表包含 last_response_id 列"""
    from sqlalchemy import inspect, DDL
    with engine.connect() as conn:
        try:
            existing_cols = {c["name"] for c in inspect(conn).get_columns("ai_chat_sessions")}
        except Exception:
            return
        if "last_response_id" not in existing_cols:
            conn.execute(DDL("ALTER TABLE ai_chat_sessions ADD COLUMN last_response_id VARCHAR(128)"))
            conn.commit()
```

---

## 11. Phase 8: 前端适配

### 11.1 改动范围

`frontend/src/stores/aiAgent.ts`。

### 11.2 建议改动

前端**无需强制改动**即可工作。可选优化：

```typescript
// 1. IDLE_TIMEOUT_MS 可缩短
// 真流式下 token 持续到达，idle 检测更准确
const IDLE_TIMEOUT_MS = 45_000;  // 从 90_000 缩短

// 2. 可增加 thinking 事件与 token 事件的更细粒度区分展示
// 在 streamingSteps 中增加 thinking 类型
```

---

## 12. 风险与回退策略

### 12.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 兼容服务不支持 Responses API | 中 | 高 | Phase 1 探测脚本在部署前验证；不支持则放弃迁移 |
| 兼容服务 `previous_response_id` 不稳定 | 中 | 中 | Tier B 回退，不传 `previous_response_id` |
| 升级 openai SDK 影响现有 `AIAssistant` | 低 | 低 | SDK 向后兼容 `chat.completions`，`AIAssistant` 代码不动 |
| 生产数据库 ALTER 失败 | 低 | 低 | SQLite ADD COLUMN 是安全操作；备份数据库后再部署 |
| Responses API 流式事件类型与官方文档不一致 | 中 | 中 | 先用探测脚本验证事件类型，必要时调整 `_handle_stream_events` |

### 12.2 回退策略

1. **代码回退**：`git revert` 或 `deploy.sh` 用旧镜像
2. **功能降级**：如果 `previous_response_id` 失效，自动降级为 Tier B，无需停机
3. **完全回退**：如果 Responses API 整体不可用，保留 `chat_stream` / `chat_async` 方法，`AgentRunner` 通过配置开关（`USE_RESPONSES_API` env var）切换回 Chat Completions

---

## 13. 改动文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `requirements.txt` | 修改 | `openai==1.59.7` → `openai>=1.66.0` |
| `app/models.py` | 修改 | `AIChatSession` 加 `last_response_id` 列 |
| `app/database.py` | 修改 | 新增 `_ensure_ai_chat_sessions_response_id()` 迁移函数 |
| `app/config.py` | 可选 | 新增 `USE_RESPONSES_API` 环境变量开关 |
| `app/services/llm.py` | 修改 | 新增 `responses_stream_single()` 方法，保留旧方法 |
| `app/services/tools/registry.py` | 修改 | 新增 `get_tool_schemas_responses()` |
| `app/services/agent_runner.py` | 修改 | 重写 `chat()` 方法核心逻辑 |
| `app/services/intelligence_report.py` | 可选 | `_agent_loop` 改用 Responses API |
| `app/api/ai_agent.py` | 修改 | `ChatRequest` 加字段，session 读写 `last_response_id` |
| `frontend/src/stores/aiAgent.ts` | 可选 | `IDLE_TIMEOUT_MS` 缩短 |
| `scripts/check_responses_api.py` | 新增 | 探测脚本（不提交到生产） |

**不改动的文件**：
- 所有 `app/services/tools/*.py`（工具定义）
- `app/services/ai_assistant.py`（review/summarize/translate）
- `app/services/base_agent.py`（公共基类核心逻辑不变）
- `app/services/_shared.py`
- 所有前端组件文件（`.vue`）

---

## 14. 附录：Responses API 与 Chat Completions API 差异对比

### 14.1 参数映射

| Chat Completions | Responses API | 类型 | 差异 |
|-----------------|---------------|------|------|
| `messages` | `input` | 必填 | 格式不同：Responses 支持 `message` / `function_call_output` / `item_reference` 等类型 |
| `model` | `model` | 必填 | 相同，但 Responses API 有更严格的模型版本要求 |
| N/A | `instructions` | 可选 | 等效于 system message，但不会随 `previous_response_id` 传到下一轮 |
| `max_tokens` | `max_output_tokens` | 可选 | **参数名不同** |
| `temperature` | `temperature` | 可选 | 相同 |
| `tools` | `tools` | 可选 | 格式不同。Function tools 不再嵌套 `function` 键 |
| `tool_choice` | `tool_choice` | 可选 | 相同语义 |
| `stream` | `stream` | 可选 | 相同 |
| `stop` | `stop` | 可选 | 相同 |
| `top_p` | `top_p` | 可选 | 相同 |
| N/A | `previous_response_id` | 可选 | 新增。用于服务端状态管理 |
| N/A | `store` | 可选 | 新增。控制是否持久化 response |
| N/A | `truncation` | 可选 | 新增。`auto` / `disabled`，控制上下文超限时的策略 |
| `max_tokens` | `max_tool_calls` | 可选 | 新增。控制内置工具的最大调用次数 |
| `user` | `user` | 可选 | 相同，但 Responses API 推荐用 `prompt_cache_key` / `safety_identifier` |

### 14.2 流式事件类型对比

| Chat Completions 流式事件 | Responses API 流式事件 | 说明 |
|----------------------|------------------------|------|
| `choices[0].delta.content` | `response.output_text.delta` | 文本增量 |
| `choices[0].delta.tool_calls` | `response.function_call_arguments.delta` | 工具调用参数增量 |
| `choices[0].finish_reason` | `response.completed` + `response.failed` + `response.incomplete` | 完成状态 |
| N/A | `response.output_item.added` | 输出项开始（text / function_call） |
| N/A | `response.output_item.done` | 输出项完成 |
| N/A | `response.function_call_arguments.done` | 工具调用参数完整就绪 |
| N/A | `response.output_text.done` | 文本段完成 |
| N/A | `response.created` / `response.in_progress` | 生命周期事件 |

### 14.3 工具调用格式对比

```python
# Chat Completions - 工具定义
{
    "type": "function",
    "function": {
        "name": "search_issues",
        "description": "...",
        "parameters": {...}
    }
}

# Responses API - 工具定义
{
    "type": "function",
    "name": "search_issues",
    "description": "...",
    "parameters": {...}
}
```

```python
# Chat Completions - 模型返回的 tool_call
{
    "role": "assistant",
    "content": None,
    "tool_calls": [{
        "id": "call_xxx",
        "type": "function",
        "function": {"name": "search_issues", "arguments": "{\"repo\":\"vllm-project/vllm\"}"}
    }]
}

# Responses API - 模型返回的 function_call output item
{
    "type": "function_call",
    "call_id": "call_xxx",
    "name": "search_issues",
    "arguments": "{\"repo\":\"vllm-project/vllm\"}"
}
```

```python
# Chat Completions - 工具结果
{
    "role": "tool",
    "tool_call_id": "call_xxx",
    "content": "{\"results\": [...]}"
}

# Responses API - 工具结果
{
    "type": "function_call_output",
    "call_id": "call_xxx",
    "output": "{\"results\": [...]}"
}
```

### 14.4 `previous_response_id` 流程图

```
Tier A 模式（启用 previous_response_id）
─────────────────────────────────────────

第 1 轮（用户新消息）：
  Client → responses.create(input=[{"role":"user","content":"..."}], store=True)
  Server → 存储 response，返回 response_id_1
  Client → 保存 response_id_1 到 AIChatSession.last_response_id

第 1 轮 + 工具执行：
  if 有 function_call:
    Client → 执行工具
    Client → responses.create(input=[function_call_output], previous_response_id=response_id_1, store=True)
    Server → 追加到同一 conversation，返回 response_id_2
    Client → 更新 last_response_id = response_id_2
    ...

第 2 轮（用户新消息）：
  Client → 读取 last_response_id = response_id_N
  Client → responses.create(input=[{"role":"user","content":"新消息"}], previous_response_id=response_id_N, store=True)
  Server → 在 conversation 后追加新消息，返回 response_id_N+1
  Client → 更新 last_response_id = response_id_N+1


Tier B 模式（不启用 previous_response_id）
─────────────────────────────────────────

每轮：
  Client → responses.create(input=[{"role":"system","content":"..."}, ...完整历史..., {"role":"user","content":"新消息"}], tools=...)
  Server → 返回 response
  Client → 丢弃 response_id（不存储）
  next 轮重复完整历史
```

---

> **文档版本**: v1.1
> **最后更新**: 2026-08-05
> **设计者**: AI Assistant
> **审查状态**: 待审查