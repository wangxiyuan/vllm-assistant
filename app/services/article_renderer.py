"""
文章渲染器
对应 DESIGN-ARTICLES.md 5.4 ArticleRenderer

渲染文章，将代码引用替换为实际代码片段
"""
from html.parser import HTMLParser
from typing import Dict, List
import re

from markdown import Markdown

from app.models import Article, CodeReference
from app.services.code_ref_parser import CodeRefParser
from app.services.local_code_sync import LocalCodeSyncService


def _preprocess_math(content: str) -> str:
    """将 $$...$$、$...$、\[...\] 数学公式包裹为 HTML，避免 markdown 引擎破坏内容"""
    # 用 HTML 实体 &#92; 代替反斜杠，避免 markdown 引擎吃掉 \ 字符
    BS = '&#92;'

    # 先处理块级公式 \[...\]
    content = re.sub(
        r'\\\[(.+?)\\\]',
        rf'<div class="math-block">{BS}[\1{BS}]</div>',
        content,
        flags=re.DOTALL,
    )
    # 再处理块级公式 $$...$$
    content = re.sub(
        r'\$\$(.+?)\$\$',
        rf'<div class="math-block">{BS}[\1{BS}]</div>',
        content,
        flags=re.DOTALL,
    )
    # 最后处理行内公式 $...$（避免匹配到已被替换的）
    content = re.sub(
        r'(?<!\$)\$(.+?)\$(?!\$)',
        rf'<span class="math-inline">{BS}(\1{BS})</span>',
        content,
    )
    return content


def _toc_html_to_json(toc_html: str) -> List[dict]:
    """将 markdown toc extension 输出的 HTML 目录树解析为结构化 JSON。

    输入: md.toc 输出的 <div class="toc"><ul><li>...</li></ul></div>
    输出: [{"level": 1, "id": "heading-id", "text": "标题文本"}, ...]
    """
    items = []

    class TocParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.current_level = 0
            self.in_anchor = False
            self.anchor_text = ""
            self.anchor_href = ""

        def handle_starttag(self, tag, attrs):
            if tag == "ul":
                self.current_level += 1
            elif tag == "a":
                self.in_anchor = True
                self.anchor_text = ""
                self.anchor_href = ""
                for name, value in attrs:
                    if name == "href":
                        self.anchor_href = (value or "").lstrip("#")

        def handle_endtag(self, tag):
            if tag == "ul":
                self.current_level -= 1
            elif tag == "a":
                self.in_anchor = False
                if self.anchor_href:
                    items.append({
                        "level": self.current_level,
                        "id": self.anchor_href,
                        "text": self.anchor_text.strip(),
                    })

        def handle_data(self, data):
            if self.in_anchor:
                self.anchor_text += data

    TocParser().feed(toc_html)
    return items


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

        # 预处理数学公式
        rendered_content = _preprocess_math(rendered_content)

        # 转换为 HTML（启用围栏代码块、代码高亮、表格和目录扩展）
        md_engine = Markdown(extensions=['fenced_code', 'codehilite', 'tables', 'toc'],
                             extension_configs={'toc': {'toc_depth': '1-3', 'anchorlink': False}})
        full_html = md_engine.convert(rendered_content)
        # 从 md.toc 解析结构化目录
        toc = _toc_html_to_json(md_engine.toc)

        return {
            "html": full_html,
            "embedded_codes": embedded_info,
            "toc": toc,
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

        # 预处理数学公式
        rendered_content = _preprocess_math(rendered_content)

        # 转换为 HTML（启用围栏代码块、代码高亮、表格和目录扩展）
        md_engine = Markdown(extensions=['fenced_code', 'codehilite', 'tables', 'toc'],
                             extension_configs={'toc': {'toc_depth': '1-3', 'anchorlink': False}})
        full_html = md_engine.convert(rendered_content)
        # 从 md.toc 解析结构化目录
        toc = _toc_html_to_json(md_engine.toc)

        return {"html": full_html, "refs": ref_details, "toc": toc}

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