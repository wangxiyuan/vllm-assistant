# 前端 AI 功能 → API → 后端类 → Tool 调用映射表

> 基于 `vllm-assistant` 代码库重构后状态整理（2026-08-03）

---

## 后端类层次

```
BaseAgent (基类) — 公共能力: 记忆注入, 工具缓存, 参数过滤, 时间/仓库上下文构建
  ├── AgentRunner — 流式对话引擎, 30轮 tool 循环, 自动记忆存储
  └── IntelligenceReportGenerator — 洞察报告生成, 10轮分阶段引导, fallback 单次模式

独立类 (无 Agent 循环, 直接 LLM 调用或数据操作):
  AIAssistant — 轻量 LLM 调用 (review/summarize/translate/suggest-labels), 结果缓存
  TaskDedupChecker — 依赖 AIAssistant.llm 做语义对比
  MemoryService — 知识库 CRUD + FTS5 检索 + 种子数据构建
```

---

## 完整映射表

| 前端功能 | 前端页面 | API 端点 | 后端类 | 继承 | Tool 白名单 |
|---------|---------|---------|-------|------|------------|
| AI 对话 | `/ai-agent` | `POST /api/ai-agent/chat` (SSE) | **AgentRunner** | extends BaseAgent | 8 个 (github×4 + knowledge×2 + code×2) |
| 生成洞察报告 | `/intelligence` | `POST /api/intelligence/reports/generate` | **IntelligenceReportGenerator** | extends BaseAgent | 11 个 |
| 触发每日报告 | `/intelligence` | `POST /api/intelligence/reports/daily/trigger` | scheduler → **IntelligenceReportGenerator** | extends BaseAgent | 同上 11 个 |
| PR Review | `/pr-center` / `/community` | `POST /api/ai-assistant/generate-review` | **AIAssistant** | 独立类 | 无 |
| AI 摘要 | `/pr-center` / `/community` | `POST /api/ai-assistant/summarize` | **AIAssistant** | 独立类 | 无 |
| AI 翻译 | `/pr-center` / `/community` | `POST /api/ai-assistant/translate` | **AIAssistant** | 独立类 | 无 |
| 标签建议 | `/community` | `POST /api/ai-assistant/suggest-labels` | **AIAssistant** | 独立类 | 无 |
| 影响分析 | `/pr-center` | `POST /api/ai-assistant/analyze-impact` | **AIAssistant** | 独立类 | 无 |
| 任务去重 | `/personal-todo` | `POST /api/personal-todo/tasks/{id}/dedup-check` | **TaskDedupChecker** | 独立类 | 无 |
| 知识库 CRUD | `/ai-agent` | `GET` `POST` `DELETE` `/api/ai-agent/memories` | **MemoryService** | 独立类 | 无 |
| 知识库重建 | `/ai-agent` | `POST /api/ai-agent/memories/build` | **MemoryService** | 独立类 | 无 |

---

## 12 个 Tool 注册表

> **AgentRunner** 默认场景（前端传 `tools: ['github', 'knowledge', 'code']`）可用下表中 **加粗的 8 个**；前端传 `tools=None` 时可用全部 12 个。
> **IntelligenceReportGenerator** 固定白名单 11 个（不含 `search_by_tags`）。因为报告场景需要的是全文检索（`search_memory`），标签浏览（`search_by_tags`）不适用。前端勾选的"数据来源"控制的是调研范围（GitHub 仓库/学术/新闻/Slack），不影响工具白名单。

| 工具名 | 类别 | 数据源 | AgentRunner | IntelligenceReport |
|--------|------|--------|:-----------:|:-----------------:|
| **`search_issues`** | github | GitHub REST API | ✅ | ✅ |
| **`get_issue_detail`** | github | GitHub REST API | ✅ | ✅ |
| **`get_pr_diff`** | github | GitHub REST API | ✅ | ✅ |
| **`get_github_releases`** | github | GitHub REST API | ✅ | ✅ |
| **`search_memory`** | knowledge | 本地 SQLite (ai_memory_fts) | ✅ | ✅ |
| `search_by_tags` | knowledge | 本地 SQLite | ✅ | ❌ |
| **`read_local_code`** | code | 本地 SQLite (LocalCodeCache) | ✅ | ✅ |
| **`search_code`** | code | 本地 SQLite (LocalCodeCache) | ✅ | ✅ |
| `search_docs` | doc | 本地 SQLite (LocalCodeCache) | ✅ | ✅ |
| `search_arxiv` | academic | arXiv API | ✅ | ✅ |
| `search_web` | web | Tavily API | ✅ | ✅ |
| `extract_web_content` | web | Jina AI / Firecrawl | ✅ | ✅ |