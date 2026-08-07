## 昨日概览

| 指标 | 数值 |
|------|------|
| 新增 Issue | {{ issue_count }}（bug: {{ bug_count }} / feature: {{ feature_count }} / 其他: {{ other_count }}） |
| 新增 PR | {{ pr_count }}（已合并: {{ merged_count }} / 待审核: {{ wip_count }}） |
| 版本发布 | {{ release_count }} |

> 昨日核心动态一句话总结（不超过 100 字），数据覆盖近 24 小时，监控仓库列表。

### 昨日新增 Issue 明细

| 编号 | 标题 | 标签 | 状态 | 简要分析 |
|------|------|------|------|----------|
| #{{ number }} | {{ title }} | `{{ label }}` | open/closed | 1-2 句分析 |

按热度排序，每个 issue 一行，`backtick` 内写标签如 `bug` `feature` `performance`。表格后跟一行简要分析。

### 昨日新增 PR 明细

| 编号 | 标题 | 状态 | 技术要点 |
|------|------|------|----------|
| #{{ number }} | {{ title }} | merged / WIP | 关键变更摘要 |

### 版本发布

- **{{ repo }} v{{ version }}**（{{ today }}）：{{ summary }}
- 优先引用 get_github_releases 获取的真实数据，不要编造版本号

## 质量与架构

> 今日共分析 N 个合并 PR，涉及模块：{{ modules }}。重点关注：{{ focus_summary }}

### {{ change_title }} `高`
- **PR**: #{{ number }}
- **影响范围**: {{ files_count }} 个文件，+{{ added }}/-{{ deleted }} 行
- **风险点**: {{ risk_desc }}
- **分析**: {{ analysis }}

### {{ change_title }} `中`
- **PR**: #{{ number }}
- **影响范围**: {{ files_count }} 个文件，+{{ added }}/-{{ deleted }} 行
- **风险点**: {{ risk_desc }}
- **分析**: {{ analysis }}

### {{ change_title }} `低`
- **PR**: #{{ number }}
- **影响范围**: {{ files_count }} 个文件，+{{ added }}/-{{ deleted }} 行
- **分析**: {{ analysis }}

### 技术债务与趋势
- {{ trend_item }}

### 测试与质量关注
- {{ quality_item }}

## 竞品动态与对比

### SGLang 昨日动态
- **PR**: #{{ number }} {{ title }} — {{ summary }}
- **Release**: {{ release_info }}

### 功能对比矩阵

| 维度 | vLLM | SGLang | 趋势方向 | 备注 |
|------|------|--------|---------|------|
| {{ feature }} | 已支持 | 已支持 | → 持平 | — |
| {{ feature }} | 未支持 | 已支持 | ↑ 追赶中 | [建议优先级: 高] 对应 vLLM issue #{{ number }} |
| {{ feature }} | 已支持 | 未支持 | ↓ 领先 | 差异化优势 |

### 差异分析
- **{{ feature }}**：vLLM 未实现，SGLang 已发布。原因：{{ reason }}。建议：{{ suggestion }}

### 总结
{{ summary }}

## 学术动态

### 高相关度
- **{{ paper_title }}** [相关性: 高]
  - {{ abstract }}
  - 链接: {{ arxiv_url }}
  - 建议：{{ suggestion }}

### 一般相关
- **{{ paper_title }}** [相关性: 中/低]
  - 链接: {{ arxiv_url }}

（用 search_arxiv 搜索英文关键词获取，每篇标注相关性。搜索超时或无结果时直接写"搜索超时"或"暂无数据"。）

## 新闻动态

- **{{ news_title }}** — {{ news_summary }}
  - 来源: [{{ source }}]({{ url }}) | 与 vLLM 关联: {{ relevance }}

（用 search_web 搜索行业新闻和技术动态，每条标注来源 URL。注意：**不要在此章节重复版本发布信息**，版本发布已在[昨日数据] tab 中单独列出。如果没有找到相关新闻，填"暂无数据"。）

## Slack 信息

### 话题总结
{{ summary }}

### 讨论明细
- **#{{ channel }}**
  - {{ topic_1 }}（参与: N | 消息: N）
  - {{ topic_2 }}（参与: N | 消息: N）

（用 search_by_tags 搜索 tags=slack 获取。**相同频道的话题合并到同一个频道名下，不要重复展示频道名。**）

## 贡献机会

### 初级 · 适合入门贡献者
- **#{{ number }}** {{ title }} `{{ task_type }}` [预估: {{ estimate }}]
  - 来源: {{ source }}
  - {{ description }}

### 专业 · 需深入理解架构
- **#{{ number }}** {{ title }} `{{ task_type }}` [预估: {{ estimate }}]
  - 来源: {{ source }}
  - {{ description }}
  - 涉及模块: {{ modules }}

### 研究型 · 需原型验证
- **#{{ number }}** {{ title }} `{{ task_type }}` [预估: {{ estimate }}]
  - 来源: {{ source }}
  - {{ description }}
  - 参考: {{ ref_info }}

（无新贡献机会时填"暂无数据"）

## 其他

- {{ other_item }}

（此章节存放其他章节未覆盖的补充信息，如社区公告、基础设施变更、团队变动等。**如果某条信息已在其他 tab 中出现，不要在此重复。** 非必要，无内容时留空。）