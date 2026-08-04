"""
洞察报告生成器（DESIGN-PERSONAL-TODO.md 4.2）

Agent 模式：通过 OpenAI function calling，让 AI 自主决定搜索什么、
读取哪些 issue/PR 的正文和评论，多轮迭代后生成报告。
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from app.config import Config
from app.services.base_agent import BaseAgent
from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)

# Agent 各阶段轮次预算
MAX_TOOL_ROUNDS = 30

# ======================================================================
# 模版渲染
# ======================================================================

def _render_daily_template() -> str:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return render_prompt("daily_report", "template.md", today=today)






class IntelligenceReportGenerator(BaseAgent):
    """洞察报告生成器（Agent 模式）"""

    def __init__(self, db=None):
        super().__init__()
        self.db = db
        self._cached_source_config: Optional[dict] = None

    # ======================================================================
    # 工具白名单
    # ======================================================================

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
            "search_code",
            "read_local_code",
        ])

    # ======================================================================
    # 来源配置
    # ======================================================================

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

        has_slack_creds = bool(Config.SLACK_TOKEN and Config.SLACK_COOKIE)
        if not has_slack_creds:
            try:
                from app.database import SessionLocal
                from app.models import SlackConfig
                db_s = SessionLocal()
                try:
                    sc = db_s.query(SlackConfig).first()
                    if sc and sc.token and sc.cookie:
                        has_slack_creds = True
                finally:
                    db_s.close()
            except Exception:
                pass

        if has_slack_creds:
            config["slack"] = {
                "display_name": "Slack 社群讨论",
                "type": "slack",
                "description": "vLLM Slack 工作区各频道的讨论消息",
            }

        return config

    def _resolve_sources(
        self, sources: List[str], excluded_sources: Optional[List[str]] = None,
        source_config: Optional[dict] = None,
    ) -> List[str]:
        if source_config is None:
            source_config = self._get_source_config(self.db)
        if not sources:
            result = list(source_config.keys())
        else:
            result = [s for s in sources if s in source_config]
        if excluded_sources:
            result = [s for s in result if s not in excluded_sources]
        return result

    # ======================================================================
    # 报告生成入口
    # ======================================================================

    def generate_report(
        self,
        task_title: str,
        task_description: str,
        sources: List[str],
        excluded_sources: Optional[List[str]] = None,
        extra_prompt: str = "",
        is_daily: bool = False,
    ) -> Dict:
        """生成洞察报告（Agent 模式）"""
        source_config = self._get_source_config(self.db)
        effective_sources = self._resolve_sources(sources, excluded_sources, source_config)

        github_repos = []
        for s in effective_sources:
            cfg = source_config.get(s)
            if not cfg:
                continue
            if cfg.get("type") == "github":
                github_repos.extend(cfg.get("repos", []))

        system_prompt = self._build_system_prompt(
            task_title, task_description, effective_sources, extra_prompt, github_repos, source_config, is_daily=is_daily,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请开始调研并生成关于「{task_title}」的洞察报告。"},
        ]

        report_content = ""
        try:
            report_content = self._agent_loop(messages, github_repos, effective_sources)
        except Exception as e:
            err_str = str(e).lower()
            tools_unsupported = any(kw in err_str for kw in ("tool", "function_call", "not support", "unrecognized"))
            if tools_unsupported:
                logger.warning(f"Agent mode failed (likely tools unsupported), falling back to single-shot: {e}")
                report_content = self._single_shot_report(task_title, task_description, effective_sources, extra_prompt, github_repos, source_config)
            else:
                raise

        return {
            "content": report_content,
            "sources": effective_sources,
        }

    # ======================================================================
    # Agent 循环
    # ======================================================================

    def _agent_loop(self, messages: List[dict], github_repos: List[str], effective_sources: List[str]) -> str:
        """Agent 循环：分阶段引导 AI 搜索和阅读"""
        search_budget = max(len(github_repos), 3)
        detail_budget = MAX_TOOL_ROUNDS - search_budget - 1

        search_count = 0
        detail_count = 0

        for round_num in range(MAX_TOOL_ROUNDS):
            guidance = self._phase_guidance(
                round_num, search_count, detail_count,
                search_budget, detail_budget, github_repos, effective_sources
            )
            if guidance:
                messages.append({"role": "user", "content": guidance})

            try:
                import asyncio
                assistant_message, text_content = asyncio.run(self.llm.chat_async(
                    messages=messages,
                    tools=self.TOOLS,
                    max_tokens=Config.LLM_MAX_TOKENS,
                    temperature=0.3,
                ))
            except Exception as e:
                err_str = str(e).lower()
                if any(kw in err_str for kw in ("rate limit", "429", "too many requests")):
                    logger.warning(f"AI chat rate limited at round {round_num}, will retry: {e}")
                elif any(kw in err_str for kw in ("timeout", "timed out", "read timed out")):
                    logger.warning(f"AI chat timed out at round {round_num}, will retry: {e}")
                elif any(kw in err_str for kw in ("context length", "maximum context", "token limit", "max_tokens")):
                    logger.warning(f"AI chat context exceeded at round {round_num}, truncating history: {e}")
                    if len(messages) > 10:
                        system = messages[0]
                        messages = [system] + messages[-8:]
                        continue
                else:
                    logger.exception(f"AI chat failed at round {round_num}: {e}")
                raise

            msg = assistant_message
            tool_calls = msg.get("tool_calls")

            if not tool_calls:
                return text_content or ""

            has_search = any(tc["function"]["name"] == "search_issues" for tc in tool_calls)
            has_detail = any(tc["function"]["name"] in ("get_issue_detail", "get_pr_diff") for tc in tool_calls)
            if has_search:
                search_count += 1
            if has_detail:
                detail_count += 1

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

            # 并行执行 tool calls
            from concurrent.futures import ThreadPoolExecutor

            def _exec_one(tc):
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
                logger.info(f"Agent round {round_num} (search={search_count}, detail={detail_count}): {tool_name}({tool_args})")
                result = self.execute_tool_sync(tool_name, tool_args)
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
            _, final_text = asyncio.run(self.llm.chat_async(
                messages=messages,
                max_tokens=Config.LLM_MAX_TOKENS,
                temperature=0.5,
            ))
            return final_text or ""
        except Exception:
            logger.exception("Final report generation failed")
            return self._build_fallback_report(messages)

    def _phase_guidance(
        self, round_num: int, search_count: int, detail_count: int,
        search_budget: int, detail_budget: int, github_repos: List[str],
        effective_sources: List[str]
    ) -> str:
        """根据当前阶段返回引导消息"""
        if search_count < search_budget:
            if search_count == 0:
                repos_str = "、".join(github_repos)
                parts = [
                    f"现在进入搜索阶段。请对以下每个仓库分别搜索：{repos_str}",
                    "每个仓库用 1 组关键词搜索即可，本轮可并行调用多个 search_issues。",
                    "关键词应从任务标题中提取核心概念，不要用太长的短语。",
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
                if "slack" in effective_sources:
                    parts.append(
                        "同时调用 search_memory 搜索 Slack 社群讨论。"
                        "用关键词如 `vLLM Slack 讨论 问题`，指定 tags 参数为 `slack` 来筛选 Slack 内容。"
                    )
                return "\n".join(parts)
            return ""

        if detail_count == 0:
            return (
                "搜索阶段已完成。现在进入深入阶段。\n"
                "请从搜索结果中选出 5-8 个最相关的 issue/PR，调用 get_issue_detail 读取正文和评论。\n"
                "优先选择：1) RFC 类 issue（了解设计方向）2) 有较多评论的 issue（了解讨论热点）3) 与任务直接相关的 PR。\n"
                "本轮可并行调用多个 get_issue_detail。"
            )

        if detail_count == 1:
            return (
                "继续深入。如果搜索结果中有重要的 PR，可以调用 get_pr_diff 查看 1-2 个核心 PR 的代码变更。\n"
                "**做 SGLang 对比分析时，用 search_code 搜索本地代码验证 vLLM 是否已实现对应功能，搜到后调 read_local_code 读关键文件确认。**"
            )

        if detail_count == 5:
            return (
                "深入阶段已过半。请确认是否已覆盖以下关键任务：\n"
                "1) 所有核心 issue/PR 的正文和评论已阅读\n"
                "2) SGLang 对比分析中每个功能的 search_code 验证已完成\n"
                "3) 贡献机会已识别\n"
                "如果还有遗漏，请尽快补充。完成后即可生成报告。"
            )

        remaining = MAX_TOOL_ROUNDS - round_num
        if remaining <= 2:
            return "调研时间已不多。请基于已收集的信息直接生成完整的 Markdown 洞察报告，不要再调用工具。"

        return ""

    # ======================================================================
    # 单次回退模式
    # ======================================================================

    def _single_shot_report(
        self, task_title: str, task_description: str,
        effective_sources: List[str], extra_prompt: str, github_repos: List[str],
        source_config: dict,
    ) -> str:
        """回退模式：先批量搜索，再让 AI 一次性生成报告"""
        sections = []
        for source in effective_sources:
            try:
                cfg = source_config.get(source, {})
                if cfg.get("type") == "github":
                    items = self._search_github_for_report(source, task_title, task_description, source_config)
                    sections.append(self._format_github_section(source, items, source_config))
                elif source == "academic":
                    en_keywords = self._translate_keywords_to_en(task_title + " " + task_description)
                    arxiv_result = self.execute_tool_sync("search_arxiv", {
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
                    web_keywords = self._translate_keywords_to_en(task_title)
                    web_result = self.execute_tool_sync("search_web", {
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

                    source_config = self._get_source_config(self.db)
                    all_releases = []
                    for s, cfg in source_config.items():
                        if cfg.get("type") == "github":
                            for repo in cfg.get("repos", []):
                                releases = self.execute_tool_sync("get_github_releases", {"repo": repo, "per_page": 3})
                                if releases.get("results"):
                                    all_releases.extend(releases["results"])
                    if all_releases:
                        news_lines.append("")
                        news_lines.append("版本发布:")
                        for r in all_releases[:5]:
                            news_lines.append(f"- {r['tag']} ({r.get('published_at', '')})")
                            news_lines.append(f"  {r.get('body', '')[:200]}")
                    sections.append("\n".join(news_lines))
                elif source == "slack":
                    slack_result = self.execute_tool_sync("search_memory", {
                        "query": "vLLM Slack 讨论 问题",
                        "top_k": 10,
                        "tags": "slack",
                    })
                    if slack_result.get("results"):
                        lines = ["Slack 社群讨论:"]
                        for item in slack_result["results"][:10]:
                            lines.append(f"- {item.get('content', '')[:200]}")
                        sections.append("\n".join(lines))
                    else:
                        sections.append("Slack 社群讨论: 未找到相关内容（可能未配置 Slack 采集）")
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

        return self.llm.chat_sync(prompt, max_tokens=Config.LLM_MAX_TOKENS, temperature=0.7)

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
                from app.services._shared import get_github_client
                client = get_github_client()
                items = client._search_issues(" ".join(query_parts)) or []
                all_items.extend(items[:20])
            except Exception:
                logger.exception(f"github search failed for {repo}")
        return all_items[:20]

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
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

    @staticmethod
    def _extract_keywords_en(text: str) -> str:
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
        en_keywords = self._extract_keywords_en(text)
        if len(en_keywords.split()) >= 3:
            return en_keywords
        if not re.search(r"[一-鿿]", text):
            return en_keywords or text[:100]
        try:
            prompt = (
                "请将以下文本翻译成英文搜索关键词（只输出关键词本身，不要多余内容）：\n\n"
                f"{text}\n\n"
                "输出格式：用空格分隔的英文关键词，不超过 6 个词。"
            )
            result = self.llm.chat_sync(prompt, max_tokens=100, temperature=0.1)
            translated = result.strip().strip('"').strip("'").strip()
            if re.search(r"[a-zA-Z]{3,}", translated):
                return translated[:100]
        except Exception:
            logger.warning(f"LLM translation failed for '{text}', falling back to direct extraction")
        return en_keywords or text[:100]

    @staticmethod
    def _format_github_section(source: str, items: List[dict], source_config: dict) -> str:
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

    # ======================================================================
    # System Prompt 构建
    # ======================================================================

    def _build_system_prompt(
        self,
        task_title: str,
        task_description: str,
        effective_sources: List[str],
        extra_prompt: str,
        github_repos: List[str],
        source_config: dict,
        is_daily: bool = False,
) -> str:
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
            elif s == "slack":
                source_descriptions.append(f"- {name}（通过 search_memory 搜索 tags=slack 获取）")

        sources_text = "\n".join(source_descriptions) if source_descriptions else "无"
        repos_text = ", ".join(github_repos) if github_repos else "无"
        extra_section = f"\n\n## 用户补充信息\n{extra_prompt}" if extra_prompt else ""

        memory_context = self._build_memory_context(f"{task_title} {task_description}", top_k=5)

        if is_daily:
            return self._build_daily_system_prompt(
                task_title, task_description, sources_text, repos_text,
                memory_context,
            )

        return render_prompt("intelligence", "system_prompt.md",
            task_title=task_title,
            task_description=task_description,
            extra_section=extra_section,
            sources_text=sources_text,
            repos_text=repos_text,
            memory_context=memory_context,
        )

    def _build_daily_system_prompt(
        self,
        task_title: str,
        task_description: str,
        sources_text: str,
        repos_text: str,
        memory_context: str,
    ) -> str:
        return render_prompt("daily_report", "system_prompt.md",
            task_title=task_title,
            task_description=task_description,
            sources_text=sources_text,
            repos_text=repos_text,
            memory_context=memory_context,
            report_template=_render_daily_template(),
        )

    @staticmethod
    def _daily_report_template() -> str:
        return _render_daily_template()

    # ======================================================================
    # 降级报告
    # ======================================================================

    @staticmethod
    def _build_fallback_report(messages: List[dict]) -> str:
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