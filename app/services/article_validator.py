"""
文章代码引用验证器
对应 DESIGN-ARTICLES.md 5.5 ArticleValidator

两阶段验证：浅层（行号越界）+ 深层（内容哈希对比）
"""
from datetime import datetime, timezone
from typing import Dict

from app.models import Article, CodeReference
from app.services.code_ref_parser import CodeRefParser
from app.services.local_code_sync import LocalCodeSyncService


class ArticleValidator:
    """文章代码引用验证器（两阶段验证）"""

    def __init__(self, cache_service: LocalCodeSyncService, db):
        self.cache_service = cache_service
        self.db = db
        self.parser = CodeRefParser()

    def validate_article(self, article_id: int, deep_check: bool = False) -> Dict:
        """
        验证单篇文章的所有代码引用。

        浅层检查（deep_check=False，默认）：
        - 文件是否缓存
        - 行号是否越界

        深层检查（deep_check=True，定时任务或手动触发）：
        - 行号越界检查
        - 内容哈希对比（检测同行号但内容已变）
        """
        article = self.db.query(Article).filter(Article.id == article_id).first()
        if not article:
            return {"error": "Article not found"}

        refs = self.parser.parse_article(article.content)
        valid_count = 0
        invalid_count = 0
        details = []

        for ref in refs:
            # 查数据库中的 CodeReference 记录
            db_ref = self.db.query(CodeReference).filter(
                CodeReference.article_id == article_id,
                CodeReference.repo_name == ref["repo"],
                CodeReference.file_path == ref["file_path"],
                CodeReference.line_start == ref["line_start"],
                CodeReference.line_end == ref["line_end"],
            ).first()

            # 确保 db_ref 存在（深度检查需要 content_hash）
            if not db_ref:
                db_ref = CodeReference(
                    article_id=article_id,
                    repo_name=ref["repo"],
                    file_path=ref["file_path"],
                    line_start=ref["line_start"],
                    line_end=ref["line_end"],
                )
                self.db.add(db_ref)
                self.db.flush()

            if deep_check:
                validation = self.parser.deep_validate(db_ref, self.db)
            else:
                validation = self.parser.validate_ref(
                    ref["repo"], ref["file_path"],
                    ref["line_start"], ref["line_end"],
                    self.cache_service,
                )

            db_ref.is_valid = validation["valid"]
            db_ref.last_checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if validation.get("content"):
                db_ref.current_content = validation["content"]
            if validation.get("diff_summary"):
                db_ref.diff_summary = validation["diff_summary"]

            if validation["valid"]:
                valid_count += 1
            else:
                invalid_count += 1

            details.append({
                "repo": ref["repo"],
                "file_path": ref["file_path"],
                "line_start": ref["line_start"],
                "line_end": ref["line_end"],
                "is_valid": validation["valid"],
                "reason": validation.get("reason", ""),
                "message": validation.get("message", ""),
                "diff_summary": validation.get("diff_summary", ""),
            })

        # 更新文章统计
        article.code_refs_count = len(refs)
        article.valid_refs_count = valid_count
        article.outdated_refs_count = invalid_count
        article.last_verified_at = datetime.now(timezone.utc).replace(tzinfo=None)

        self.db.commit()

        return {
            "article_id": article_id,
            "validated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            "total_refs": len(refs),
            "valid_refs": valid_count,
            "invalid_refs": invalid_count,
            "details": details,
        }

    def batch_validate(self, deep_check: bool = False) -> Dict:
        """批量验证所有文章"""
        articles = self.db.query(Article).all()
        results = {
            "total": len(articles),
            "validated": 0,
            "with_invalid_refs": 0,
            "details": [],
        }

        for article in articles:
            result = self.validate_article(article.id, deep_check)
            results["validated"] += 1
            if result["invalid_refs"] > 0:
                results["with_invalid_refs"] += 1
                results["details"].append({
                    "article_id": article.id,
                    "title": article.title,
                    "invalid_refs": result["invalid_refs"],
                })

        return results