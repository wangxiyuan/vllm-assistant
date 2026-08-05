## 昨日概览

| 指标 | 数值 |
|------|------|
| 新增 Issue | {{ issue_count }}（bug: {{ bug_count }} / feature: {{ feature_count }} / 其他: {{ other_count }}） |
| 新增 PR | {{ pr_count }}（已合并: {{ merged_count }} / 待审核: {{ wip_count }}） |
| 版本发布 | {{ release_count }} |

> 昨日核心动态一句话总结（不超过 100 字），数据覆盖近 24 小时，监控仓库列表。

## 昨日新增 Issue 明细

| 编号 | 标题 | 标签 | 状态 | 简要分析 |
|------|------|------|------|----------|
| #{{ number }} | {{ title }} | `{{ label }}` | open/closed | 1-2 句分析 |

按热度排序，每个 issue 一行，`backtick` 内写标签如 `bug` `feature` `performance`。表格后跟一行简要分析。

## 昨日新增 PR 明细

| 编号 | 标题 | 状态 | 技术要点 |
|------|------|------|----------|
| #{{ number }} | {{ title }} | merged / WIP | 关键变更摘要 |

## 版本发布

- **{{ repo }} v{{ version }}**（{{ today }}）：{{ summary }}
- 优先引用 get_github_releases 获取的真实数据，不要编造版本号

## 质量与架构

### [高] {{ change_title }}
- **#{{ number }}** {{ change_desc }} — 影响文件数: N，新增行: N，删除行: N
- 风险点：{{ risk_desc }}
- 涉及模块: {{ modules }}

### [中] {{ change_title }}
- **#{{ number }}** {{ change_desc }} — 影响文件数: N，新增行: N，删除行: N
- 风险点：{{ risk_desc }}
- 涉及模块: {{ modules }}

### [低] {{ change_title }}
- **#{{ number }}** {{ change_desc }} — 影响文件数: N，新增行: N，删除行: N
- 纯新增/不影响现有逻辑

## 竞品动态与对比

| 维度 | vLLM | SGLang | 备注 |
|------|------|--------|------|
| {{ feature }} | 已支持 | 已支持 | — |
| {{ feature }} | 未支持 | 已支持 | [建议优先级: 高] 对应 vLLM issue #{{ number }} |

核心差异分析：{{ diff_analysis }}

## 学术动态

- **{{ paper_title }}** ({{ institution }}) [相关性: 高/中/低]
  - {{ abstract }}
  - 链接: {{ arxiv_url }}
  - 建议：{{ suggestion }}

（每篇论文一条，用 search_arxiv 搜索英文关键词获取，标注相关性）

## 新闻动态

- **{{ news_title }}** — {{ news_summary }}
  - 来源: [{{ source }}]({{ url }}) | 与 vLLM 关联: {{ relevance }}

（每条新闻必须标注来源 URL，无来源 URL 的新闻不要写。如果没有找到相关新闻，填"暂无数据"。）

## Slack 信息

- **#{{ channel }}** 讨论: {{ topic }}
  - 参与人数: N | 消息数: N
  - {{ discussion }}

（用 search_by_tags 搜索 tags=slack 获取，标注参与人数、消息数）

## 贡献机会

### [初级] 适合入门贡献者
- **#{{ number }}** {{ title }} `{{ task_type }}` [预估: {{ estimate }}小时]
  - 标签: `good first issue`
  - {{ description }}

### [专业] 需深入理解架构
- **{{ direction }}** [预估: {{ estimate }}天]
  - {{ description }}
  - 涉及模块: {{ modules }}
  - 对应 issue: #{{ number }}

### [研究型] 需原型验证
- **{{ direction }}** [预估: {{ estimate }}周]
  - {{ description }}
  - {{ ref_info }}

## 其他

- {{ other_item }}

（此章节存放不属于以上各 tab 的补充信息，如社区公告、基础设施变更、团队变动、值得关注的长期趋势等。**所有信息必须有可验证的来源（GitHub issue/PR 编号、search_web 返回的 URL 等），无法验证的信息不要写。** 非必要，无内容时留空。）

## 要求
- 使用中文
- 每个结论必须引用具体 issue/PR 编号，使用 #{{ number }} 格式
- 直接输出 Markdown，不要包裹在代码块中
- 搜索时优先搜索近 24-48 小时的内容
- 对于未覆盖的内容，保留章节标题并填写"暂无数据，搜索关键词建议：{{ keywords }}"
- 贡献机会要分三级：初级（good first issue）、专业（架构改进）、研究型（新算法原型）
- 每个 ## 章节将作为独立 tab 展示，内容需完整可独立阅读