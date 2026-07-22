"""
文章渲染器
对应 DESIGN-ARTICLES.md 5.4 ArticleRenderer

渲染文章，将代码引用替换为实际代码片段
"""
from typing import Dict, List

from markdown import markdown

from app.models import Article, CodeReference
from app.services.code_ref_parser import CodeRefParser
from app.services.local_code_sync import LocalCodeSyncService


class ArticleRenderer:
    """渲染文章，将代码引用替换为实际代码片段"""

    def __init__(self, cache_service: LocalCodeSyncService, db):
        self.cache_service = cache_service
        self.db = db
        self.parser = CodeRefParser()

    def render_article(self, article_id: int, sync_code: bool = False) -> Dict:
        """
        渲染文章，嵌入代码片段。

        渲染策略：
        1. 解析文章中的所有代码引用
        2. 对每个引用，优先从 CodeReference 取缓存内容
        3. 如果 CodeReference 没有缓存，实时从 LocalCodeCache 取
        4. 无效引用显示错误提示
        5. 将 Markdown 中的引用替换为 HTML 代码块
        6. 整体转为 HTML
        """
        article = self.db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"error": "Article not found"}

        # 解析引用
        refs = self.parser.parse_article(article.content)

        # 构建引用映射：原始文本 → HTML 片段
        ref_map = {}
        embedded_info = []

        for ref in refs:
            key = ref["raw_match"]

            # 从 CodeReference 取缓存数据
            db_ref = self.db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.repo_name == ref["repo"],
                CodeReference.file_path == ref["file_path"],
                CodeReference.line_start == ref["line_start"],
                CodeReference.line_end == ref["line_end"],
            ).first()

            is_outdated = False
            ref_is_valid = False
            ref_id = None
            if db_ref:
                is_outdated = not db_ref.is_valid
                ref_is_valid = db_ref.is_valid
                ref_id = db_ref.id
                if db_ref.is_valid and db_ref.current_content:
                    html = self._generate_code_html(
                        db_ref.current_content, ref["line_start"],
                        ref["line_end"], is_outdated=is_outdated,
                        repo=ref["repo"], file_path=ref["file_path"],
                    )
                    ref_map[key] = html
                    embedded_info.append({
                        "ref_id": ref_id,
                        "repo": ref["repo"],
                        "file_path": ref["file_path"],
                        "line_start": ref["line_start"],
                        "line_end": ref["line_end"],
                        "is_valid": ref_is_valid,
                    })
                    continue

            # 实时从缓存文件获取
            validation = self.parser.validate_ref(
                ref["repo"], ref["file_path"],
                ref["line_start"], ref["line_end"],
                self.cache_service,
            )

            if validation["valid"]:
                html = self._generate_code_html(
                    validation["content"], ref["line_start"],
                    ref["line_end"], is_outdated=is_outdated,
                    repo=ref["repo"], file_path=ref["file_path"],
                )
            else:
                html = self._generate_error_html(validation)

            ref_map[key] = html
            embedded_info.append({
                "ref_id": ref_id,
                "repo": ref["repo"],
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": validation["valid"],
                "reason": validation.get("reason", ""),
                "message": validation.get("message", ""),
            })

        # 替换 Markdown 中的引用
        rendered_content = article.content
        for raw_match, html in ref_map.items():
            rendered_content = rendered_content.replace(
                f"`{raw_match}`", html
            )

        # 转换为 HTML
        full_html = markdown(rendered_content)

        return {
            "html": full_html,
            "embedded_codes": embedded_info,
        }

    def render_preview(self, content: str) -> Dict:
        """
        预览模式：不保存，只返回渲染结果。
        引用从缓存实时获取，不查 CodeReference 表。
        """
        refs = self.parser.parse_article(content)
        ref_map = {}
        ref_details = []

        for ref in refs:
            validation = self.parser.validate_ref(
                ref["repo"], ref["file_path"],
                ref["line_start"], ref["line_end"],
                self.cache_service,
            )

            if validation["valid"]:
                html = self._generate_code_html(
                    validation["content"], ref["line_start"],
                    ref["line_end"], repo=ref["repo"], file_path=ref["file_path"],
                )
            else:
                html = self._generate_error_html(validation)

            ref_map[ref["raw_match"]] = html
            ref_details.append({
                "repo": ref["repo"],
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": validation["valid"],
                "reason": validation.get("reason", ""),
                "message": validation.get("message", ""),
            })

        rendered_content = content
        for raw_match, html in ref_map.items():
            rendered_content = rendered_content.replace(f"`{raw_match}`", html)

        full_html = markdown(rendered_content)

        return {"html": full_html, "refs": ref_details}

    def _generate_code_html(self, content: str, start_line: int, end_line: int,
                            is_outdated: bool = False,
                            repo: str = "", file_path: str = "") -> str:
        """生成带行号的代码 HTML"""
        lines = content.split("\n")
        css_class = "embedded-code outdated" if is_outdated else "embedded-code"

        html_parts = [
            f'<div class="code-embed" data-repo="{repo}" data-file="{file_path}">',
        ]

        if is_outdated:
            html_parts.append(
                '<div class="outdated-banner">'
                '⚠️ 此代码引用可能已过时'
                '<button class="diff-toggle" onclick="toggleDiff(this)">查看变更</button>'
                '</div>'
            )

        html_parts.append(f'<pre><code class="{css_class}">')

        for i, line in enumerate(lines, start_line):
            html_parts.append(f'<span class="line-number">{i}</span> ')
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<span class="code-content">{escaped}</span>\n')

        html_parts.append('</code></pre>')
        html_parts.append('</div>')
        return ''.join(html_parts)

    def _generate_error_html(self, validation: Dict) -> str:
        """生成错误提示的 HTML"""
        msg = validation.get("message", "引用无效")
        return f'<div class="code-embed-error">⚠️ {msg}</div>'