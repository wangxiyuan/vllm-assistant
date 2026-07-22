# 个人 TODO 面板 - 设计文档

## 1. 概述

### 1.1 背景
作为 vllm-ascend 项目的 committer，在 vllm 社区中需要处理的任务来源多样：
- 自己发现的改进点
- 团队其他成员反馈的需求
- 社区用户提出的问题
- 会议纪要中记录的行动项

任务数量多且来源分散，容易遗忘或重复劳动。需要一个工具来集中管理这些任务，并能自动检查是否与已有 issue/PR 重复，同时按需生成多维度的洞察报告（vllm 社区、vllm-ascend、竞品、学术、新闻）。

### 1.2 目标
- 集中管理个人任务，支持 P0/P1/P2/P3 四级优先级分类
- 创建任务时可选触发去重检查，避免重复劳动
- 按需触发 AI Agent 生成多维度洞察报告
- 独立的情报面板，按时间倒序展示所有洞察报告
- 洞察报告与触发任务关联，便于追溯

### 1.3 非目标
- 不支持外部链接导入（Slack/Discord 消息）
- 不实现截止日期邮件/IM 通知
- 不集成日历同步
- 不需要对比功能（对比不同洞察报告）

---

## 2. 数据模型

### 2.1 PersonalTask（个人任务）

```python
class PersonalTask(Base):
    """个人任务"""
    __tablename__ = "personal_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)              # 任务标题
    description = Column(Text)                         # 详细描述

    # 来源分类
    source = Column(String(50), nullable=False)       # 'self' / 'team' / 'community' / 'meeting'

    # 优先级（P0/P1/P2/P3 四级）
    priority = Column(String(10), nullable=False, default="P2")  # P0 > P1 > P2 > P3

    # 状态
    status = Column(String(20), nullable=False, default="todo")  # todo / in_progress / done / cancelled

    # 关联外部资源
    related_issue_number = Column(Integer)             # 关联的 vllm issue 编号
    related_pr_number = Column(Integer)                # 关联的 vllm PR 编号
    related_url = Column(String(500))                 # 外部链接

    # 分类
    area = Column(String(50))                         # 领域 (engine/model/...)
    tags = Column(Text)                               # JSON array

    # 时间追踪
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    due_date = Column(Date)                           # 截止日期（可选）
    completed_at = Column(DateTime)                   # 完成时间

    # AI 辅助字段
    dedup_check_result = Column(Text)                 # JSON: 去重检查结果
```

### 2.2 TaskDedupCache（去重检查缓存）

```python
class TaskDedupCache(Base):
    """去重检查缓存，避免重复调用 API"""
    __tablename__ = "task_dedup_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("personal_tasks.id"))
    check_type = Column(String(20))                   # 'keyword' / 'semantic' / 'hybrid'
    matched_items = Column(Text)                      # JSON: 匹配到的 issue/PR 列表
    checked_at = Column(DateTime, nullable=False)
```

> **说明**：去重检查结果同时存储在 `PersonalTask.dedup_check_result` 中便于快速查询，此表用于历史记录和审计。

### 2.3 IntelligenceReport（洞察报告）

```python
class IntelligenceReport(Base):
    """洞察报告"""
    __tablename__ = "intelligence_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)                    # 报告标题
    content = Column(Text, nullable=False)                   # Markdown 内容

    # 关联信息
    task_id = Column(Integer, ForeignKey("personal_tasks.id"))  # 触发的任务

    # 来源范围（JSON 数组）
    # 可选值: "vllm", "vllm-ascend", "sglang", "academic", "news"
    sources = Column(Text, nullable=False)                   # JSON: ["vllm", "sglang", "academic"]

    # 排除的来源（用户选择排除某些来源时记录）
    excluded_sources = Column(Text)                         # JSON array

    # 额外提示词（用户提供的论文信息、特殊要求等）
    extra_prompt = Column(Text)                             # 用户输入的额外提示词

    # 元信息
    created_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="completed")        # generating / completed / failed
    error_message = Column(Text)                            # 失败时的错误信息
```

---

## 3. API 设计

### 3.1 任务管理

```
GET    /api/personal-todo/tasks
POST   /api/personal-todo/tasks
PUT    /api/personal-todo/tasks/{task_id}
DELETE /api/personal-todo/tasks/{task_id}
```

#### GET /api/personal-todo/tasks

获取任务列表，支持筛选和排序。

**Query Parameters:**
| 参数 | 类型 | 说明 |
|------|------|------|
| status | string | 筛选状态：all / todo / in_progress / done / cancelled |
| priority | string | 筛选优先级：all / P0 / P1 / P2 / P3 |
| area | string | 筛选领域 |
| sort_by | string | 排序字段：created / updated / priority / due_date |
| sort_order | string | 排序方向：asc / desc |

