"""
AI Assistant - OpenAI API 集成
提供 Review 意见生成、PR 影响范围分析等功能
"""
import json
import logging
from typing import List, Dict, Any

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

from app.config import Config

logger = logging.getLogger(__name__)


class AIAssistant:
    """AI 助手，基于 OpenAI API 提供智能建议"""

    # 统一超时（秒），所有 AI 调用都用
    # Review 需要处理 diff，耗时较长；summarize 较短
    DEFAULT_TIMEOUT = 120.0

    def __init__(self):
        if not OpenAI:
            raise ImportError("openai package is required")

        # 忽略环境变量中的代理（httpx 不支持 socks 协议），
        # 通过显式创建 httpx 客户端来避免代理冲突
        import httpx
        http_client = httpx.Client(proxy=None, timeout=self.DEFAULT_TIMEOUT, trust_env=False)
        self.client = OpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL,
            http_client=http_client,
        )
        self.model = Config.OPENAI_MODEL

    def _chat(self, prompt: str, max_tokens: int, temperature: float) -> str:
        """统一的 chat 调用 + 错误处理"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=self.DEFAULT_TIMEOUT,
            )
            content = response.choices[0].message.content
            if not content:
                logger.warning("AI returned empty content")
            return content or ""
        except Exception as e:
            logger.exception("AI chat call failed")
            raise

    def _safe_json(self, content: str, default: Any) -> Any:
        """解析 AI 返回的 JSON，失败时尝试自动修复常见格式错误"""
        if not content:
            return default
        # 尝试直接解析
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
        # 尝试修复常见问题：字段名缺少引号、值缺少引号、末尾逗号
        import re
        try:
            # 1. 去掉 markdown 代码块标记
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', content.strip())
            cleaned = re.sub(r'\n```\s*$', '', cleaned)
            # 2. 修复键名缺少引号：{key:  -> {"key":
            cleaned = re.sub(r'(?<=[{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'"\1":', cleaned)
            # 3. 修复值中未引用的字符串（在 : 之后、, 或 } 之前）
            #   先处理数组和对象嵌套，跳过
            # 4. 尝试再次解析
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError, re.error):
            return default

    def generate_review(
        self, pr_title: str, pr_diff: str, pr_number: int
    ) -> Dict[str, Any]:
        """
        基于PR diff生成结构化review意见

        Args:
            pr_title: PR标题
            pr_diff: PR的diff内容
            pr_number: PR编号

        Returns:
            {
                "summary": str,
                "code_quality": [...],
                "performance": [...],
                "tests": [...],
                "docs": [...],
            }
        """
        prompt = f"""你是一位资深 vLLM 贡献者，正在 review 一个 PR。

PR #{pr_number}: {pr_title}

PR Diff:
```diff
{pr_diff[:8000]}
```

请用中文给出结构化的 review 意见。**严格**返回以下 JSON 格式，不要 markdown 代码块，不要多余文字：

{{
  "summary": "一句话总体评价",
  "code_quality": [
    {{"severity": "critical", "title": "问题标题", "description": "详细说明"}}
  ],
  "performance": [
    {{"severity": "important", "title": "问题标题", "description": "详细说明"}}
  ],
  "tests": [
    {{"severity": "important", "title": "问题标题", "description": "详细说明"}}
  ],
  "docs": [
    {{"severity": "minor", "title": "问题标题", "description": "详细说明"}}
  ]
}}

规则：
- 所有字段必须是上述类型：summary 是字符串，其余 4 个字段都是数组
- 数组中每项必须是对象，含 severity（critical/important/minor）、title（简短标题）、description（详细说明）
- 如果某个方面没有问题，返回空数组 []
- 所有文字用中文，severity 值用英文"""

        try:
            content = self._chat(prompt, max_tokens=4096, temperature=0.7)
        except Exception as e:
            return {"error": str(e)}

        parsed = self._safe_json(content, None)
        if parsed is not None and isinstance(parsed, dict):
            return parsed
        # JSON 解析失败时，返回空结构化数据 + raw_response 兜底
        return {
            "summary": "AI 返回了内容但格式无法解析",
            "code_quality": [],
            "performance": [],
            "tests": [],
            "docs": [],
        }

    def analyze_impact(self, changed_files: List[str]) -> Dict[str, Any]:
        """
        分析PR影响范围

        Args:
            changed_files: 变更的文件列表

        Returns:
            {
                "affected_modules": [...],
                "potential_breaking_changes": bool,
                "test_requirements": [...],
                "cross_area_impact": [...],
            }
        """
        prompt = f"""Analyze the impact of these file changes in the vLLM project:

Changed files:
{json.dumps(changed_files, indent=2)}

Return JSON with:
1. affected_modules: List of module names that may be affected
2. potential_breaking_changes: Boolean indicating if breaking changes are likely
3. test_requirements: List of test files that may need updates
4. cross_area_impact: List of areas that may be affected

Consider vLLM's architecture:
- Engine core (scheduler, KV cache, distributed)
- Model implementation (attention, MoE, quantization)
- Entrypoints (API server, CLI)
- Hardware integration (GPU, CPU, TPU)

