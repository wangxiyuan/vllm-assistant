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
from app.services.llm import LLMClient
from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)

# ======================================================================
# 模版渲染
# ======================================================================

def _render_daily_template() -> str:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return render_prompt("daily_report", "template.md", today=today)






class IntelligenceReportGenerator:
    """洞察报告生成器（Agent 模式，基于 OpenAI Agents SDK 三阶段流水线）"""

    def __init__(self, db=None):
        self.db = db
        self.llm = LLMClient()
        self._cached_source_config: Optional[dict] = None

    def single_shot_report_for_sdk(
        self, task_title: str, task_description: str,
        effective_sources: List[str], extra_prompt: str,
        github_repos: List[str], source_config: dict,
    ) -> str:
        """给 agent_sdk.report 使用的单次回退入口（复用 _single_shot_report）。"""
        return self._single_shot_report(
            task_title, task_description, effective_sources, extra_prompt,
            github_repos, source_config,
        )

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

        has_slack_creds = False
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
        report_id: Optional[int] = None,
    ) -> Dict:
        """生成洞察报告（Agent 模式，三阶段流水线，委托给 agent_sdk.report）"""
        from app.services.agent_sdk.report import generate_report_sync
        return generate_report_sync(
            task_title=task_title,
            task_description=task_description,
            sources=sources,
            excluded_sources=excluded_sources,
            extra_prompt=extra_prompt,
            is_daily=is_daily,
            db=self.db,
            report_id=report_id,
            gen=self,
        )

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
                    arxiv_result = execute_tool_sync("search_arxiv", {
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
                    web_result = execute_tool_sync("search_web", {
                        "query": web_keywords,
                        "max_results": 5,
                    })
                    news_lines = ["新闻动态 (行业新闻 + GitHub Releases):"]
                    if web_result and not web_result.get("error") and web_result.get("results"):
                        for r in web_result["results"][:5]:
                            url = r.get("url", "")
                            title = r.get("title", "")
                            snippet = r.get("content", "")[:200]
                            published = r.get("published_date", r.get("date", ""))
                            if url and title:
                                news_lines.append(f"- [{title}]({url})")
                                if published:
                                    news_lines.append(f"  发布时间: {published}")
                                if snippet:
                                    news_lines.append(f"  {snippet}")
                    else:
                        news_lines.append("  (web 搜索未配置或不可用，以下仅展示 GitHub release 信息)")

                    source_config = self._get_source_config(self.db)
                    all_releases = []
                    for s, cfg in source_config.items():
                        if cfg.get("type") == "github":
                            for repo in cfg.get("repos", []):
                                releases = execute_tool_sync("get_github_releases", {"repo": repo, "per_page": 3})
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
                    slack_result = execute_tool_sync("search_by_tags", {
                        "tags": "slack",
                        "top_k": 15,
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

        prompt = f"""基于以下数据，围绕给定主题生成一份有洞察的分析报告。

报告主题：{task_title}
主题说明/背景：{task_description}

调研得到的数据：
{sections_text}
{extra_section}

【核心】报告的结构与逻辑必须由主题主导，而不是套固定的社区扫描模板。
动笔前先想清楚：这个主题要回答什么问题、面向谁、期望的产出形态（解析、规划梳理、优劣势对比、决策建议等），
据此设计最贴切的章节结构。除摘要外不强制固定章节。
请围绕主题组织内容，聚焦主题，不要泛泛罗列无关内容。

要求：使用中文，直接输出 Markdown，不要包裹在代码块中；内容要有实质价值。
不要编造版本号或论文标题，只使用上面提供的真实数据。
**重要：不要编造任何新闻、事件、会议或演讲信息。所有新闻必须有上面数据中提供的 URL 来源。没有 URL 来源的信息一律不写。**"""

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

    def _build_memory_context(self, query: str, top_k: int = 5) -> str:
        """从知识库召回相关记忆，返回格式化文本。"""
        from app.services.agent_prompt import build_memory_context
        return build_memory_context(query, top_k=top_k)

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