**Response:**
```json
{
  "tasks": [
    {
      "id": 1,
      "title": "优化 Ascend NPU 注意力计算",
      "description": "当前实现存在性能瓶颈...",
      "source": "team",
      "priority": "P0",
      "status": "in_progress",
      "area": "kernels",
      "tags": ["performance", "npu"],
      "due_date": "2024-02-15",
      "created_at": "2024-01-20T10:00:00Z",
      "updated_at": "2024-01-25T14:30:00Z",
      "has_dedup_check": true,
      "has_ai_insight": false
    }
  ],
  "total": 15,
  "stats": {
    "by_status": {"todo": 5, "in_progress": 3, "done": 6, "cancelled": 1},
    "by_priority": {"P0": 2, "P1": 4, "P2": 6, "P3": 3}
  }
}
```

#### POST /api/personal-todo/tasks

创建新任务。

**Request Body:**
```json
{
  "title": "优化 Ascend NPU 注意力计算",
  "description": "当前实现存在性能瓶颈，需要参考 sglang 的实现...",
  "source": "team",
  "priority": "P0",
  "area": "kernels",
  "tags": ["performance", "npu"],
  "due_date": "2024-02-15",
  "trigger_dedup_check": true      // 是否立即触发去重检查
}
```

**Response:**
```json
{
  "id": 1,
  "title": "优化 Ascend NPU 注意力计算",
  "status": "todo",
  "dedup_check_result": {
    "checked": true,
    "matches": [
      {
        "repo": "vllm-project/vllm",
        "type": "issue",
        "number": 1234,
        "title": "[Ascend] Attention kernel optimization needed",
        "similarity": "high",
        "url": "https://github.com/vllm-project/vllm/issues/1234"
      }
    ]
  }
}
```

### 3.2 去重检查

```
POST   /api/personal-todo/tasks/{task_id}/dedup-check
```

#### POST /api/personal-todo/tasks/{task_id}/dedup-check

对指定任务执行去重检查，搜索是否有相似的 issue/PR。

**Request Body:**
```json
{
  "repos": ["vllm-project/vllm"],    // 要检查的仓库列表
  "check_type": "hybrid"             // 'keyword' / 'semantic' / 'hybrid'
}
```

**Response:**
```json
{
  "task_id": 1,
  "checked_at": "2024-01-25T14:30:00Z",
  "results": [
    {
      "repo": "vllm-project/vllm",
      "type": "issue",
      "number": 1234,
      "title": "[Ascend] Attention kernel optimization needed",
      "state": "open",
      "similarity": "high",
      "reason": "关键词匹配：Ascend、Attention、optimization",
      "url": "https://github.com/vllm-project/vllm/issues/1234"
    }
  ]
}
```

### 3.3 洞察报告

```
GET    /api/intelligence/reports
POST   /api/intelligence/generate
GET    /api/intelligence/reports/{report_id}
```

#### GET /api/intelligence/reports

获取洞察报告列表（按时间倒序，无需筛选）。

**Response:**
```json
{
  "reports": [
    {
      "id": 1,
      "title": "Ascend NPU 注意力优化相关动态",
      "task_id": 1,
      "task_title": "优化 Ascend NPU 注意力计算",
      "sources": ["vllm", "vllm-ascend", "sglang"],
      "word_count": 2340,
      "created_at": "2024-01-25T14:30:00Z",
      "status": "completed"
    },
    {
      "id": 2,
      "title": "FlashAttention 技术趋势分析",
      "task_id": 2,
      "task_title": "研究 FlashAttention-3 集成方案",
      "sources": ["vllm", "academic", "news"],
      "word_count": 1890,
      "created_at": "2024-01-20T10:15:00Z",
      "status": "completed"
    }
  ]
}
```

#### POST /api/intelligence/generate

触发生成洞察报告。

**Request Body:**
```json
{
  "task_id": 1,                                  // 关联的任务 ID
  "title": "Ascend NPU 注意力优化相关动态",       // 报告标题（可选，默认自动生成）
  "sources": ["vllm", "vllm-ascend", "sglang", "academic", "news"],  // 要包含的来源
  "excluded_sources": [],                         // 排除的来源（优先级高于 sources）
  "extra_prompt": ""                             // 用户提供的额外提示词（可包含论文信息、特殊要求等）
}
```

> **说明**：`extra_prompt` 字段用于用户补充信息，例如：
> - 提供的学术论文内容："以下是我最近关注的论文：FlashAttention-3: Faster and More Attention by Tri Dao..."
> - 特殊关注点："重点关注 Ascend NPU 相关的性能优化方案"
> - 其他自定义需求

**Response:**
```json
{
  "report_id": 1,
  "task_id": 1,
  "title": "Ascend NPU 注意力优化相关动态",
  "status": "generating",
  "message": "洞察报告正在生成中，预计需要 60-90 秒"
}
```

> **注意**：由于洞察报告生成耗时较长（需调用多个 API + AI 分析），建议采用异步模式：
> - 接口立即返回 `report_id` 和 `status: "generating"`
> - 前端轮询或通过 WebSocket 获取进度
> - 生成完成后状态变为 `completed`

#### GET /api/intelligence/reports/{report_id}

获取洞察报告详情。

