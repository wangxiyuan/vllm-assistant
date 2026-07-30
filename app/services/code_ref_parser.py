"""
代码引用解析器
对应 DESIGN-ARTICLES.md 5.2 CodeRefParser

解析 Markdown 中的代码引用，支持多仓库。
引用格式：`vllm/engine/core.py:10-20`、`vllm/engine/core.py:L10-L20`、`vllm-ascend/ascend/backend.py:30`
"""
import difflib
import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional


class CodeRefParser:
    """解析 Markdown 中的代码引用，支持多仓库"""

    def __init__(self):
        # 从 DB 获取所有活跃仓库名，构建正则前缀
        self._refresh_repo_names()
        self._build_pattern()

    def _refresh_repo_names(self):
        """从 DB 重新加载活跃仓库列表"""
        from app.database import SessionLocal
        from app.models import RepoCache
        db = SessionLocal()
        try:
            names = [r.repo for r in db.query(RepoCache).filter(
                RepoCache.status == "active"
            ).all()]
            self.repo_names = sorted(names, key=len, reverse=True)
        finally:
            db.close()
        if not self.repo_names:
            self.repo_names = []

    def _build_pattern(self):
        """构建正则表达式"""
        prefix_pattern = "|".join(re.escape(n) for n in self.repo_names)

        # 匹配格式（反引号必须成对出现，避免误匹配）：
        #   `vllm/engine/core.py:10-20`
        #   `vllm/engine/core.py:L10-L20`
        #   `vllm-ascend/ascend/backend.py:30`
        self.REF_PATTERN = re.compile(
            rf'`(?:{prefix_pattern})/([^`\s]+?)[:#]L?(\d+)(?:[-~]L?(\d+))?`'
        )

    def parse_article(self, content: str) -> List[Dict]:
        """
        解析文章中的所有代码引用

        Returns:
            List of {
                "article_line": 行号,
                "repo": 仓库名,
                "file_path": 仓库内路径,
                "line_start": 起始行,
                "line_end": 结束行,
                "raw_match": 原始匹配文本
            }
        """
        lines = content.split('\n')
        results = []

        for line_idx, line in enumerate(lines, 1):
            matches = self.REF_PATTERN.finditer(line)
            for match in matches:
                # 反推仓库名：从全文匹配中提取前缀
                full_match = match.group(0)
                repo = self._detect_repo(full_match)
                file_path = match.group(1)
                start_line = int(match.group(2))
                end_line = int(match.group(3)) if match.group(3) else start_line

                results.append({
                    "article_line": line_idx,
                    "repo": repo,
                    "file_path": file_path,
                    "line_start": start_line,
                    "line_end": end_line,
                    "raw_match": full_match,
                })

        return results

    def _detect_repo(self, match: str) -> str:
        """从匹配文本中检测仓库名"""
        for name in self.repo_names:
            if match.startswith(f"`{name}/") or match.startswith(name + "/"):
                return name
        return self.repo_names[0] if self.repo_names else ""

    def validate_ref(self, repo: str, file_path: str, start_line: int, end_line: int,
                     cache_service) -> Dict:
        """
        验证单个引用是否有效。

        行号检查：文件是否缓存 → 行号是否越界
        深度检查：基于 content_hash 判断内容是否变化（由调用方决定是否执行）
        """
        lines = cache_service.get_file_lines(repo, file_path)
        if lines is None:
            return {
                "valid": False,
                "reason": "file_not_cached",
                "message": f"文件 {repo}/{file_path} 未在缓存中，请先执行代码同步",
            }

        total_lines = len(lines)
        if start_line > total_lines or end_line > total_lines:
            return {
                "valid": False,
                "reason": "line_out_of_range",
                "message": f"行号超出范围（文件当前共 {total_lines} 行）",
                "expected_range": f"1-{total_lines}",
                "actual_range": f"{start_line}-{end_line}",
            }

        # 提取引用的代码片段
        referenced_content = "\n".join(lines[start_line - 1:end_line])
        current_hash = hashlib.sha256(referenced_content.encode()).hexdigest()

        return {
            "valid": True,
            "reason": "ok",
            "content": referenced_content,
            "content_hash": current_hash,
            "total_lines": total_lines,
        }

    def deep_validate(self, ref, db) -> Dict:
        """
        深度检查：对比保存时的 content_hash 与当前代码的 hash。
        用于定时任务，检测"同行号但内容已变"的情况。

        Args:
            ref: CodeReference 对象（必须是 db session 关联的）
            db: 数据库 session
        """
        from app.services.local_code_sync import LocalCodeSyncService

        cache_service = LocalCodeSyncService(db)
        lines = cache_service.get_file_lines(ref.repo_name, ref.file_path)
        if lines is None:
            return {"valid": False, "reason": "file_not_cached"}

        if ref.line_start > len(lines) or ref.line_end > len(lines):
            return {"valid": False, "reason": "line_out_of_range"}

        current_content = "\n".join(lines[ref.line_start - 1:ref.line_end])
        current_hash = hashlib.sha256(current_content.encode()).hexdigest()

        if current_hash != ref.content_hash:
            diff_summary = self._generate_diff_summary(
                ref.content_snapshot or "", current_content
            )
            return {
                "valid": False,
                "reason": "content_changed",
                "old_content": ref.content_snapshot,
                "new_content": current_content,
                "diff_summary": diff_summary,
            }

        return {"valid": True, "reason": "ok", "content": current_content}

    def _generate_diff_summary(self, old: str, new: str) -> str:
        """生成简单的 diff 摘要（行级别对比）"""
        old_lines = old.splitlines()
        new_lines = new.splitlines()
        diff = difflib.unified_diff(old_lines, new_lines, n=2)
        return "\n".join(diff)

    def get_snippet_html(self, repo: str, file_path: str, start_line: int, end_line: int,
                         cache_service, show_line_numbers: bool = True,
                         is_outdated: bool = False) -> str:
        """生成代码片段的 HTML"""
        lines = cache_service.get_file_lines(repo, file_path)
        if lines is None:
            return '<div class="code-embed-error">文件未缓存</div>'

        total_lines = len(lines)
        if start_line > total_lines or end_line > total_lines:
            return f'<div class="code-embed-error">行号超出范围（文件共 {total_lines} 行）</div>'

        snippet_lines = lines[start_line - 1:end_line]
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

        for i, line in enumerate(snippet_lines, start_line):
            if show_line_numbers:
                html_parts.append(f'<span class="line-number">{i:>4}</span> ')
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<span class="code-content">{escaped}</span>\n')

        html_parts.append('</code></pre>')
        html_parts.append('</div>')
        return ''.join(html_parts)

    def save_article_refs(self, article_id: int, content: str, db) -> Dict:
        """
        保存文章时，解析所有代码引用并写入 CodeReference 表。

        在 POST/PUT /api/articles 的 handler 中调用。
        记录 content_hash 和 content_snapshot，用于后续深度检查。
        """
        from app.models import CodeReference, Article
        from app.services.local_code_sync import LocalCodeSyncService

        refs = self.parse_article(content)
        cache_service = LocalCodeSyncService(db)

        # 删除不再存在的引用
        existing = db.query(CodeReference).filter(
            CodeReference.article_id == article_id
        ).all()
        existing_keys = {(r.repo_name, r.file_path, r.line_start, r.line_end) for r in existing}
        current_keys = {(r["repo"], r["file_path"], r["line_start"], r["line_end"])
                        for r in refs}
        for ref in existing:
            key = (ref.repo_name, ref.file_path, ref.line_start, ref.line_end)
            if key not in current_keys:
                db.delete(ref)

        # 新增或更新引用，记录 content_hash
        valid_count = 0
        for ref_data in refs:
            key = (ref_data["repo"], ref_data["file_path"],
                   ref_data["line_start"], ref_data["line_end"])

            # 获取当前代码内容并计算 hash
            lines = cache_service.get_file_lines(
                ref_data["repo"], ref_data["file_path"]
            )
            content_snapshot = None
            content_hash = None
            if lines and ref_data["line_start"] <= len(lines):
                snippet = "\n".join(
                    lines[ref_data["line_start"] - 1:ref_data["line_end"]]
                )
                content_snapshot = snippet
                content_hash = hashlib.sha256(snippet.encode()).hexdigest()

            existing_ref = db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.repo_name == ref_data["repo"],
                CodeReference.file_path == ref_data["file_path"],
                CodeReference.line_start == ref_data["line_start"],
                CodeReference.line_end == ref_data["line_end"],
            ).first()

            if existing_ref:
                existing_ref.content_snapshot = content_snapshot
                existing_ref.content_hash = content_hash
                existing_ref.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            else:
                db.add(CodeReference(
                    article_id=article_id,
                    article_line_start=ref_data["article_line"],
                    repo_name=ref_data["repo"],
                    file_path=ref_data["file_path"],
                    line_start=ref_data["line_start"],
                    line_end=ref_data["line_end"],
                    content_snapshot=content_snapshot,
                    content_hash=content_hash,
                    last_checked_at=datetime.now(timezone.utc).replace(tzinfo=None),
                ))

            if content_hash:
                valid_count += 1

        # 更新文章统计
        article = db.query(Article).filter(Article.id == article_id).first()
        if article:
            article.code_refs_count = len(refs)
            article.valid_refs_count = valid_count

        db.commit()
        return {"total_refs": len(refs), "valid_refs": valid_count}