Return valid JSON only."""

        try:
            content = self._chat(prompt, max_tokens=2048, temperature=0.5)
        except Exception as e:
            return {"error": str(e)}

        parsed = self._safe_json(content, None)
        if parsed is not None:
            return parsed
        return {"error": "Failed to parse response", "raw_response": content}

    def suggest_labels(self, issue_title: str, issue_body: str) -> List[str]:
        """
        根据issue内容推荐标签和领域

        Args:
            issue_title: Issue标题
            issue_body: Issue正文

        Returns:
            推荐的标签列表
        """
        prompt = f"""Based on this vLLM issue, suggest appropriate labels and area.

Issue Title: {issue_title}
Issue Body: {issue_body[:2000]}

vLLM label categories:
- Type: bug, feature, enhancement, documentation
- Area: engine, model, entrypoints, kernels, hardware, config, multimodal, compilation, lora, docs, ci
- Status: good first issue, help wanted, priority: high

Return JSON with:
1. labels: List of suggested labels
2. area: Suggested area (engine/model/entrypoints/etc.)
3. reasoning: Brief explanation

Return valid JSON only."""

        try:
            content = self._chat(prompt, max_tokens=1024, temperature=0.5)
        except Exception as e:
            logger.warning(f"suggest_labels failed: {e}")
            return []

        parsed = self._safe_json(content, None)
        if isinstance(parsed, dict):
            return parsed.get("labels", []) or []
        return []

    def summarize(self, title: str, body: str, item_type: str) -> Dict[str, Any]:
        """为 issue 或 PR 生成结构化的中文摘要

        返回 dict，前端解析后渲染。仅本地展示，不做任何 GitHub 写操作。

        Args:
            title: 标题
            body: 正文（Markdown）
            item_type: 'issue' or 'pr'

        Returns:
            dict，格式：
            {
                "core_problem": "核心问题/目标",
                "key_points": ["要点1", "要点2"],
                "impact": "影响范围/价值",
                "risk": "潜在风险或注意事项"
            }
        """
        if not body:
            body = "(无正文)"
        kind = "Issue" if item_type == "issue" else "Pull Request"

        if item_type == "issue":
            prompt = f"""分析以下 vLLM Issue，给出结构化摘要。**严格**返回以下 JSON 格式，不要 markdown 代码块：

{{
  "core_problem": "这个 issue 报告了什么问题或提出了什么需求（1-2句）",
  "key_points": ["关键信息点1（如复现条件、环境、错误信息等）", "关键信息点2"],
  "impact": "对用户/项目的影响程度和范围",
  "risk": "如果不解决可能带来的风险，或处理时需要注意的点"
}}

标题：{title}

正文：
{body[:4000]}

要求：
- 中文输出
- core_problem 要具体，不要泛泛而谈
- key_points 提取 2-4 个最有价值的信息点
- impact 说明影响哪些用户群体或功能
- risk 如果无明显风险写"暂无"
- 不要客套话"""
        else:
            prompt = f"""分析以下 vLLM Pull Request，给出结构化摘要。**严格**返回以下 JSON 格式，不要 markdown 代码块：

{{
  "core_problem": "这个 PR 解决了什么问题或实现了什么功能（1-2句）",
  "key_points": ["实现要点1（如关键设计决策、算法选择等）", "实现要点2"],
  "impact": "对项目的影响：性能提升幅度、功能变化、兼容性等",
  "risk": "潜在风险：如边界条件未处理、性能回归风险、兼容性等"
}}

标题：{title}

正文：
{body[:4000]}

要求：
- 中文输出
- core_problem 要具体说明解决了什么问题
- key_points 提取 2-4 个关键技术实现要点
- impact 说明对 vLLM 的实际影响
- risk 如果无明显风险写"暂无"
- 不要客套话"""

        try:
            content = self._chat(prompt, max_tokens=512, temperature=0.3)
        except Exception as e:
            # fallback：返回简单文本格式
            return {"core_problem": f"[摘要生成失败: {e}]", "key_points": [], "impact": "", "risk": "暂无"}

        parsed = self._safe_json(content, None)
        if parsed is not None:
            return parsed
        # fallback：返回原始文本
        return {"core_problem": (content.strip()[:200] if content else "[无摘要]"), "key_points": [], "impact": "", "risk": "暂无"}

    def translate(self, text: str, item_type: str) -> str:
        """将 Issue/PR 正文翻译为中文"""
        if not text:
            return ""

        prompt = f"""你是一个 vLLM 项目的技术文档翻译专家。请将以下英文技术内容翻译成流畅的中文。

要求：
- 保持技术术语准确（如 Attention、KV Cache、Tensor Parallelism 等保留英文）
- 代码片段、变量名、路径名等保持原样
- 翻译要自然流畅，符合中文技术文档的表述习惯
- 只输出翻译结果，不要加任何解释或前言
- 如果原文是中文，原样返回

原文（{'Issue' if item_type == 'issue' else 'PR'} 描述）：
{text[:6000]}

翻译："""

        try:
            content = self._chat(prompt, max_tokens=4096, temperature=0.3)
            return content.strip() if content else text
        except Exception:
            logger.exception("translate failed")
            return text