**Response:**
```json
{
  "id": 1,
  "title": "Ascend NPU 注意力优化相关动态",
  "task_id": 1,
  "task_title": "优化 Ascend NPU 注意力计算",
  "content": "# Ascend NPU 注意力优化相关动态\n\n## 摘要\n\n本报告分析了与 Ascend NPU 注意力优化相关的最新动态...\n\n## vLLM 社区动态\n\n### 相关 Issue/PR\n\n- **Issue #1234**: [Ascend] Attention kernel optimization needed\n  - 状态: Open\n  - 创建时间: 2024-01-20\n  - URL: https://github.com/vllm-project/vllm/issues/1234\n\n- **PR #5678**: Add FlashAttention-3 support for Ascend\n  - 状态: In Review\n  - 变更文件: 15\n  - URL: https://github.com/vllm-project/vllm/pull/5678\n\n### 讨论热点\n\n近期社区讨论集中在以下话题：\n1. FlashAttention-3 的集成路径\n2. Ascend NPU 的性能优化方向\n\n## vLLM-Ascend 动态\n\n### 相关 Issue/PR\n\n- **Issue #45**: Performance regression on A100\n  - ...\n\n## 竞品动态\n\n### sglang\n\n- **新功能**: FlashAttention-3 支持\n  - 最近添加了对 FlashAttention-3 的支持，使用新的 tiling 策略...\n  - 相关链接: https://github.com/sgl-project/sglang/pull/xxx\n\n- **解决方案**: KV cache 分块预分配\n  - 解决了 NPU 上的 KV cache 内存碎片问题...\n  - 相关链接: https://github.com/sgl-project/sglang/issues/xxx\n\n## 学术动态\n\n### 相关论文\n\n- **FlashAttention-3: Faster and More Attention**\n  - 作者: Tri Dao\n  - 发表: arXiv 2024\n  - 摘要: 提出了新的 tiling 策略，进一步提升了注意力计算效率...\n\n### 技术趋势\n\n近期学术界在注意力机制方面的研究方向：\n1. 更高效的内存访问模式\n2. 硬件感知的算法设计\n\n## 新闻动态\n\n### 行业新闻\n\n- vLLM 发布 v0.4.0，支持更多模型架构\n- HuggingFace 推出新的推理加速库\n\n### 发布信息\n\n- PyTorch 2.3 发布，包含多项性能优化\n- CUDA 12.4 发布\n\n## AI 建议\n\n基于以上分析，建议：\n1. 优先关注 Issue #1234，了解社区的具体需求\n2. 参考 sglang 的 KV cache 实现，可能对 vllm-ascend 有借鉴价值\n3. 跟进 FlashAttention-3 的研究进展，评估集成可行性\n",
  "sources": ["vllm", "vllm-ascend", "sglang", "academic", "news"],
  "created_at": "2024-01-25T14:35:00Z",
  "status": "completed"
}
```

---

## 4. 核心服务设计

### 4.1 TaskDedupChecker（去重检查器）

```python
# app/services/task_dedup.py

class TaskDedupChecker:
    """任务去重检查器"""

    def __init__(self, github_client: GitHubClient, ai_assistant: AIAssistant):
        self.client = github_client
        self.ai = ai_assistant

    def check_duplicates(
        self, title: str, description: str, repos: List[str]
    ) -> List[Dict]:
        """
        检查是否有重复的 issue/PR

        策略：混合模式
        1. 关键词提取 + GitHub Search API（快速过滤）
        2. AI 语义相似度对比（精确判断）
        """
        # Step 1: 提取关键词
        keywords = self._extract_keywords(title, description)

        # Step 2: 对每个仓库执行搜索
        all_candidates = []
        for repo in repos:
            candidates = self._search_repo(repo, keywords)
            all_candidates.extend(candidates)

        # Step 3: AI 语义对比（取 top 10 候选）
        similar_items = self._ai_semantic_compare(title, description, all_candidates[:10])

        return similar_items

    def _extract_keywords(self, title: str, description: str) -> List[str]:
        """提取关键词用于搜索"""
        # 简单实现：提取名词性短语
        # 可扩展为更复杂的 NLP 处理
        text = f"{title} {description}"
        # 移除常见停用词，提取技术术语
        keywords = []
        # ... 关键词提取逻辑
        return keywords

    def _search_repo(self, repo: str, keywords: List[str]) -> List[Dict]:
        """在指定仓库搜索"""
        # 构建搜索查询
        query_parts = [f"repo:{repo}", "is:issue", "is:pr"]
        # 添加关键词
        query_parts.extend(keywords[:5])  # 限制关键词数量

        query = " ".join(query_parts)
        return self.client._search_issues(query) or []

    def _ai_semantic_compare(
        self, title: str, description: str, candidates: List[Dict]
    ) -> List[Dict]:
        """AI 语义相似度对比"""
        if not candidates:
            return []

        prompt = f"""比较以下任务描述与候选 issue/PR 的相似度。

任务标题：{title}
任务描述：{description}

候选列表：
{json.dumps([{"number": c["number"], "title": c["title"], "state": c["state"]} for c in candidates], indent=2)}

返回 JSON 格式：
{{
  "matches": [
    {{
      "item_number": 123,
      "item_title": "...",
      "similarity": "high/medium/low",
      "reason": "为什么相似"
    }}
  ]
}}

只返回高度相似或中度相似的项目。"""

        result = self.ai._chat(prompt, max_tokens=1024, temperature=0.3)
        parsed = self.ai._safe_json(result, {"matches": []})
        return parsed.get("matches", [])
```

