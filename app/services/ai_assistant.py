"""
AI Assistant - OpenAI API 集成
提供 Review 意见生成、摘要、翻译等功能
"""
import logging
import re

from app.config import Config
from app.services.llm import LLMClient
from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)


class AIAssistant:
    """AI 助手，基于 OpenAI API 提供智能建议"""

    def __init__(self):
        self.llm = LLMClient()
        self.model = Config.OPENAI_MODEL

    def generate_review(
        self, pr_title: str, pr_diff: str, pr_number: int
    ) -> str:
        """
        基于PR diff生成 markdown 格式的 review 意见

        Args:
            pr_title: PR标题
            pr_diff: PR的diff内容
            pr_number: PR编号

        Returns:
            markdown 格式的 review 字符串
        """
        prompt = render_prompt("assistant", "review.md",
            pr_number=pr_number,
            pr_title=pr_title,
            pr_diff=pr_diff[:8000],
        )

        try:
            content = self.llm.chat_sync(prompt, max_tokens=Config.LLM_MAX_TOKENS, temperature=0.7)
        except Exception as e:
            return f"**Review 生成失败**：{e}"

        if content and content.strip():
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:markdown)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            return content.strip()
        return "*暂无 Review 内容*"

    def summarize(self, title: str, body: str, item_type: str) -> str:
        """为 issue 或 PR 生成 markdown 格式的中文摘要

        返回 markdown 字符串，前端用 marked 渲染。仅本地展示，不做任何 GitHub 写操作。

        Args:
            title: 标题
            body: 正文（Markdown）
            item_type: 'issue' or 'pr'

        Returns:
            markdown 格式的摘要字符串
        """
        if not body:
            body = "(无正文)"
        kind = "Issue" if item_type == "issue" else "Pull Request"

        if item_type == "issue":
            prompt = render_prompt("assistant", "summarize.md",
                kind="Issue",
                is_issue=True,
                title=title,
                body=body[:4000],
            )
        else:
            prompt = render_prompt("assistant", "summarize.md",
                kind="Pull Request",
                is_issue=False,
                title=title,
                body=body[:4000],
            )

        try:
            content = self.llm.chat_sync(prompt, max_tokens=Config.LLM_MAX_TOKENS, temperature=0.3)
        except Exception as e:
            return f"**摘要生成失败**：{e}"

        if content and content.strip():
            # 清理可能多余的代码块包裹
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:markdown)?\n?", "", content)
                content = re.sub(r"\n?```$", "", content)
            return content.strip()
        return "*暂无摘要*"

    def translate(self, text: str, item_type: str) -> str:
        """将 Issue/PR 正文翻译为中文"""
        if not text:
            return ""

        prompt = render_prompt("assistant", "translate.md",
            item_type='Issue' if item_type == 'issue' else 'PR',
            text=text,
        )

        try:
            content = self.llm.chat_sync(prompt, max_tokens=Config.LLM_MAX_TOKENS, temperature=0.1)
            return content.strip() if content else text
        except Exception:
            logger.exception("translate failed")
            return text