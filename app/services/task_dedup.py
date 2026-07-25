"""
任务去重检查器（DESIGN-PERSONAL-TODO.md 4.1）

策略：混合模式
1. 关键词提取 + GitHub Search API（快速过滤）
2. AI 语义相似度对比（精确判断）
"""
import json
import logging
import re
from typing import List, Dict

from app.services._shared import get_github_client
from app.services.ai_assistant import AIAssistant

logger = logging.getLogger(__name__)

# 简单中英文停用词
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "up", "about", "into", "through", "during", "before",
    "after", "above", "below", "between", "this", "that", "these", "those",
    "it", "its", "they", "them", "their", "we", "us", "our", "you", "your",
    "he", "she", "him", "her", "his", "hers",
    "的", "了", "是", "在", "有", "和", "与", "或", "等", "这", "那",
    "个", "一", "不", "要", "需", "求", "为", "以", "及",
    "进行", "可以", "需要", "应该", "可能", "存在", "使用", "实现",
    "支持", "的能力", "满足不同", "实现自定义",
}

# 常见拼写纠正
_SPELLING_FIXES = {
    "trition": "triton",
    "flahsattention": "flashattention",
    "flashattetnion": "flashattention",
    "kenerl": "kernel",
    "dispacth": "dispatch",
    "dispacher": "dispatcher",
    "platfrom": "platform",
    "atention": "attention",
}