### 4.2 IntelligenceReportGenerator（洞察报告生成器）

```python
# app/services/intelligence_report.py

class IntelligenceReportGenerator:
    """洞察报告生成器"""

    # 来源配置
    SOURCE_CONFIG = {
        "vllm": {
            "display_name": "vLLM 社区",
            "repos": ["vllm-project/vllm"],
            "type": "github"
        },
        "vllm-ascend": {
            "display_name": "vLLM-Ascend",
            "repos": ["vllm-project/vllm-ascend"],
            "type": "github"
        },
        "sglang": {
            "display_name": "sglang",
            "repos": ["sgl-project/sglang"],
            "type": "github"
        },
        "academic": {
            "display_name": "学术动态",
            "type": "manual",  # 用户提供论文信息
            "description": "用户手动提供的学术论文信息"
        },
        "news": {
            "display_name": "新闻动态",
            "sources": [
                "Hacker News",
                "Reddit (r/MachineLearning, r/LocalLLaMA)",
                "GitHub Trending",
                "Twitter/X (@vllm_project)"
            ],
            "type": "web"
        }
    }

    def __init__(self, github_client: GitHubClient, ai_assistant: AIAssistant):
        self.client = github_client
        self.ai = ai_assistant

    def generate_report(
        self,
        task_title: str,
        task_description: str,
        sources: List[str],
        excluded_sources: List[str] = None,
        extra_prompt: str = ""
    ) -> Dict:
        """
        生成洞察报告

        Args:
            task_title: 触发任务的标题
            task_description: 触发任务的描述
            sources: 要包含的来源列表
            excluded_sources: 排除的来源列表
            extra_prompt: 用户提供的额外提示词（可包含论文信息、特殊要求等）

        Returns:
            生成的报告内容（Markdown）
        """
        # 确定实际使用的来源
        effective_sources = self._resolve_sources(sources, excluded_sources)

        # 收集各来源的数据
        report_data = {}

        for source in effective_sources:
            if source == "news":
                report_data["news"] = self._fetch_news_dynamics(task_title, task_description)
            else:
                # GitHub 相关来源
                report_data[source] = self._fetch_github_dynamics(
                    source, task_title, task_description
                )

        # AI 整合分析，生成最终报告
        report_content = self._generate_markdown_report(
            task_title, task_description, report_data, extra_prompt
        )

        return {
            "content": report_content,
            "sources": effective_sources
        }

    def _resolve_sources(
        self, sources: List[str], excluded_sources: List[str] = None
    ) -> List[str]:
        """解析最终使用的来源列表"""
        if excluded_sources:
            return [s for s in sources if s not in excluded_sources]
        return sources

    def _fetch_github_dynamics(
        self, source: str, task_title: str, task_description: str
    ) -> Dict:
        """从 GitHub 获取动态"""
        config = self.SOURCE_CONFIG.get(source, {})
        repos = config.get("repos", [])

        all_items = []
        keywords = self._extract_keywords(task_title + " " + task_description)

        for repo in repos:
            # 搜索近 30 天的 issue/PR
            since = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"

            # 构建搜索查询
            query_parts = [f"repo:{repo}", f"is:issue", f"created:>{since}"]
            if keywords:
                query_parts.extend(keywords[:5])

            query = " ".join(query_parts)
            items = self.client._search_issues(query) or []
            all_items.extend(items)

        return {
            "items": all_items[:20],  # 限制数量
            "total": len(all_items)
        }

    def _fetch_news_dynamics(
        self, task_title: str, task_description: str
    ) -> Dict:
        """获取新闻动态（Phase 1 实现基础版本）"""
        keywords = self._extract_keywords(task_title + " " + task_description)

        # Phase 1: 集成 Hacker News API
        # Phase 2: 扩展 Reddit、GitHub Trending、Twitter/X
        return {
            "hacker_news": [],
            "reddit": [],
            "github_trending": [],
            "twitter": []
        }

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词用于搜索"""
        # 简单实现：移除常见停用词，提取技术术语
        stop_words = {"的", "了", "是", "在", "有", "和", "与", "或", "等", "这", "那", "个", "一", "不", "要", "需", "求"}
        words = re.findall(r'\b[a-zA-Z]+\b|\b[一-龥]{2,}\b', text)
        keywords = [w for w in words if w not in stop_words and len(w) > 1]
        return keywords[:10]

    def _generate_markdown_report(
        self,
        task_title: str,
        task_description: str,
        report_data: Dict,
        extra_prompt: str = ""
    ) -> str:
        """AI 生成 Markdown 格式的洞察报告"""

        # 构建各来源的数据摘要
        sections = []

        for source, data in report_data.items():
            if source == "news":
                sections.append(self._format_news_section(data))
            else:
                sections.append(self._format_github_section(source, data))

        sections_text = "\n\n".join(sections)

        # 构建额外提示词部分
        extra_section = ""
        if extra_prompt:
            extra_section = f"\n\n## 用户补充信息\n\n{extra_prompt}"

        prompt = f"""基于以下数据，生成一份结构化的洞察报告。

任务标题：{task_title}
任务描述：{task_description}

各来源数据：
{sections_text}
{extra_section}

请生成一份完整的 Markdown 格式洞察报告，包含以下章节：

# {task_title} 相关动态洞察

## 摘要
一句话总结核心发现（不超过 50 字）

## vLLM 社区动态
### 相关 Issue/PR
列出与任务最相关的 issue/PR，每个包含标题、状态、链接
### 讨论热点
总结近期社区讨论的热点话题

## vLLM-Ascend 动态
### 相关 Issue/PR
...

## 竞品动态
### sglang
列出竞品的新功能、解决方案、技术趋势

## 学术动态
### 相关论文
如果用户提供了论文信息，分析其相关性；否则简要概述当前学术趋势
### 技术趋势
总结学术界的最新研究方向

## 新闻动态
### 行业新闻
列出相关的行业新闻
### 发布信息
列出相关的版本发布信息

## AI 建议
基于以上分析，给出 3-5 条具体建议

要求：
- 使用中文
- 内容要有实质价值，不要泛泛而谈
- 每条建议要具体可执行
- 适当引用数据来源"""

        result = self.ai._chat(prompt, max_tokens=4096, temperature=0.7)
        return result

    def _format_github_section(self, source: str, data: Dict) -> str:
        """格式化 GitHub 来源的数据"""
        display_name = self.SOURCE_CONFIG.get(source, {}).get("display_name", source)
        items = data.get("items", [])

        if not items:
            return f"{display_name}: 暂无相关动态"

        lines = [f"{display_name}:"]
        for item in items[:10]:
            lines.append(f"- {item.get('title', '')} (#{item.get('number')})")
            lines.append(f"  状态: {item.get('state', 'unknown')}")
            lines.append(f"  URL: {item.get('html_url', '')}")

        return "\n".join(lines)

    def _format_news_section(self, data: Dict) -> str:
        """格式化新闻来源的数据"""
        # 实际实现需要调用多个 API
        # Hacker News API、Reddit API、GitHub Trending、Twitter/X
        return "新闻动态: 待集成第三方 API"
```

