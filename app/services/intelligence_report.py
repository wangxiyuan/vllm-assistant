"""
洞察报告生成器（DESIGN-PERSONAL-TODO.md 4.2）

Agent 模式：通过 OpenAI function calling，让 AI 自主决定搜索什么、
读取哪些 issue/PR 的正文和评论，多轮迭代后生成报告。
"""
import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from app.services._shared import get_github_client
from app.services.ai_assistant import AIAssistant

logger = logging.getLogger(__name__)

# Agent 各阶段轮次预算
# 阶段 1（搜索）：每仓库 1 轮，每轮可并行搜 2-3 个关键词变体
# 阶段 2（深入）：读 5-8 个最相关 issue/PR 的正文，可选 1-2 个 PR diff
# 阶段 3（补充）：如果某仓库结果太少，补充搜索
MAX_TOOL_ROUNDS = 10


class IntelligenceReportGenerator:
    """洞察报告生成器（Agent 模式）"""

    SOURCE_CONFIG = {
        "vllm": {
            "display_name": "vLLM 社区",
            "repos": ["vllm-project/vllm"],
            "type": "github",
        },
        "vllm-ascend": {
            "display_name": "vLLM-Ascend",
            "repos": ["vllm-project/vllm-ascend"],
            "type": "github",
        },
        "sglang": {
            "display_name": "sglang",
            "repos": ["sgl-project/sglang"],
            "type": "github",
        },
        "academic": {
            "display_name": "学术动态",
            "type": "manual",
            "description": "用户手动提供的学术论文信息",
        },
        "news": {
            "display_name": "新闻动态",
            "type": "web",
            "description": "行业新闻、版本发布信息",
        },
    }

    # OpenAI function calling 的工具定义
    TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "search_issues",
                "description": "在指定 GitHub 仓库搜索 issue/PR。可按关键词、状态、时间过滤。用于发现与任务相关的讨论。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，空字符串则返回最近创建的 issue/PR",
                        },
                        "repo": {
                            "type": "string",
                            "description": "仓库全名，如 'vllm-project/vllm'",
                        },
                        "state": {
                            "type": "string",
                            "enum": ["open", "closed", "all"],
                            "description": "issue/PR 状态过滤，默认 all",
                        },
                        "days_back": {
                            "type": "integer",
                            "description": "只搜索最近 N 天内创建的，默认 90",
                        },
                    },
                    "required": ["repo"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_issue_detail",
                "description": "获取某个 issue/PR 的正文内容和评论。当 search_issues 发现感兴趣的条目时调用此函数深入了解。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type": "string",
                            "description": "仓库全名，如 'vllm-project/vllm'",
                        },
                        "number": {
                            "type": "integer",
                            "description": "issue/PR 编号",
                        },
                    },
                    "required": ["repo", "number"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_pr_diff",
                "description": "获取某个 PR 的 diff 内容。当需要分析 PR 的具体代码变更时调用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type": "string",
                            "description": "仓库全名，如 'vllm-project/vllm'",
                        },
                        "number": {
                            "type": "integer",
                            "description": "PR 编号",
                        },
                    },
                    "required": ["repo", "number"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_arxiv",
                "description": "在 arXiv 搜索与任务相关的学术论文。用于学术动态调研。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词，英文效果更好，如 'flash attention triton kernel'",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "最大返回数量，默认 5",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_github_releases",
                "description": "获取 GitHub 仓库最近的 release 列表。用于了解项目的版本发布动态，避免编造版本号。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type": "string",
                            "description": "仓库全名，如 'vllm-project/vllm'",
                        },
                        "per_page": {
                            "type": "integer",
                            "description": "返回数量，默认 5",
                        },
                    },
                    "required": ["repo"],
                },
            },
        },
    ]

    def __init__(self):
        self.client = get_github_client()
        self.ai: Optional[AIAssistant] = None

    def _get_ai(self) -> AIAssistant:
        if self.ai is None:
            self.ai = AIAssistant()
        return self.ai

    def generate_report(
        self,
        task_title: str,
        task_description: str,
        sources: List[str],
        excluded_sources: Optional[List[str]] = None,
        extra_prompt: str = "",
    ) -> Dict:
        """生成洞察报告（Agent 模式）

        AI 通过 function calling 自主搜索 GitHub issue/PR、读取正文和评论，
        多轮迭代后生成结构化的 Markdown 报告。
        """
        effective_sources = self._resolve_sources(sources, excluded_sources)

        # 构建可用仓库列表
        github_repos = []
        for s in effective_sources:
            cfg = self.SOURCE_CONFIG.get(s)
            if not cfg:
                continue
            if cfg.get("type") == "github":
                github_repos.extend(cfg.get("repos", []))

        # 构建 system prompt
        system_prompt = self._build_system_prompt(
            task_title, task_description, effective_sources, extra_prompt, github_repos
        )

        # Agent 循环
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请开始调研并生成关于「{task_title}」的洞察报告。"},
        ]

        ai = self._get_ai()
        report_content = ""

        # 尝试 Agent 模式（function calling）；如果 API 不支持 tools，回退到单次模式
        try:
            report_content = self._agent_loop(ai, messages, github_repos, effective_sources)
        except Exception as e:
            # 如果是 tools 不支持的错误，回退到单次模式
            err_str = str(e).lower()
            tools_unsupported = any(kw in err_str for kw in ("tool", "function_call", "not support", "unrecognized"))
            if tools_unsupported:
                logger.warning(f"Agent mode failed (likely tools unsupported), falling back to single-shot: {e}")
                report_content = self._single_shot_report(ai, task_title, task_description, effective_sources, extra_prompt, github_repos)
            else:
                raise

        return {
            "content": report_content,
            "sources": effective_sources,
        }

    def _agent_loop(self, ai: AIAssistant, messages: List[dict], github_repos: List[str], effective_sources: List[str]) -> str:
        """Agent 循环：分阶段引导 AI 搜索和阅读

        阶段 1（前 N 轮）：搜索 - 每个 GitHub 仓库至少搜一轮
        阶段 2（中间轮）：深入 - 读最相关 issue/PR 的正文和评论
        阶段 3（最后 1-2 轮）：生成报告
        """
        # 阶段 1 的轮次预算：每个仓库 1 轮搜索（每轮 AI 可并行调多个 search）
        search_budget = max(len(github_repos), 3)
        # 阶段 2 至少留 4 轮读详情
        detail_budget = MAX_TOOL_ROUNDS - search_budget - 1  # -1 留给最终生成

        search_count = 0  # 已执行的搜索轮次
        detail_count = 0  # 已执行的详情轮次

        for round_num in range(MAX_TOOL_ROUNDS):
            # 根据当前阶段注入引导消息
            guidance = self._phase_guidance(
                round_num, search_count, detail_count,
                search_budget, detail_budget, github_repos, effective_sources
            )
            if guidance:
                messages.append({"role": "user", "content": guidance})

            try:
                response = ai.client.chat.completions.create(
                    model=ai.model,
                    messages=messages,
                    tools=self.TOOLS,
                    max_tokens=4096,
                    temperature=0.3,
                    timeout=ai.DEFAULT_TIMEOUT,
                )
            except Exception:
                logger.exception(f"AI chat failed at round {round_num}")
                raise

            choice = response.choices[0]
            msg = choice.message

            # 如果没有 tool_calls，说明 AI 已完成（直接返回了报告）
            if not msg.tool_calls:
                return msg.content or ""

            # 统计本轮调用的工具类型
            has_search = any(tc.function.name == "search_issues" for tc in msg.tool_calls)
            has_detail = any(tc.function.name in ("get_issue_detail", "get_pr_diff") for tc in msg.tool_calls)
            if has_search:
                search_count += 1
            if has_detail:
                detail_count += 1

            # 把 assistant 的 tool_calls 消息加入历史
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # 并行执行本轮所有 tool calls（GitHub API 请求互不依赖）
            from concurrent.futures import ThreadPoolExecutor

            def _exec_one(tc):
                tool_name = tc.function.name
                try:
                    tool_args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
                logger.info(f"Agent round {round_num} (search={search_count}, detail={detail_count}): {tool_name}({tool_args})")
                result = self._execute_tool(tool_name, tool_args)
                return tc.id, json.dumps(result, ensure_ascii=False)

            with ThreadPoolExecutor(max_workers=min(len(msg.tool_calls), 5)) as pool:
                futures = [pool.submit(_exec_one, tc) for tc in msg.tool_calls]
                for f in futures:
                    tool_call_id, content = f.result()
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": content,
                    })

        # 循环用完，让 AI 基于已有信息生成最终报告
        messages.append({
            "role": "user",
            "content": "已达到搜索上限。请基于已收集的信息，直接生成完整的 Markdown 洞察报告，不要调用工具。",
        })
        try:
            response = ai.client.chat.completions.create(
                model=ai.model,
                messages=messages,
                max_tokens=4096,
                temperature=0.5,
                timeout=ai.DEFAULT_TIMEOUT,
            )
            return response.choices[0].message.content or ""
        except Exception:
            logger.exception("Final report generation failed")
            raise

    def _phase_guidance(
        self, round_num: int, search_count: int, detail_count: int,
        search_budget: int, detail_budget: int, github_repos: List[str],
        effective_sources: List[str]
    ) -> str:
        """根据当前阶段返回引导消息，控制 AI 的行为节奏

        返回空字符串表示不注入引导（让 AI 自由发挥）。
        """
        # 阶段 1：搜索阶段
        if search_count < search_budget:
            if search_count == 0:
                # 第一轮：引导按仓库逐个搜索 + arxiv + releases
                repos_str = "、".join(github_repos)
                parts = [
                    f"现在进入搜索阶段。请对以下每个仓库分别搜索：{repos_str}",
                    f"每个仓库用 1 组关键词搜索即可，本轮可并行调用多个 search_issues。",
                    f"关键词应从任务标题中提取核心概念，不要用太长的短语。",
                ]
                if "academic" in effective_sources:
                    parts.append("同时调用 search_arxiv 搜索相关论文（用英文关键词）。")
                if "news" in effective_sources:
                    parts.append("同时调用 get_github_releases 获取 vllm-project/vllm 的最近 release。")
                return "\n".join(parts)
            return ""  # 后续搜索轮让 AI 自由发挥

        # 搜索阶段结束，进入深入阶段
        if detail_count == 0:
            return (
                "搜索阶段已完成。现在进入深入阶段。\n"
                "请从搜索结果中选出 5-8 个最相关的 issue/PR，调用 get_issue_detail 读取正文和评论。\n"
                "优先选择：1) RFC 类 issue（了解设计方向）2) 有较多评论的 issue（了解讨论热点）3) 与任务直接相关的 PR。\n"
                "本轮可并行调用多个 get_issue_detail。"
            )

        # 深入阶段中途：如果还没看 PR diff，引导看 1-2 个
        if detail_count == 1:
            return (
                "继续深入。如果搜索结果中有重要的 PR，可以调用 get_pr_diff 查看 1-2 个核心 PR 的代码变更。\n"
                "如果已经足够了解，可以直接生成报告（不再调用工具）。"
            )

        # 接近预算上限，引导生成报告
        remaining = MAX_TOOL_ROUNDS - round_num
        if remaining <= 2:
            return (
                "调研时间已不多。请基于已收集的信息直接生成完整的 Markdown 洞察报告，不要再调用工具。"
            )

        return ""

    def _single_shot_report(
        self, ai: AIAssistant, task_title: str, task_description: str,
        effective_sources: List[str], extra_prompt: str, github_repos: List[str],
    ) -> str:
        """回退模式：先批量搜索 GitHub + arXiv + releases，再让 AI 一次性生成报告"""
        sections = []
        for source in effective_sources:
            cfg = self.SOURCE_CONFIG.get(source, {})
            if cfg.get("type") == "github":
                items = self._search_github_for_report(source, task_title, task_description)
                sections.append(self._format_github_section(source, items))
            elif source == "academic":
                # 搜 arXiv
                arxiv_result = self._tool_search_arxiv({
                    "query": self._extract_keywords_en(task_title + " " + task_description),
                    "max_results": 5,
                })
                if arxiv_result.get("results"):
                    lines = ["学术动态:"]
                    for p in arxiv_result["results"][:5]:
                        lines.append(f"- {p['title']}")
                        lines.append(f"  作者: {', '.join(p.get('authors', [])[:3])}")
                        lines.append(f"  摘要: {p.get('summary', '')[:200]}")
                        lines.append(f"  URL: {p.get('url', '')}")
                    sections.append("\n".join(lines))
                else:
                    sections.append("学术动态: 未找到相关论文")
            elif source == "news":
                # 获取 vllm releases
                releases = self._tool_get_github_releases({"repo": "vllm-project/vllm", "per_page": 5})
                if releases.get("results"):
                    lines = ["新闻动态 (GitHub Releases):"]
                    for r in releases["results"][:5]:
                        lines.append(f"- {r['tag']} ({r.get('published_at', '')})")
                        lines.append(f"  {r.get('body', '')[:200]}")
                    sections.append("\n".join(lines))
                else:
                    sections.append("新闻动态: 无法获取 release 信息")

        sections_text = "\n\n".join(sections)
        extra_section = f"\n\n## 用户补充信息\n{extra_prompt}" if extra_prompt else ""

        prompt = f"""基于以下数据，生成一份结构化的洞察报告。

任务标题：{task_title}
任务描述：{task_description}

各来源数据：
{sections_text}
{extra_section}

请生成一份完整的 Markdown 格式洞察报告，包含摘要、各来源动态、AI 建议等章节。
要求：使用中文，内容要有实质价值，直接输出 Markdown，不要包裹在代码块中。
不要编造版本号或论文标题，只使用上面提供的真实数据。"""

        return ai._chat(prompt, max_tokens=4096, temperature=0.7)

    def _search_github_for_report(self, source: str, task_title: str, task_description: str) -> List[dict]:
        """回退模式用：搜索 GitHub issue/PR"""
        cfg = self.SOURCE_CONFIG.get(source, {})
        repos = cfg.get("repos", [])
        keywords = self._extract_keywords(task_title + " " + task_description)
        all_items = []
        for repo in repos:
            since = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
            query_parts = [f"repo:{repo}", f"created:>={since}"]
            if keywords:
                query_parts.extend(keywords[:5])
            try:
                items = self.client._search_issues(" ".join(query_parts)) or []
                all_items.extend(items[:20])
            except Exception:
                logger.exception(f"github search failed for {repo}")
        return all_items[:20]

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        stop_words = {
            "的", "了", "是", "在", "有", "和", "与", "或", "等", "这", "那",
            "个", "一", "不", "要", "需", "求", "the", "a", "an", "is", "are",
            "and", "or", "to", "for", "of", "with", "in", "on", "at",
        }
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+|[一-龥]{2,}", text)
        seen = set()
        result = []
        for w in words:
            wl = w.lower()
            if wl not in stop_words and len(w) > 1 and wl not in seen:
                seen.add(wl)
                result.append(w)
        return result[:10]

    def _extract_keywords_en(self, text: str) -> str:
        """提取英文关键词用于 arXiv 搜索（返回空格分隔的字符串）"""
        stop_words = {
            "the", "a", "an", "is", "are", "and", "or", "to", "for", "of",
            "with", "in", "on", "at", "by", "from", "this", "that", "it",
        }
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", text)
        seen = set()
        result = []
        for w in words:
            wl = w.lower()
            if wl not in stop_words and len(wl) > 1 and wl not in seen:
                seen.add(wl)
                result.append(w)
        return " ".join(result[:6])

    def _format_github_section(self, source: str, items: List[dict]) -> str:
        """回退模式用：格式化 GitHub 搜索结果"""
        display_name = self.SOURCE_CONFIG.get(source, {}).get("display_name", source)
        if not items:
            return f"{display_name}: 暂无相关动态"
        lines = [f"{display_name}:"]
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('title', '')} (#{item.get('number')})")
            lines.append(f"  状态: {item.get('state', 'unknown')}")
            url = item.get("html_url", "")
            if url:
                lines.append(f"  URL: {url}")
        return "\n".join(lines)

    def _build_system_prompt(
        self,
        task_title: str,
        task_description: str,
        effective_sources: List[str],
        extra_prompt: str,
        github_repos: List[str],
    ) -> str:
        """构建 system prompt"""
        source_descriptions = []
        for s in effective_sources:
            cfg = self.SOURCE_CONFIG.get(s, {})
            name = cfg.get("display_name", s)
            if cfg.get("type") == "github":
                repos = ", ".join(cfg.get("repos", []))
                source_descriptions.append(f"- {name}（GitHub 仓库: {repos}）")
            elif s == "academic":
                source_descriptions.append(f"- {name}（用户提供的论文信息，见下方补充）")
            elif s == "news":
                source_descriptions.append(f"- {name}（基于你的已有知识）")

        sources_text = "\n".join(source_descriptions) if source_descriptions else "无"
        repos_text = ", ".join(github_repos) if github_repos else "无"
        extra_section = f"\n\n## 用户补充信息\n{extra_prompt}" if extra_prompt else ""

        return f"""你是一位资深的 vLLM 社区贡献者和技术分析师。你的任务是为以下个人任务生成一份结构化的洞察报告。

## 任务信息
- 标题：{task_title}
- 描述：{task_description}{extra_section}

## 要调研的来源
{sources_text}

## 可用 GitHub 仓库
{repos_text}

## 工具说明
你有以下工具可用：
- **search_issues**：在 GitHub 仓库搜索 issue/PR。每轮可并行调用多个。
- **get_issue_detail**：读取 issue/PR 的正文和评论。每轮可并行调用多个。
- **get_pr_diff**：读取 PR 的 diff 内容。
- **search_arxiv**：搜索 arXiv 论文。用于学术动态调研，用英文关键词效果更好。
- **get_github_releases**：获取仓库最近的 release 列表。用于新闻动态，避免编造版本号。

## 工作原则
1. **搜索要高效**：每个仓库搜索 1-2 次即可，用核心关键词，不要用长句。不同轮用不同关键词。
2. **深入要聚焦**：搜索后选出 5-8 个最相关的条目读详情，优先 RFC issue 和高评论量的 issue。
3. **学术用 arXiv**：如果包含学术来源，用英文关键词调 search_arxiv 搜 1 次即可。
4. **新闻用 release**：如果包含新闻来源，调 get_github_releases 获取真实版本信息，不要编造版本号。
5. **报告要基于证据**：每个结论引用具体 issue/PR 编号或论文标题。不确定的内容不要编造。
6. **接受局限性**：你的搜索轮次有限，不可能遍历所有 issue/PR。对于未能深入调研的部分，在报告中提供 GitHub 搜索链接和关键词建议，让用户自行深入。这比假装覆盖了所有内容更有价值。
7. 会按阶段引导你：先搜索，再深入，最后生成报告。

## 报告格式
生成报告时（不再调用工具），直接输出以下 Markdown：

# {task_title} 相关动态洞察

## 摘要
一句话总结核心发现（不超过 50 字）

## 各来源动态
（根据实际来源生成对应章节，如 vLLM 社区动态、vLLM-Ascend 动态、竞品动态）
### 已调研的 Issue/PR
列出已通过 get_issue_detail 深入了解的 issue/PR，每个包含编号、标题、状态、关键内容摘要和链接
### 讨论热点
基于已读 issue 的正文和评论总结热点话题
### 进一步调研建议
列出未能深入但值得关注的线索，提供 GitHub 搜索链接。格式示例：
- 在 vllm-project/vllm 搜索更多相关 issue：[搜索链接](https://github.com/vllm-project/vllm/issues?q=关键词)
- 建议关注 label:kernel / label:performance 的 issue
- 建议用以下关键词在 GitHub 搜索：`triton kernel dispatch`、`platform abstraction`

## 学术动态
（基于 arXiv 搜索结果列出相关论文；如果用户提供了论文信息，分析其相关性）
### 进一步调研建议
提供 arXiv 搜索链接，如：https://arxiv.org/search/?query=关键词&searchtype=all

## 新闻动态
（基于 GitHub release 数据列出真实的版本发布信息；不要编造版本号）

## AI 建议
基于以上分析，给出 3-5 条具体、可执行的建议

## 要求
- 使用中文
- 内容要有实质价值，不要泛泛而谈
- 每条建议要具体可执行
- 引用 issue/PR 时带上编号和链接
- 直接输出 Markdown，不要包裹在代码块中
- 搜索时优先搜索近 90 天的内容
- 对于未覆盖的内容，主动提供搜索链接和关键词建议，不要假装覆盖全面
- GitHub 搜索链接格式：https://github.com/{{owner}}/{{repo}}/issues?q={{关键词}}
- arXiv 搜索链接格式：https://arxiv.org/search/?query={{关键词}}&searchtype=all"""

    def _execute_tool(self, name: str, args: dict) -> dict:
        """执行 AI 请求的 tool call"""
        try:
            if name == "search_issues":
                return self._tool_search_issues(args)
            elif name == "get_issue_detail":
                return self._tool_get_issue_detail(args)
            elif name == "get_pr_diff":
                return self._tool_get_pr_diff(args)
            elif name == "search_arxiv":
                return self._tool_search_arxiv(args)
            elif name == "get_github_releases":
                return self._tool_get_github_releases(args)
            else:
                return {"error": f"unknown tool: {name}"}
        except Exception as e:
            logger.exception(f"tool {name} failed")
            return {"error": str(e)}

    def _tool_search_issues(self, args: dict) -> dict:
        """搜索 issue/PR"""
        repo = args.get("repo", "")
        if not repo:
            return {"error": "repo is required"}

        query_parts = [f"repo:{repo}"]
        state = args.get("state", "all")
        if state in ("open", "closed"):
            query_parts.append(f"is:{state}")

        days_back = args.get("days_back", 90)
        if days_back:
            since = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
            query_parts.append(f"created:>={since}")

        keywords = args.get("query", "").strip()
        if keywords:
            query_parts.append(keywords)

        query = " ".join(query_parts)
        items = self.client._search_issues(query) or []

        # 只返回关键字段，避免 token 爆炸
        results = []
        for item in items[:15]:
            if not isinstance(item, dict):
                continue
            html_url = item.get("html_url", "")
            item_type = "pr" if "/pull/" in html_url else "issue"
            results.append({
                "number": item.get("number"),
                "title": item.get("title", ""),
                "state": item.get("state", "unknown"),
                "type": item_type,
                "created_at": item.get("created_at"),
                "comments": item.get("comments", 0),
                "url": html_url,
                "labels": [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)][:5],
            })

        return {"results": results, "total": len(items), "query": query}

    def _tool_get_issue_detail(self, args: dict) -> dict:
        """获取 issue/PR 正文"""
        repo = args.get("repo", "")
        number = args.get("number")
        if not repo or not number:
            return {"error": "repo and number are required"}

        # 临时构建 URL（支持任意仓库）
        url = f"https://api.github.com/repos/{repo}/issues/{number}"
        item = self.client._request_with_retry("GET", url)

        if not item or not isinstance(item, dict):
            return {"error": f"not found: {repo}#{number}"}

        # 获取评论（如果有）
        comments = []
        comment_count = item.get("comments", 0)
        if comment_count > 0:
            comments_url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
            raw_comments = self.client._request_with_retry("GET", comments_url, params={"per_page": 20})
            if isinstance(raw_comments, list):
                for c in raw_comments[:20]:
                    if isinstance(c, dict):
                        comments.append({
                            "author": (c.get("user") or {}).get("login", ""),
                            "body": (c.get("body") or "")[:500],  # 截断长评论
                            "created_at": c.get("created_at"),
                        })

        html_url = item.get("html_url", "")
        item_type = "pr" if "/pull/" in html_url else "issue"

        return {
            "number": item.get("number"),
            "title": item.get("title", ""),
            "state": item.get("state", "unknown"),
            "type": item_type,
            "body": (item.get("body") or "")[:3000],  # 截断长正文
            "author": (item.get("user") or {}).get("login", ""),
            "created_at": item.get("created_at"),
            "updated_at": item.get("updated_at"),
            "labels": [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)],
            "comments_count": comment_count,
            "comments": comments,
            "url": html_url,
        }

    def _tool_get_pr_diff(self, args: dict) -> dict:
        """获取 PR diff"""
        repo = args.get("repo", "")
        number = args.get("number")
        if not repo or not number:
            return {"error": "repo and number are required"}

        url = f"https://api.github.com/repos/{repo}/pulls/{number}"
        diff = self.client._request_with_retry(
            "GET", url, headers={"Accept": "application/vnd.github.v3.diff"}
        )
        if not isinstance(diff, str):
            return {"error": "diff not available"}

        # 截断长 diff
        return {
            "number": number,
            "repo": repo,
            "diff": diff[:6000],
            "truncated": len(diff) > 6000,
        }

    def _tool_search_arxiv(self, args: dict) -> dict:
        """搜索 arXiv 论文（免费 API，无需认证）"""
        import urllib.request
        import xml.etree.ElementTree as ET

        query = args.get("query", "").strip()
        if not query:
            return {"error": "query is required"}

        max_results = min(args.get("max_results", 5), 10)
        # arXiv API: http://export.arxiv.org/api/query?search_query=all:xxx&max_results=N
        encoded = urllib.parse.quote(query)
        url = f"http://export.arxiv.org/api/query?search_query=all:{encoded}&max_results={max_results}&sortBy=relevance"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vllm-assistant/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read().decode("utf-8")
        except Exception as e:
            return {"error": f"arxiv search failed: {e}"}

        # 解析 Atom XML
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_data)
        entries = root.findall("atom:entry", ns)

        results = []
        for entry in entries[:max_results]:
            title = (entry.findtext("atom:title", "", ns) or "").strip().replace("\n", " ")
            summary = (entry.findtext("atom:summary", "", ns) or "").strip().replace("\n", " ")
            published = entry.findtext("atom:published", "", ns)
            arxiv_url = entry.findtext("atom:id", "", ns)

            authors = []
            for author in entry.findall("atom:author", ns):
                name = author.findtext("atom:name", "", ns)
                if name:
                    authors.append(name)

            results.append({
                "title": title,
                "authors": authors[:5],
                "summary": summary[:500],
                "published": published,
                "url": arxiv_url,
            })

        return {"results": results, "query": query}

    def _tool_get_github_releases(self, args: dict) -> dict:
        """获取 GitHub 仓库最近的 release 列表"""
        repo = args.get("repo", "")
        if not repo:
            return {"error": "repo is required"}

        per_page = min(args.get("per_page", 5), 10)
        url = f"https://api.github.com/repos/{repo}/releases"
        releases = self.client._request_with_retry("GET", url, params={"per_page": per_page})

        if not isinstance(releases, list):
            return {"error": "releases not available"}

        results = []
        for r in releases[:per_page]:
            if not isinstance(r, dict):
                continue
            results.append({
                "tag": r.get("tag_name", ""),
                "name": r.get("name", ""),
                "published_at": r.get("published_at"),
                "prerelease": r.get("prerelease", False),
                "draft": r.get("draft", False),
                "body": (r.get("body") or "")[:1000],  # release notes 截断
                "url": r.get("html_url", ""),
            })

        return {"results": results, "repo": repo}

    def _resolve_sources(
        self, sources: List[str], excluded_sources: Optional[List[str]] = None
    ) -> List[str]:
        """解析最终使用的来源列表"""
        if excluded_sources:
            return [s for s in sources if s not in excluded_sources]
        return [s for s in sources if s in self.SOURCE_CONFIG]