class TaskDedupChecker:
    """任务去重检查器"""

    def __init__(self):
        self.client = get_github_client()
        self.ai = None  # lazy init

    def _get_ai(self) -> AIAssistant:
        if self.ai is None:
            self.ai = AIAssistant()
        return self.ai

    def check_duplicates(
        self,
        title: str,
        description: str,
        repos: List[str],
        check_type: str = "hybrid",
    ) -> List[Dict]:
        """检查是否有重复的 issue/PR

        Args:
            title: 任务标题
            description: 任务描述
            repos: 要检查的仓库列表（如 ["vllm-project/vllm"]）
            check_type: 'keyword' / 'semantic' / 'hybrid'

        Returns:
            匹配项列表，每项含 repo/type/number/title/state/similarity/reason/url
        """
        if not repos:
            return []

        # Step 1: 提取关键词（英文为主）
        keywords = self._extract_keywords(title, description)

        # Step 2: 生成多组搜索查询，对每个仓库执行搜索
        all_candidates: List[Dict] = []
        seen_numbers = set()
        for repo in repos:
            for query in self._build_search_queries(repo, keywords):
                candidates = self._search_repo(query, repo)
                for c in candidates:
                    num = c.get("number")
                    if num and num not in seen_numbers:
                        seen_numbers.add(num)
                        all_candidates.append(c)

        # Step 3: 根据 check_type 决定是否走 AI 语义对比
        if check_type == "keyword":
            results = self._keyword_matches(title, all_candidates)
        else:
            # semantic / hybrid: 先用关键词预筛，再让 AI 对比
            # 按标题关键词重叠度排序，把最相关的候选排在前面
            pre_ranked = self._rank_by_keyword_overlap(title, all_candidates)
            similar_items = self._ai_semantic_compare(title, description, pre_ranked[:20])

            # 补充 url / repo 字段（AI 返回只有 number/title/similarity/reason）
            candidate_map = {}
            for c in all_candidates:
                repo_name = self._extract_repo_name(c)
                candidate_map[(repo_name, c.get("number"))] = c

            results = []
            for item in similar_items:
                repo_name = item.get("repo") or self._guess_repo_from_candidates(item, all_candidates)
                num = item.get("item_number") or item.get("number")
                orig = candidate_map.get((repo_name, num)) or candidate_map.get((None, num))
                entry = {
                    "repo": repo_name,
                    "type": self._infer_type(orig) if orig else "issue",
                    "number": num,
                    "title": item.get("item_title") or item.get("title") or (orig or {}).get("title", ""),
                    "state": (orig or {}).get("state", "unknown"),
                    "similarity": item.get("similarity", "medium"),
                    "reason": item.get("reason", ""),
                    "url": (orig or {}).get("html_url", ""),
                }
                results.append(entry)

        # 标注是否为用户自己创建的（从 users 表获取第一个有 github_id 的用户）
        from app.models import User
        from app.database import SessionLocal
        try:
            _db = SessionLocal()
            first_user = _db.query(User).filter(User.github_id.isnot(None), User.github_id != "").first()
            _db.close()
        except Exception:
            first_user = None

        if first_user:
            username = first_user.github_id.lower()
            for entry in results:
                orig = next((c for c in all_candidates if c.get("number") == entry.get("number")), None)
                author = ""
                if orig:
                    author = ((orig.get("user") or {}).get("login") or "").lower()
                entry["is_mine"] = author == username if author else False

        return results

    def _extract_keywords(self, title: str, description: str) -> List[str]:
        """提取关键词用于搜索

        只保留英文关键词（GitHub Search API 对中文支持差），
        做拼写纠正，去停用词。
        """
        text = f"{title} {description}"
        # 只提取英文单词（GitHub Search 对中文支持差，中文词会导致返回 0 条）
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", text)
        keywords = []
        seen = set()
        for w in words:
            wl = w.lower()
            # 拼写纠正
            wl = _SPELLING_FIXES.get(wl, wl)
            if wl in _STOP_WORDS or len(wl) < 2:
                continue
            if wl in seen:
                continue
            seen.add(wl)
            keywords.append(wl)
        return keywords[:10]

    def _build_search_queries(self, repo: str, keywords: List[str]) -> List[str]:
        """构建多组搜索查询，提高召回率

        策略：
        1. 全部关键词组合（AND）
        2. 核心关键词两两组合（多组 OR）
        3. 标题关键词搜 in:title
        """
        if not keywords:
            return []

        queries = []

        # Query 1: 前 3 个关键词 AND
        queries.append(f"repo:{repo} " + " ".join(keywords[:3]))

        # Query 2: 前 2 个关键词（更宽松）
        if len(keywords) >= 2:
            queries.append(f"repo:{repo} " + " ".join(keywords[:2]))

        # Query 3: 第 1 个关键词 in:title（精确匹配标题）
        if keywords:
            queries.append(f"repo:{repo} {keywords[0]} in:title")

        # Query 4: 第 2-3 个关键词 in:title
        if len(keywords) >= 3:
            queries.append(f"repo:{repo} {keywords[1]} {keywords[2]} in:title")

        return queries

    def _search_repo(self, query: str, repo: str) -> List[Dict]:
        """在指定仓库搜索 issue/PR（通过 GitHub Search API）"""
        try:
            items = self.client._search_issues(query) or []
            # 给每项标注 repo
            for it in items:
                if isinstance(it, dict):
                    it.setdefault("_repo", repo)
            return items
        except Exception:
            logger.exception(f"dedup search failed: {query}")
            return []

    def _extract_repo_name(self, item: Dict) -> str:
        """从 search result 提取 repo 全名（owner/repo）"""
        if "_repo" in item:
            return item["_repo"]
        url = item.get("repository_url") or ""
        # https://api.github.com/repos/vllm-project/vllm
        if url:
            return url.replace("https://api.github.com/repos/", "")
        return ""

    def _infer_type(self, item: Dict) -> str:
        """从 search result 推断是 issue 还是 pr"""
        if not item:
            return "issue"
        # search API 返回的 pull_request 字段存在 => PR
        if item.get("pull_request"):
            return "pr"
        # html_url 包含 /pull/
        url = item.get("html_url") or ""
        if "/pull/" in url:
            return "pr"
        return "issue"

    def _rank_by_keyword_overlap(self, title: str, candidates: List[Dict]) -> List[Dict]:
        """按标题关键词重叠度排序候选，把最相关的排在前面

        GitHub Search API 默认按时间排序，最新的 issue 排前面，
        但最相关的不一定是最新的。这里按关键词重叠度重新排序。
        使用简单词干匹配（dispatch/dispatcher/dispatching 算同一个词）。
        """
        title_words = set(self._stem(w) for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", (title or "").lower()))
        if not title_words:
            return candidates

        def overlap_score(c):
            c_title = (c.get("title") or "").lower()
            c_words = set(self._stem(w) for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", c_title))
            return len(title_words & c_words)

        return sorted(candidates, key=overlap_score, reverse=True)

    @staticmethod
    def _stem(word: str) -> str:
        """简单词干提取：去掉常见英文后缀，让 dispatch/dispatcher/dispatching 匹配"""
        for suffix in ("ing", "tion", "ions", "er", "ers", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) > len(suffix) + 2:
                return word[:-len(suffix)]
        return word

    def _keyword_matches(self, title: str, candidates: List[Dict]) -> List[Dict]:
        """纯关键词模式：返回所有候选，标注 medium 相似度"""
        results = []
        title_lower = (title or "").lower()
        for c in candidates[:10]:
            c_title = (c.get("title") or "").lower()
            # 计算重叠词
            title_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", title_lower))
            c_words = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", c_title))
            overlap = title_words & c_words
            similarity = "high" if len(overlap) >= 3 else ("medium" if len(overlap) >= 1 else "low")
            repo_name = self._extract_repo_name(c)
            results.append({
                "repo": repo_name,
                "type": self._infer_type(c),
                "number": c.get("number"),
                "title": c.get("title", ""),
                "state": c.get("state", "unknown"),
                "similarity": similarity,
                "reason": f"关键词匹配：{', '.join(list(overlap)[:5])}" if overlap else "无关键词重叠",
                "url": c.get("html_url", ""),
            })
        return [r for r in results if r["similarity"] != "low"]

    def _guess_repo_from_candidates(self, item: Dict, candidates: List[Dict]) -> str:
        """AI 返回中可能没带 repo，尝试从候选列表里找到同 number 的项"""
        num = item.get("item_number") or item.get("number")
        for c in candidates:
            if c.get("number") == num:
                return self._extract_repo_name(c)
        return ""

    def _ai_semantic_compare(
        self, title: str, description: str, candidates: List[Dict]
    ) -> List[Dict]:
        """AI 语义相似度对比"""
        if not candidates:
            return []

        # 简化候选列表给 AI
        simplified = []
        for c in candidates:
            repo_name = self._extract_repo_name(c)
            simplified.append({
                "repo": repo_name,
                "number": c.get("number"),
                "title": c.get("title", ""),
                "state": c.get("state", "unknown"),
            })

        prompt = f"""比较以下任务描述与候选 issue/PR 的相似度。

任务标题：{title}
任务描述：{description}

候选列表：
{json.dumps(simplified, indent=2, ensure_ascii=False)}

返回 JSON 格式（不要 markdown 代码块，不要多余文字）：
{{
  "matches": [
    {{
      "repo": "vllm-project/vllm",
      "item_number": 123,
      "item_title": "...",
      "similarity": "high/medium/low",
      "reason": "为什么相似"
    }}
  ]
}}

只返回高度相似或中度相似的项目。"""

        try:
            ai = self._get_ai()
            result = ai._chat(prompt, max_tokens=2048, temperature=0.3)
            # AI 可能用 markdown 代码块包裹 JSON，需要剥离
            cleaned = result.strip()
            if cleaned.startswith("```"):
                # 去掉首尾的 ```json / ``` 行
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)
            # 尝试截取最后一个完整的 JSON 对象
            try:
                parsed = json.loads(cleaned)
            except (json.JSONDecodeError, TypeError):
                # JSON 可能被截断，尝试修复：补全缺失的括号
                parsed = self._repair_truncated_json(cleaned)
            if isinstance(parsed, dict):
                return parsed.get("matches", [])
            return []
        except Exception:
            logger.exception("AI semantic compare failed; falling back to keyword matches")
            return self._keyword_matches(title, candidates)

    @staticmethod
    def _repair_truncated_json(text: str) -> dict:
        """尝试修复被截断的 JSON（AI 回复可能因 max_tokens 不够而截断）"""
        text = text.strip()
        if not text:
            return {"matches": []}
        # 去掉 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        # 尝试逐层补全括号
        for repair in [
            text + "]}",
            text + "}",
            text + '"}]}',
            text + '"]}',
        ]:
            try:
                return json.loads(repair)
            except (json.JSONDecodeError, TypeError):
                continue
        # 最后尝试：找到最后一个完整的 } 截断
        last_brace = text.rfind("}")
        if last_brace > 0:
            truncated = text[:last_brace + 1]
            # 补全外层括号
            open_count = truncated.count("{") - truncated.count("}")
            open_brackets = truncated.count("[") - truncated.count("]")
            repair = truncated + "]" * open_brackets + "}" * open_count
            try:
                return json.loads(repair)
            except (json.JSONDecodeError, TypeError):
                pass
        return {"matches": []}