---

## 5. 前端设计

### 5.1 整体页面布局

```
┌─────────────────────────────────────────────────────────────────────┐
│  vLLM Assistant · 贡献者控制台                                      │
├──────────┬──────────────────────────────────────────────────────────┤
│          │                                                          │
│  📋 工作区 │   主内容区域                                              │
│          │                                                          │
│  ┌───────┐│   ┌─────────────────────────────────────────────────┐  │
│  │社区动态││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│  ┌───────┐│   │                                                     │  │
│  │我的贡献││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│  ┌───────┐│   │                                                     │  │
│  │特别关注││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│  ┌───────┐│   │                                                     │  │
│  │我的数据││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│          │   │                                                     │  │
│  ┌───────┐│   │                                                     │  │
│  │个人TODO││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│          │   │                                                     │  │
│  ┌───────┐│   │                                                     │  │
│  │情报面板││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│          │   │                                                     │  │
│  操作     │   │                                                     │  │
│  ┌───────┐│   │                                                     │  │
│  │命令面板││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│  ┌───────┐│   │                                                     │  │
│  │立即同步││   │                                                     │  │
│  └───────┘│   │                                                     │  │
│          │   │                                                     │  │
│  同步状态 │   │                                                     │  │
│  ● 正常   │   │                                                     │  │
│          │   │                                                     │  │
└──────────┴─────────────────────────────────────────────────────────┘
```

### 5.2 个人 TODO 面板布局

