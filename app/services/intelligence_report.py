"""
洞察报告生成器（DESIGN-PERSONAL-TODO.md 4.2）

Agent 模式：通过 OpenAI function calling，让 AI 自主决定搜索什么、
读取哪些 issue/PR 的正文和评论，多轮迭代后生成报告。
"""
import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from app.config import Config
from app.services._shared import get_github_client
from app.services.llm import LLMClient

logger = logging.getLogger(__name__)

# Agent 各阶段轮次预算
# 阶段 1（搜索）：每仓库 1 轮，每轮可并行搜 2-3 个关键词变体
# 阶段 2（深入）：读 5-8 个最相关 issue/PR 的正文，可选 1-2 个 PR diff
# 阶段 3（补充）：如果某仓库结果太少，补充搜索
MAX_TOOL_ROUNDS = 10


class IntelligenceReportGenerator:
    """洞察报告生成器（Agent 模式）"""

    def __init__(self, db=None):
        self.client = get_github_client()
        self.llm: Optional[LLMClient] = None
        self.db = db
        self._cached_source_config: Optional[dict] = None

    @staticmethod
    def _parse_repo_url(clone_url: str) -> str:
        url = clone_url
        if url.endswith('.git'):
            url = url[:-4]
        parts = url.rstrip('/').split('/')
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return ""

    def _get_source_config(self, db=None) -> Dict[str, dict]:
        if self._cached_source_config is not None:
            return self._cached_source_config
        config = {}

        # 从 RepoCache 动态构建 GitHub 类型来源
        if db is not None:
            try:
                from app.models import RepoCache
                repos = db.query(RepoCache).filter(
                    RepoCache.status == "active"
                ).all()
                for r in repos:
                    owner_repo = self._parse_repo_url(r.clone_url)
                    if not owner_repo:
                        continue
                    config[r.repo] = {
                        "display_name": r.repo,
                        "repos": [owner_repo],
                        "type": "github",
                    }
            except Exception:
                logger.warning("Failed to load repos from RepoCache", exc_info=True)

        # 如果没有配置任何仓库，跳过 GitHub 来源（仅保留固定来源）
        # 固定来源
        config["academic"] = {
            "display_name": "学术动态",
            "type": "manual",
            "description": "用户手动提供的学术论文信息",
        }
        config["news"] = {
            "display_name": "新闻动态",
            "type": "web",
            "description": "行业新闻、版本发布信息",
        }

        return config

    # OpenAI function calling 的工具定义（引用 tools/registry 中的 schema）
    # 不再单独定义，复用已注册的工具 schema
    @property
    def TOOLS(self):
        from app.services.tools import registry as tool_registry
        return tool_registry.get_tool_schemas([
            "search_issues",
            "get_issue_detail",
            "get_pr_diff",
            "search_arxiv",
            "get_github_releases",
            "search_web",
            "extract_web_content",
            "search_docs",
            "search_memory",
        ])

    def _get_llm(self) -> LLMClient:
        if self.llm is None:
            self.llm = LLMClient()
        return self.llm

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
        source_config = self._get_source_config(self.db)

        effective_sources = self._resolve_sources(sources, excluded_sources, source_config)

        # 构建可用仓库列表
        github_repos = []
        for s in effective_sources:
            cfg = source_config.get(s)
            if not cfg:
                continue
            if cfg.get("type") == "github":
                github_repos.extend(cfg.get("repos", []))

        # 构建 system prompt
        system_prompt = self._build_system_prompt(
            task_title, task_description, effective_sources, extra_prompt, github_repos, source_config
        )

        # Agent 循环
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请开始调研并生成关于「{task_title}」的洞察报告。"},
        ]

        llm = self._get_llm()
        report_content = ""

        # 尝试 Agent 模式（function calling）；如果 API 不支持 tools，回退到单次模式
        try:
            report_content = self._agent_loop(llm, messages, github_repos, effective_sources)
        except Exception as e:
            # 如果是 tools 不支持的错误，回退到单次模式
            err_str = str(e).lower()
            tools_unsupported = any(kw in err_str for kw in ("tool", "function_call", "not support", "unrecognized"))
            if tools_unsupported:
                logger.warning(f"Agent mode failed (likely tools unsupported), falling back to single-shot: {e}")
                report_content = self._single_shot_report(llm, task_title, task_description, effective_sources, extra_prompt, github_repos, source_config)
            else:
                raise

        return {
            "content": report_content,
            "sources": effective_sources,
        }

    def _agent_loop(self, llm: LLMClient, messages: List[dict], github_repos: List[str], effective_sources: List[str]) -> str:
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
                import asyncio
                assistant_message, text_content = asyncio.run(llm.chat_async(
                    messages=messages,
                    tools=self.TOOLS,
                    max_tokens=Config.LLM_MAX_TOKENS,
                    temperature=0.3,
                ))
            except Exception as e:
                err_str = str(e).lower()
                # 区分不同异常类型，给出更精确的日志
                if any(kw in err_str for kw in ("rate limit", "429", "too many requests")):
                    logger.warning(f"AI chat rate limited at round {round_num}, will retry: {e}")
                elif any(kw in err_str for kw in ("timeout", "timed out", "read timed out")):
                    logger.warning(f"AI chat timed out at round {round_num}, will retry: {e}")
                elif any(kw in err_str for kw in ("context length", "maximum context", "token limit", "max_tokens")):
                    logger.warning(f"AI chat context exceeded at round {round_num}, truncating history: {e}")
                    # 截断历史消息（保留 system + 最近 4 轮的对话 + tool 结果）
                    if len(messages) > 10:
                        system = messages[0]
                        messages = [system] + messages[-8:]
                        continue
                else:
                    logger.exception(f"AI chat failed at round {round_num}: {e}")
                raise

            msg = assistant_message
            tool_calls = msg.get("tool_calls")

            # 如果没有 tool_calls，说明 AI 已完成（直接返回了报告）
            if not tool_calls:
                return text_content or ""

            # 统计本轮调用的工具类型
            has_search = any(tc["function"]["name"] == "search_issues" for tc in tool_calls)
            has_detail = any(tc["function"]["name"] in ("get_issue_detail", "get_pr_diff") for tc in tool_calls)
            if has_search:
                search_count += 1
            if has_detail:
                detail_count += 1

            # 把 assistant 的 tool_calls 消息加入历史
            messages.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ],
            })

            # 并行执行本轮所有 tool calls（GitHub API 请求互不依赖）
            from concurrent.futures import ThreadPoolExecutor

            def _exec_one(tc):
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
                # 剔除 schema 未声明的字段，避免噪声字段影响执行
                declared = self._get_declared_tool_props(tool_name)
                if declared is not None:
                    tool_args = {k: v for k, v in tool_args.items() if k in declared}
                logger.info(f"Agent round {round_num} (search={search_count}, detail={detail_count}): {tool_name}({tool_args})")
                result = self._execute_tool(tool_name, tool_args)
                return tc["id"], json.dumps(result, ensure_ascii=False)

            with ThreadPoolExecutor(max_workers=min(len(tool_calls), 5)) as pool:
                futures = [pool.submit(_exec_one, tc) for tc in tool_calls]
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
            import asyncio
            _, final_text = asyncio.run(llm.chat_async(
                messages=messages,
                max_tokens=Config.LLM_MAX_TOKENS,
                temperature=0.5,
            ))
            return final_text or ""
        except Exception:
            logger.exception("Final report generation failed")
            # 返回已有数据摘要作为降级结果
            return self._build_fallback_report(messages)

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
                # 第一轮：引导按仓库逐个搜索 + arxiv + releases + web
                repos_str = "、".join(github_repos)
                parts = [
                    f"现在进入搜索阶段。请对以下每个仓库分别搜索：{repos_str}",
                    f"每个仓库用 1 组关键词搜索即可，本轮可并行调用多个 search_issues。",
                    f"关键词应从任务标题中提取核心概念，不要用太长的短语。",
                ]
                if "academic" in effective_sources:
                    parts.append(
                        "同时调用 search_arxiv 搜索相关论文。"
                        "**注意：arXiv 搜索必须用英文关键词。**"
                        "如果任务标题包含中文，请先将其翻译成英文核心关键词再搜索。"
                        "例如「vLLM 推理性能优化」→ 搜索 `vLLM inference performance optimization`。"
                    )
                if "news" in effective_sources:
                    parts.append(
                        "同时调用 search_web 搜索行业新闻。"
                        "搜索关键词用英文效果更好，如 `vLLM latest news`、`LLM inference framework`。"
                        "如果搜索结果中有感兴趣的文章，可以进一步调用 extract_web_content 提取正文。"
                    )
                    parts.append(
                        f"同时调用 get_github_releases 获取 {github_repos[0] if github_repos else '已配置仓库'} 的最近 release。"
                    )
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
        self, llm: LLMClient, task_title: str, task_description: str,
        effective_sources: List[str], extra_prompt: str, github_repos: List[str],
        source_config: dict,
    ) -> str:
        """回退模式：先批量搜索 GitHub + arXiv + web + releases，再让 AI 一次性生成报告"""
        sections = []
        for source in effective_sources:
            try:
                cfg = source_config.get(source, {})
                if cfg.get("type") == "github":
                    items = self._search_github_for_report(source, task_title, task_description, source_config)
                    sections.append(self._format_github_section(source, items, source_config))
                elif source == "academic":
                    # 先用 LLM 将中文关键词翻译成英文
                    en_keywords = self._translate_keywords_to_en(task_title + " " + task_description)
                    arxiv_result = self._tool_search_arxiv({
                        "query": en_keywords,
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
                    # 1. 用 search_web 搜索行业新闻
                    web_keywords = self._translate_keywords_to_en(task_title)
                    web_result = self._execute_tool("search_web", {
                        "query": web_keywords,
                        "max_results": 5,
                    })
                    news_lines = ["新闻动态 (行业新闻 + GitHub Releases):"]
                    if web_result and not web_result.get("error") and web_result.get("results"):
                        for r in web_result["results"][:5]:
                            url = r.get("url", "")
                            title = r.get("title", "")
                            snippet = r.get("content", "")[:200]
                            if url and title:
                                news_lines.append(f"- [{title}]({url})")
                                if snippet:
                                    news_lines.append(f"  {snippet}")
                    else:
                        news_lines.append("  (web 搜索未配置或不可用，以下仅展示 GitHub release 信息)")

                    # 2. 获取所有 GitHub 仓库的 releases
                    # 从动态配置中收集所有 GitHub 仓库
                    source_config = self._get_source_config(self.db)
                    all_releases = []
                    for s, cfg in source_config.items():
                        if cfg.get("type") == "github":
                            for repo in cfg.get("repos", []):
                                releases = self._tool_get_github_releases({"repo": repo, "per_page": 3})
                                if releases.get("results"):
                                    all_releases.extend(releases["results"])
                    if all_releases:
                        news_lines.append("")
                        news_lines.append("版本发布:")
                        for r in all_releases[:5]:
                            news_lines.append(f"- {r['tag']} ({r.get('published_at', '')})")
                            news_lines.append(f"  {r.get('body', '')[:200]}")
                    sections.append("\n".join(news_lines))
            except Exception:
                logger.exception(f"Failed to collect data from source '{source}' in single-shot mode")
                display_name = source_config.get(source, {}).get("display_name", source)
                sections.append(f"{display_name}: 数据收集失败")

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

        return llm.chat_sync(prompt, max_tokens=Config.LLM_MAX_TOKENS, temperature=0.7)

    def _search_github_for_report(self, source: str, task_title: str, task_description: str, source_config: dict) -> List[dict]:
        """回退模式用：搜索 GitHub issue/PR"""
        cfg = source_config.get(source, {})
        repos = cfg.get("repos", [])
        keywords = self._extract_keywords(task_title + " " + task_description)
        all_items = []
        for repo in repos:
            since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    def _translate_keywords_to_en(self, text: str) -> str:
        """用 LLM 将（可能含中文的）文本翻译成英文关键词

        如果文本中已有足够英文关键词，直接提取；否则调用 LLM 翻译。

        Returns:
            英文关键词字符串（空格分隔）
        """
        # 先尝试直接提取英文关键词
        en_keywords = self._extract_keywords_en(text)
        # 如果提取到的英文关键词足够多（>=3个词），直接使用
        if len(en_keywords.split()) >= 3:
            return en_keywords

        # 检测是否包含中文字符
        if not re.search(r"[一-鿿]", text):
            # 没有中文，用已有的英文关键词
            return en_keywords or text[:100]

        # 用 LLM 翻译
        try:
            llm = self._get_llm()
            prompt = (
                "请将以下文本翻译成英文搜索关键词（只输出关键词本身，不要多余内容）：\n\n"
                f"{text}\n\n"
                "输出格式：用空格分隔的英文关键词，不超过 6 个词。"
            )
            result = llm.chat_sync(prompt, max_tokens=100, temperature=0.1)
            translated = result.strip()
            # 清理：去掉可能的引号、换行、多余空格
            translated = translated.strip('"').strip("'").strip()
            # 如果翻译结果看起来有效（包含英文字母）
            if re.search(r"[a-zA-Z]{3,}", translated):
                return translated[:100]
        except Exception:
            logger.warning(f"LLM translation failed for '{text}', falling back to direct extraction")

        # 降级：返回直接提取的英文关键词
        return en_keywords or text[:100]

    def _format_github_section(self, source: str, items: List[dict], source_config: dict) -> str:
        """回退模式用：格式化 GitHub 搜索结果"""
        display_name = source_config.get(source, {}).get("display_name", source)
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
        source_config: dict,
    ) -> str:
        """构建 system prompt，注入知识库相关记忆"""
        source_descriptions = []
        for s in effective_sources:
            cfg = source_config.get(s, {})
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

        # 从知识库召回相关记忆
        memory_context = ""
        try:
            from app.services.memory_service import MemoryService
            query = f"{task_title} {task_description}"
            if query.strip():
                memories = MemoryService().recall(query=query, top_k=5)
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
                    memory_context = "\n\n## 知识库相关记录\n" + "\n\n".join(memory_lines)
        except Exception:
            logger.warning("Failed to recall memories for report generation", exc_info=True)

        return f"""你是一位资深的开源社区贡献者和技术分析师。你的任务是为以下个人任务生成一份结构化的洞察报告。

## 任务信息
- 标题：{task_title}
- 描述：{task_description}{extra_section}

## 要调研的来源
{sources_text}

## 可用 GitHub 仓库
{repos_text}
{memory_context}

## 工具说明
你有以下工具可用：
- **search_issues**：在 GitHub 仓库搜索 issue/PR。每轮可并行调用多个。
- **get_issue_detail**：读取 issue/PR 的正文和评论。每轮可并行调用多个。
- **get_pr_diff**：读取 PR 的 diff 内容。
- **search_arxiv**：搜索 arXiv 论文。用于学术动态调研，**必须用英文关键词**。
- **get_github_releases**：获取仓库最近的 release 列表。用于新闻动态，避免编造版本号。
- **search_web**：在互联网上搜索行业新闻、技术文章、博客等。用于了解业界动态、竞品信息。
  - 默认使用 Tavily 兼容协议，无需额外配置。
- **extract_web_content**：从指定 URL 提取清洁的文本内容。当搜索结果中的某篇文章需要深入了解时，用此工具获取完整正文。

## 工作原则
1. **搜索要高效**：每个仓库搜索 1-2 次即可，用核心关键词，不要用长句。不同轮用不同关键词。
2. **深入要聚焦**：搜索后选出 5-8 个最相关的条目读详情，优先 RFC issue 和高评论量的 issue。
3. **学术用 arXiv**：如果包含学术来源，用英文关键词调 search_arxiv 搜 1 次即可。**如果任务标题是中文，请先将其翻译成英文关键词再搜索**。
4. **新闻用 search_web + release**：如果包含新闻来源，先用 search_web 搜索行业新闻，再调 get_github_releases 获取真实版本信息，不要编造版本号。
5. **报告要基于证据**：每个结论引用具体 issue/PR 编号或论文标题。不确定的内容不要编造。
6. **接受局限性**：你的搜索轮次有限，不可能遍历所有 issue/PR。对于未能深入调研的部分，在报告中提供 GitHub 搜索链接和关键词建议，让用户自行深入。这比假装覆盖了所有内容更有价值。
7. 会按阶段引导你：先搜索，再深入，最后生成报告。

## 报告格式
生成报告时（不再调用工具），直接输出以下 Markdown：

# {task_title} 相关动态洞察

## 摘要
一句话总结核心发现（不超过 50 字）

## 各来源动态
（根据实际来源生成对应章节，如项目 A 社区动态、项目 B 社区动态、竞品动态）
### 已调研的 Issue/PR
列出已通过 get_issue_detail 深入了解的 issue/PR，每个包含编号、标题、状态、关键内容摘要和链接
### 讨论热点
基于已读 issue 的正文和评论总结热点话题
### 进一步调研建议
列出未能深入但值得关注的线索，提供 GitHub 搜索链接。格式示例：
- 在 GitHub 搜索更多相关 issue：[搜索链接](https://github.com/search?q=is%3Aissue+关键词&type=issues)
- 建议关注 label:kernel / label:performance 的 issue

## 学术动态
（基于 arXiv 搜索结果列出相关论文；如果用户提供了论文信息，分析其相关性）
### 进一步调研建议
提供 arXiv 搜索链接，如：https://arxiv.org/search/?query=关键词&searchtype=all

## 新闻动态
（基于 GitHub release 数据和 web 搜索到的行业新闻，列出真实的版本发布信息和业界动态；不要编造版本号）

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

    @staticmethod
    def _build_fallback_report(messages: List[dict]) -> str:
        """在最终报告生成失败时，从已有对话历史中提取数据构造降级报告

        遍历 tool 消息结果，收集已搜索到的 issue/PR 信息作为降级输出。
        """
        parts = ["# 洞察报告（降级版：AI 最终生成失败，基于已有数据自动汇总）\n"]
        seen_issues = set()

        for msg in messages:
            if msg.get("role") != "tool":
                continue
            try:
                data = json.loads(msg.get("content", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict):
                continue

            # 提取搜索结果中的 issue/PR 列表
            results = data.get("results")
            if isinstance(results, list):
                for r in results:
                    if isinstance(r, dict):
                        num = r.get("number")
                        if num and num not in seen_issues:
                            seen_issues.add(num)
                            title = r.get("title", "")
                            state = r.get("state", "")
                            url = r.get("url", "")
                            parts.append(f"- {title} (#{num}, {state})")
                            if url:
                                parts.append(f"  {url}")

        if len(parts) == 1:
            parts.append("（无法从对话历史中提取有效数据）")

        parts.append(f"\n\n---\n*共搜索到 {len(seen_issues)} 个相关 issue/PR*")
        return "\n".join(parts)

    def _execute_tool(self, name: str, args: dict) -> dict:
        """执行 AI 请求的 tool call

        优先通过工具注册表执行（异步），注册表中没有的再走自带的遗留同步实现。
        """
        try:
            # 优先使用工具注册表（与 AgentRunner 共享一套工具逻辑）
            from app.services.tools import registry as tool_registry
            import asyncio
            result = asyncio.run(tool_registry.execute_tool(name, args))
            if result is not None:
                return result
            # 注册表返回 None 表示未找到该工具，走遗留分支
            return self._execute_tool_legacy(name, args)
        except Exception as e:
            logger.exception(f"tool {name} failed")
            return {"error": str(e)}

    def _execute_tool_legacy(self, name: str, args: dict) -> dict:
        """遗留工具执行分支（不在注册表中的工具）"""
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
        if state == "merged":
            query_parts.append("is:pr")
            query_parts.append("is:merged")
        elif state in ("open", "closed"):
            query_parts.append(f"is:{state}")

        days_back = args.get("days_back", 90)
        if days_back:
            since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
            query_parts.append(f"created:>={since}")

        keywords = args.get("query", "").strip()
        if keywords:
            query_parts.append(keywords)

        # 搜索条数上限（AI 有轮次限制，返回太多会导致选择困难）
        SEARCH_LIMIT = 20

        query = " ".join(query_parts)
        result = self.client._search_issues_with_count(query)
        items = result.get("items") or []
        total_count = result.get("total_count", len(items))

        # 只返回关键字段，避免 token 爆炸
        results = []
        for item in items[:SEARCH_LIMIT]:
            if not isinstance(item, dict):
                continue
            html_url = item.get("html_url", "")
            item_type = "pr" if "/pull/" in html_url else "issue"
            results.append({
                "number": item.get("number"),
                "title": item.get("title", ""),
                "state": item.get("state", "unknown"),
                "type": item_type,
                "merged": item.get("merged", False),  # 搜索 API 可能不返回此字段，默认为 False
                "created_at": item.get("created_at"),
                "comments": item.get("comments", 0),
                "url": html_url,
                "labels": [l.get("name") for l in item.get("labels", []) if isinstance(l, dict)][:5],
            })

        return {
            "results": results,
            "total": min(total_count, SEARCH_LIMIT),
            "total_count": total_count,
            "query": query,
            "truncated": total_count > SEARCH_LIMIT,
        }

    def _get_allowed_repos(self) -> list:
        """获取所有允许的 GitHub 仓库列表"""
        source_config = self._get_source_config(self.db)
        repos = []
        for cfg in source_config.values():
            repos.extend(cfg.get("repos", []))
        return repos

    def _validate_repo(self, repo: str) -> bool:
        """验证仓库名是否在允许列表中"""
        return repo in self._get_allowed_repos()

    def _tool_get_issue_detail(self, args: dict) -> dict:
        """获取 issue/PR 正文"""
        repo = args.get("repo", "")
        number = args.get("number")
        if not repo or not number:
            return {"error": "repo and number are required"}
        if not self._validate_repo(repo):
            return {"error": f"repo '{repo}' is not in the allowed list"}

        # 先通过 issues 端点获取基本信息
        url = f"https://api.github.com/repos/{repo}/issues/{number}"
        item = self.client._request_with_retry("GET", url)

        if not item or not isinstance(item, dict):
            return {"error": f"not found: {repo}#{number}"}

        html_url = item.get("html_url", "")
        item_type = "pr" if "/pull/" in html_url else "issue"

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

        # 如果是 PR，从 pulls 端点获取合并状态（issues API 不返回 merged 字段）
        merged = False
        if item_type == "pr":
            try:
                pr_url = f"https://api.github.com/repos/{repo}/pulls/{number}"
                pr_data = self.client._request_with_retry("GET", pr_url)
                if isinstance(pr_data, dict):
                    merged = pr_data.get("merged", False)
            except Exception:
                logger.warning(f"Failed to fetch PR merge status for {repo}#{number}")

        return {
            "number": item.get("number"),
            "title": item.get("title", ""),
            "state": item.get("state", "unknown"),
            "merged": merged,  # PR 是否已合并（比 state 更准确），issues API 不返回此字段
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
        if not self._validate_repo(repo):
            return {"error": f"repo '{repo}' is not in the allowed list"}

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
        url = f"https://export.arxiv.org/api/query?search_query=all:{encoded}&max_results={max_results}&sortBy=relevance"

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

    @staticmethod
    def _get_declared_tool_props(tool_name: str):
        """从 tool schema 里取出声明的属性名集合。

        用来在执行前剔除模型塞进来的 schema 外字段，避免噪声字段导致执行异常。
        """
        from app.services.tools._shared import get_declared_tool_props
        return get_declared_tool_props(tool_name)

    def _resolve_sources(
        self, sources: List[str], excluded_sources: Optional[List[str]] = None,
        source_config: Optional[dict] = None,
    ) -> List[str]:
        """解析最终使用的来源列表。空列表表示用全部可用来源。"""
        if source_config is None:
            source_config = self._get_source_config(self.db)
        # 空 sources 表示用全部来源
        if not sources:
            result = list(source_config.keys())
        else:
            # 只保留已知的 source
            result = [s for s in sources if s in source_config]
        if excluded_sources:
            result = [s for s in result if s not in excluded_sources]
        return result