```
┌─────────────────────────────────────────────────────────────────────┐
│  个人 TODO 面板                        [搜索框] [刷新]               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 快速添加任务                                                    │ │
│  │ ┌───────────────────────────────────────────────────────────┐ │ │
│  │ │ 标题: [________________________________________]              │ │ │
│  │ │ 描述: [________________________________________]              │ │ │
│  │ │       [__________________________________________________]   │ │ │
│  │ │ 来源: [自己发现 ▼]  优先级: [P0 ▼]  领域: [engine ▼]        │ │ │
│  │ │ 截止日期: [____]  标签: [性能] [优化] [+]                   │ │ │
│  │ └───────────────────────────────────────────────────────────┘ │ │
│  │ [☑ 添加后自动去重检查]  [添加任务]                               │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 统计概览                                                        │ │
│  │ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐                       │ │
│  │ │待处理 │ │进行中 │ │已完成 │ │已取消 │                       │ │
│  │ │   5   │ │   3   │ │   6   │ │   1   │                       │ │
│  │ └───────┘ └───────┘ └───────┘ └───────┘                       │ │
│  │ P0: 2  P1: 4  P2: 6  P3: 3                                     │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 筛选器                                                          │ │
│  │ 状态: [全部] [待处理] [进行中] [已完成] [已取消]               │ │
│  │ 优先级: [全部] [P0] [P1] [P2] [P3]                             │ │
│  │ 领域: [全部] [engine] [model] [kernels] [attention] ...         │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 任务列表 (Kanban 风格)                                          │ │
│  │ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │ │
│  │ │ P0 紧急     │ │ P1 重要     │ │ P2 普通     │ │ P3 低优   │ │ │
│  │ ├─────────────┤ ├─────────────┤ ├─────────────┤ ├───────────┤ │ │
│  │ │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌───────┐ │ │ │
│  │ │ │• 任务1  │ │ │ │• 任务3  │ │ │ │• 任务5  │ │ │ │• 任务7│ │ │ │
│  │ │ │ 优化NPU │ │ │ │ 研究FA3 │ │ │ │ 重构代码│ │ │ │ 文档更新│ │ │ │
│  │ │ │ 性能    │ │ │ │ 集成方案│ │ │ │ 注释    │ │ │ │       │ │ │ │
│  │ │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │ └───────┘ │ │ │
│  │ │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌─────────┐ │ │ ┌───────┐ │ │ │
│  │ │ │• 任务2  │ │ │ │• 任务4  │ │ │ │• 任务6  │ │ │ │• 任务8│ │ │ │
│  │ │ │ 修复bug │ │ │ │ 添加测试│ │ │ │ 更新依赖│ │ │ │ 会议纪要│ │ │ │
│  │ │ └─────────┘ │ │ └─────────┘ │ │ └─────────┘ │ │ └───────┘ │ │ │
│  │ └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.3 情报面板布局

```
┌─────────────────────────────────────────────────────────────────────┐
│  情报面板                        [搜索框] [刷新]                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 生成洞察报告                                                    │ │
│  │ ┌───────────────────────────────────────────────────────────┐ │ │
│  │ │ 关联任务: [优化 Ascend NPU 注意力计算 ▼]                    │ │ │
│  │ │ 报告标题: [________________________________________]          │ │ │
│  │ │                                                            │ │ │
│  │ │ 包含来源:                                                    │ │ │
│  │ │ ☑ vLLM 社区    ☑ vLLM-Ascend    ☑ sglang                 │ │ │
│  │ │ ☑ 学术动态    ☑ 新闻动态                                   │ │ │
│  │ │                                                            │ │ │
│  │ │ 额外提示词:                                                  │ │ │
│  │ │ ┌─────────────────────────────────────────────────────────┐│ │ │
│  │ │ │ 以下是我最近关注的论文：                                  ││ │ │
│  │ │ │ FlashAttention-3: Faster and More Attention by Tri Dao  ││ │ │
│  │ │ │ ...                                                       ││ │ │
│  │ │ └─────────────────────────────────────────────────────────┘│ │ │
│  │ │                                                            │ │ │
│  │ │ [生成报告]                                                   │ │ │
│  │ └───────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 洞察报告列表                                                    │ │
│  │ ┌───────────────────────────────────────────────────────────┐ │ │
│  │ │ 📄 Ascend NPU 注意力优化相关动态                              │ │ │
│  │ │   触发任务: "优化 Ascend NPU 注意力计算"                    │ │ │
│  │ │   来源: vllm, vllm-ascend, sglang, academic, news          │ │ │
│  │ │   生成时间: 2024-01-25 14:35  字数: 2,340                  │ │ │
│  │ │   [查看报告]  [重新生成]  [复制 Markdown]                   │ │ │
│  │ ├───────────────────────────────────────────────────────────┤ │ │
│  │ │ 📄 FlashAttention 技术趋势分析                               │ │ │
│  │ │   触发任务: "研究 FlashAttention-3 集成方案"                │ │ │
│  │ │   来源: vllm, academic, news                               │ │ │
│  │ │   生成时间: 2024-01-20 10:15  字数: 1,890                  │ │ │
│  │ │   [查看报告]  [重新生成]  [复制 Markdown]                   │ │ │
│  │ ├───────────────────────────────────────────────────────────┤ │ │
│  │ │ 📄 KV Cache 优化方案调研                                     │ │ │
│  │ │   触发任务: "优化 KV Cache 内存管理"                        │ │ │
│  │ │   来源: vllm, vllm-ascend, sglang                         │ │ │
│  │ │   生成时间: 2024-01-15 09:00  字数: 1,560                  │ │ │
│  │ │   [查看报告]  [重新生成]  [复制 Markdown]                   │ │ │
│  │ └───────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.4 任务详情抽屉

```
┌─────────────────────────────────────────────────────────────────────┐
│  任务详情                                  [关闭]                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ #1 优化 Ascend NPU 注意力计算                                    │ │
│  │                                                                │ │
│  │ [badge-state-open] 开放                                        │ │
│  │                                                                │ │
│  │ 元信息:                                                        │ │
│  │ • 来源: 团队反馈                                               │ │
│  │ • 优先级: [P0]                                                 │ │
│  │ • 领域: kernels                                                │ │
│  │ • 创建时间: 2024-01-20                                         │ │
│  │ • 截止日期: 2024-02-15                                         │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 描述:                                                          │ │
│  │ 当前实现存在性能瓶颈，需要参考 sglang 的实现...                  │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 去重检查结果                                                    │ │
│  │ ⚠️ 发现 2 个可能重复的项目:                                     │ │
│  │                                                                │ │
│  │ • Issue #1234: [Ascend] Attention kernel optimization needed    │ │
│  │   相似度: high | https://github.com/.../issues/1234            │ │
│  │                                                                │ │
│  │ • PR #5678: Add FlashAttention-3 support for Ascend            │ │
│  │   相似度: medium | https://github.com/.../pull/5678            │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 操作按钮:                                                      │ │
│  │ [🔍 生成洞察报告]  [编辑]  [删除]  [标记完成]                    │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.5 洞察报告查看弹窗

```
┌─────────────────────────────────────────────────────────────────────┐
│  Ascend NPU 注意力优化相关动态                    [关闭] [全屏]       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 报告信息                                                       │ │
│  │ • 触发任务: 优化 Ascend NPU 注意力计算                         │ │
│  │ • 生成时间: 2024-01-25 14:35                                  │ │
│  │ • 来源: vllm, vllm-ascend, sglang, academic, news             │ │
│  │ • 字数: 2,340                                                 │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 报告内容 (Markdown 渲染)                                        │ │
│  │ ┌───────────────────────────────────────────────────────────┐ │ │
│  │ │ # Ascend NPU 注意力优化相关动态                             │ │ │
│  │ │                                                            │ │ │
│  │ │ ## 摘要                                                    │ │ │
│  │ │ 本报告分析了与 Ascend NPU 注意力优化相关的最新动态...     │ │ │
│  │ │                                                            │ │ │
│  │ │ ## vLLM 社区动态                                           │ │ │
│  │ │ ### 相关 Issue/PR                                         │ │ │
│  │ │ - **Issue #1234**: [Ascend] Attention kernel optimization  │ │ │
│  │ │   状态: Open | URL: https://github.com/...                │ │ │
│  │ │                                                            │ │ │
│  │ │ ## vLLM-Ascend 动态                                        │ │ │
│  │ │ ...                                                        │ │ │
│  │ │                                                            │ │ │
│  │ │ ## AI 建议                                                 │ │ │
│  │ │ 1. 优先关注 Issue #1234...                                │ │ │
│  │ └───────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 操作按钮:                                                      │ │
│  │ [复制 Markdown]  [重新生成]  [导出 PDF]                        │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.6 去重检查弹窗

```
┌─────────────────────────────────────────────────────────────────────┐
│  ⚠️ 发现可能重复的项目                                [关闭]          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  以下 issue/PR 可能与您要创建的任务重复：                          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ • Issue #1234: [Ascend] Attention kernel optimization needed   │ │
│  │   仓库: vllm-project/vllm                                     │ │
│  │   相似度: [high]                                              │ │
│  │   原因: 关键词匹配：Ascend、Attention、optimization           │ │
│  │   [在 GitHub 查看]  [关联到此任务]  [忽略]                     │ │
│  ├───────────────────────────────────────────────────────────────┤ │
│  │ • PR #5678: Add FlashAttention-3 support for Ascend          │ │
│  │   仓库: vllm-project/vllm                                     │ │
│  │   相似度: [medium]                                            │ │
│  │   原因: 涉及 FlashAttention 和 Ascend                        │ │
│  │   [在 GitHub 查看]  [关联到此任务]  [忽略]                     │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 操作按钮:                                                      │ │
│  │ [跳过检查]  [确认创建任务]                                      │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.7 任务卡片组件

```javascript
// 单个任务卡片
<div class="task-card">
    <!-- 优先级标识 -->
    <span class="priority-badge" :class="'priority-' + task.priority">
        {{ task.priority }}
    </span>
    
    <!-- 任务标题 -->
    <h4 class="task-title" @click="openTask(task)">
        {{ task.title }}
    </h4>
    
    <!-- 状态标签 -->
    <span class="status-badge" :class="'status-' + task.status">
        {{ statusLabel(task.status) }}
    </span>
    
    <!-- 元信息 -->
    <div class="task-meta">
        <span class="source-tag">{{ sourceLabel(task.source) }}</span>
        <span class="area-tag">{{ task.area }}</span>
        <span class="due-date" x-show="task.due_date">
            截止: {{ formatDate(task.due_date) }}
        </span>
    </div>
    
    <!-- 去重检查状态 -->
    <div class="dedup-status" x-show="task.has_dedup_check">
        <template x-if="task.dedup_matches > 0">
            <span class="warning">⚠️ {{ task.dedup_matches }} 个可能重复</span>
        </template>
        <template x-else>
            <span class="success">✓ 无重复</span>
        </template>
    </div>
    
    <!-- 操作按钮 -->
    <div class="task-actions">
        <button @click.stop="generateInsight(task)" title="生成洞察报告">
            🔍
        </button>
        <button @click.stop="editTask(task)" title="编辑">
            ✏️
        </button>
    </div>
</div>
```

### 5.8 洞察报告卡片组件

```javascript
// 单个洞察报告卡片
<div class="report-card">
    <!-- 报告图标 -->
    <span class="report-icon">📄</span>
    
    <!-- 报告标题 -->
    <h4 class="report-title" @click="viewReport(report)">
        {{ report.title }}
    </h4>
    
    <!-- 关联任务 -->
    <div class="report-task">
        触发任务: <strong>{{ report.task_title }}</strong>
    </div>
    
    <!-- 来源标签 -->
    <div class="report-sources">
        <template x-for="source in report.sources" :key="source">
            <span class="source-badge" :class="'source-' + source">
                {{ sourceLabel(source) }}
            </span>
        </template>
    </div>
    
    <!-- 元信息 -->
    <div class="report-meta">
        <span>生成时间: {{ timeAgo(report.created_at) }}</span>
        <span>字数: {{ report.word_count }}</span>
    </div>
    
    <!-- 操作按钮 -->
    <div class="report-actions">
        <button @click.stop="viewReport(report)" title="查看">
            👁️
        </button>
        <button @click.stop="regenerateReport(report)" title="重新生成">
            🔄
        </button>
        <button @click.stop="copyReport(report)" title="复制 Markdown">
            📋
        </button>
    </div>
</div>
```

---

## 6. 错误处理与异步任务管理

### 6.1 错误处理策略

| 场景 | 错误类型 | 处理方式 |
|------|----------|----------|
| GitHub API Rate Limit | 429 | 返回友好提示，建议用户稍后重试 |
| GitHub API 认证失败 | 401 | 返回配置错误提示，引导检查 PAT |
| AI 调用超时 | TIMEOUT | 返回错误信息，支持手动重试 |
| AI 返回格式异常 | PARSE_ERROR | 使用 fallback 数据，记录日志 |
| 数据库写入失败 | DB_ERROR | 返回 500 错误，前端显示通用错误提示 |

**统一错误响应格式：**
```json
{
  "error": {
    "type": "rate_limit",
    "message": "GitHub API 请求频率超限，请稍后重试",
    "retry_after": 60,
    "details": "..."
  }
}
```

### 6.2 异步任务状态管理

洞察报告生成采用异步模式：

| 参数 | 值 | 说明 |
|------|-----|------|
| 轮询间隔 | 3 秒 | 前端轮询检查报告状态 |
| 超时时间 | 180 秒 | 超过此时间标记为 failed |
| 最大重试次数 | 1 次 | 失败后允许手动重新生成 |

**状态流转：**
```
generating → completed (成功)
           → failed (失败，需手动重试)
```

### 6.3 分页设计

**任务列表分页：**
```
GET /api/personal-todo/tasks?page=1&per_page=20
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| page | 1 | 页码 |
| per_page | 20 | 每页数量（最大 50） |

**响应格式：**
```json
{
  "tasks": [...],
  "total": 150,
  "page": 1,
  "per_page": 20,
  "has_more": true
}
```

### 6.4 测试策略

| 层级 | 测试内容 | 工具 |
|------|----------|------|
| 单元测试 | 关键词提取、来源解析、Markdown 格式化 | pytest |
| 集成测试 | API 端点、数据库操作 | pytest + httpx |
| E2E 测试 | 前端交互流程 | Playwright（可选） |

**关键测试用例：**
1. 去重检查：关键词匹配 + AI 语义对比
2. 洞察报告生成：多来源数据聚合 + AI 整合
3. 异步任务状态：generating → completed 流转
4. 错误处理：API 限流、AI 超时、DB 错误

---

## 7. 配置项

```python
# app/config.py 新增

class Config:
    # ... 现有配置 ...

    # 去重检查默认仓库
    DEFAULT_DEDUP_REPOS = os.getenv(
        "DEFAULT_DEDUP_REPOS", 
        "vllm-project/vllm"
    ).split(",")

    # 洞察报告来源配置（JSON 格式）
    INTELLIGENCE_SOURCES = os.getenv(
        "INTELLIGENCE_SOURCES",
        '{"vllm": {"repos": ["vllm-project/vllm"]}, "vllm-ascend": {"repos": ["vllm-project/vllm-ascend"]}, "sglang": {"repos": ["sgl-project/sglang"]}}'
    )
```

---

## 8. 路由注册

```python
# app/main.py 修改

from app.api.personal_todo import router as personal_todo_router
from app.api.intelligence import router as intelligence_router

app.include_router(
    personal_todo_router, 
    prefix="/api/personal-todo", 
    tags=["Personal TODO"]
)

app.include_router(
    intelligence_router, 
    prefix="/api/intelligence", 
    tags=["Intelligence Reports"]
)
```

---

## 9. 实施计划

| 阶段 | 内容 | 预计工时 |
|------|------|----------|
| Phase 1 | 数据模型 + CRUD API | 1 天 |
| Phase 2 | 去重检查服务（关键词 + AI） | 1.5 天 |
| Phase 3 | 情报面板 + 洞察报告生成器 | 2 天 |
| Phase 4 | 前端视图 + 交互 | 1 天 |
| **总计** | | **5.5 天** |

---

## 10. 未来扩展

- 支持更多竞品仓库（tensorrt-llm、llama.cpp 等）
- 新闻动态功能集成第三方 API（Hacker News、Reddit、Twitter）
- 定期自动扫描并推送洞察摘要
- 任务与 GitHub Issue 双向同步
- 团队成员共享任务视图
