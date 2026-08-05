"""
持久记忆/知识库服务

提供：
- remember() 存储知识
- recall() 检索知识（FTS5 全文检索 + 标签过滤）
- forget() 删除/标记过时
- build_code_knowledge() 从已有数据源批量构建知识种子
- sync_code_knowledge() 增量更新
"""
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.database import SessionLocal
from app.models import AIMemory

logger = logging.getLogger(__name__)


class MemoryService:
    """持久记忆/知识库服务"""

    # 默认召回数量
    DEFAULT_TOP_K = 5
    # 知识库中保留的最大条目数
    MAX_RECORDS = 10000

    def remember(
        self,
        content: str,
        source_type: str = "manual",
        source_ref: Optional[str] = None,
        tags: Optional[List[str]] = None,
        checksum: Optional[str] = None,
    ) -> int:
        """存储一条知识。如果相同 source_ref 已存在，则更新。

        Returns:
            知识条目的 id
        """
        if not content or not content.strip():
            return 0

        db = SessionLocal()
        try:
            existing = None
            if source_ref:
                existing = (
                    db.query(AIMemory)
                    .filter(AIMemory.source_ref == source_ref)
                    .first()
                )

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            tags_json = json.dumps(tags or [], ensure_ascii=False)

            if existing:
                existing.content = content
                existing.tags = tags_json
                existing.checksum = checksum
                existing.updated_at = now
                existing.is_stale = False
                if source_type != "manual":
                    existing.source_type = source_type
                db.commit()
                return existing.id
            else:
                entry = AIMemory(
                    content=content,
                    source_type=source_type,
                    source_ref=source_ref or "",
                    tags=tags_json,
                    checksum=checksum,
                    created_at=now,
                    updated_at=now,
                    last_accessed_at=None,
                    access_count=0,
                    is_stale=False,
                )
                db.add(entry)
                db.commit()
                return entry.id
        except Exception:
            logger.exception("Failed to remember knowledge")
            db.rollback()
            return 0
        finally:
            db.close()

    def recall(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        tags: Optional[List[str]] = None,
        source_types: Optional[List[str]] = None,
        exclude_stale: bool = True,
    ) -> List[Dict[str, Any]]:
        """检索知识库。

        先按 FTS5 全文检索，再按标签过滤，最后按访问次数排序。
        返回的结构和 AIMemory.to_dict() 一致。
        """
        if not query or not query.strip():
            return []

        db = SessionLocal()
        try:
            # 1. FTS5 全文检索
            # SQLite FTS5 默认不区分大小写，支持中文
            escaped_query = self._escape_fts_query(query)
            fts_sql = text("""
                SELECT rowid FROM ai_memory_fts
                WHERE ai_memory_fts MATCH :q
                ORDER BY rank
                LIMIT :limit
            """)
            fts_rows = db.execute(fts_sql, {"q": escaped_query, "limit": top_k * 3}).fetchall()
            if not fts_rows:
                # 如果精确匹配失败，尝试前缀匹配
                fts_rows = db.execute(
                    text("SELECT rowid FROM ai_memory_fts WHERE ai_memory_fts MATCH :q ORDER BY rank LIMIT :limit"),
                    {"q": f"{escaped_query}*", "limit": top_k * 3},
                ).fetchall()

            if not fts_rows:
                return []

            row_ids = [r[0] for r in fts_rows]

            # 2. 查询完整记录
            query_obj = db.query(AIMemory).filter(AIMemory.id.in_(row_ids))

            # 排除过时知识
            if exclude_stale:
                query_obj = query_obj.filter(AIMemory.is_stale == False)

            # 按 source_type 过滤
            if source_types:
                query_obj = query_obj.filter(AIMemory.source_type.in_(source_types))

            entries = query_obj.all()

            # 3. 按标签过滤（如果指定了标签）
            if tags:
                filtered = []
                for entry in entries:
                    entry_tags = json.loads(entry.tags) if entry.tags else []
                    if any(t in entry_tags for t in tags):
                        filtered.append(entry)
                entries = filtered

            # 4. 按访问次数排序（热门知识优先）
            entries.sort(key=lambda e: e.access_count or 0, reverse=True)

            # 5. 更新访问统计
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for entry in entries[:top_k]:
                entry.access_count = (entry.access_count or 0) + 1
                entry.last_accessed_at = now
            db.commit()

            # 6. 返回结果
            results = []
            for entry in entries[:top_k]:
                results.append(self._entry_to_dict(entry))
            return results
        except Exception:
            logger.exception("Failed to recall knowledge")
            return []
        finally:
            db.close()

    def forget(self, memory_id: int, hard_delete: bool = False) -> bool:
        """删除知识条目。

        Args:
            memory_id: 知识条目 id
            hard_delete: True 则物理删除，False 则标记为 stale

        Returns:
            是否成功
        """
        db = SessionLocal()
        try:
            entry = db.query(AIMemory).filter(AIMemory.id == memory_id).first()
            if not entry:
                return False

            if hard_delete:
                db.delete(entry)
            else:
                entry.is_stale = True
                entry.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            return True
        except Exception:
            logger.exception("Failed to forget knowledge")
            db.rollback()
            return False
        finally:
            db.close()

    def find_by_source_ref(self, source_ref: str) -> Optional[AIMemory]:
        """按 source_ref 查找知识条目（用于增量更新判断）"""
        db = SessionLocal()
        try:
            return (
                db.query(AIMemory)
                .filter(AIMemory.source_ref == source_ref)
                .first()
            )
        finally:
            db.close()

    def forget_by_source_ref_prefix(self, source_ref_prefix: str, hard_delete: bool = False) -> int:
        """按 source_ref 前缀批量删除或标记知识条目。

        Args:
            source_ref_prefix: source_ref 前缀，如 "article123" 或 "conv/session-id/"
            hard_delete: True 则物理删除，False 则标记为 stale

        Returns:
            处理的条目数
        """
        db = SessionLocal()
        try:
            base_query = db.query(AIMemory).filter(
                AIMemory.source_ref.like(f"{source_ref_prefix}%"),
            )
            if not hard_delete:
                base_query = base_query.filter(AIMemory.is_stale == False)

            if hard_delete:
                count = base_query.delete(synchronize_session=False)
                action = "Deleted"
            else:
                count = base_query.update(
                    {"is_stale": True, "updated_at": datetime.now(timezone.utc).replace(tzinfo=None)},
                    synchronize_session=False,
                )
                action = "Marked as stale"
            db.commit()
            if count > 0:
                logger.info(f"{action} {count} memories by source_ref prefix: {source_ref_prefix}")
            return count
        except Exception:
            logger.exception("Failed to forget knowledge by source_ref prefix")
            db.rollback()
            return 0
        finally:
            db.close()

    def update(self, memory_id: int, **kwargs) -> bool:
        """更新知识条目的字段

        Args:
            memory_id: 知识条目 id
            **kwargs: 要更新的字段，如 content=..., checksum=...

        Returns:
            是否成功
        """
        db = SessionLocal()
        try:
            entry = db.query(AIMemory).filter(AIMemory.id == memory_id).first()
            if not entry:
                return False

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for key, value in kwargs.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
            entry.updated_at = now
            entry.is_stale = False
            db.commit()
            return True
        except Exception:
            logger.exception("Failed to update memory")
            db.rollback()
            return False
        finally:
            db.close()

    def list_by_tags(
        self,
        tags: List[str],
        top_k: int = DEFAULT_TOP_K,
        exclude_stale: bool = True,
    ) -> List[Dict[str, Any]]:
        """按标签列出知识条目（不经过 FTS5，直接按标签匹配）"""
        db = SessionLocal()
        try:
            query_obj = db.query(AIMemory)
            if exclude_stale:
                query_obj = query_obj.filter(AIMemory.is_stale == False)

            entries = query_obj.order_by(AIMemory.access_count.desc()).limit(top_k * 3).all()

            results = []
            for entry in entries:
                entry_tags = json.loads(entry.tags) if entry.tags else []
                if any(t in entry_tags for t in tags):
                    results.append(self._entry_to_dict(entry))
                    if len(results) >= top_k:
                        break
            return results
        finally:
            db.close()

    def get_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        db = SessionLocal()
        try:
            total = db.query(AIMemory).filter(AIMemory.is_stale == False).count()
            stale = db.query(AIMemory).filter(AIMemory.is_stale == True).count()
            # 按 source_type 统计
            type_counts = db.execute(
                text("SELECT source_type, COUNT(*) as cnt FROM ai_memory WHERE is_stale = 0 GROUP BY source_type")
            ).fetchall()
            by_type = {r[0]: r[1] for r in type_counts}
            # 补全所有已知类型（数量为 0 的也显示）
            known_types = ["docs", "code_structure", "issue", "pr", "article", "manual", "conversation", "report", "slack"]
            for t in known_types:
                if t not in by_type:
                    by_type[t] = 0
            return {
                "total": total,
                "stale": stale,
                "by_type": by_type,
            }
        finally:
            db.close()

    def list_by_source_type(
        self,
        source_type: str,
        offset: int = 0,
        limit: int = 20,
        query: str = "",
        exclude_stale: bool = True,
    ) -> Dict[str, Any]:
        """按来源类型列出知识条目，支持分页和关键词搜索

        Args:
            source_type: 来源类型（如 "docs"、"code_structure"、"issue" 等）
            offset: 偏移量
            limit: 返回条数
            query: 可选的关键词搜索
            exclude_stale: 是否排除过时条目

        Returns:
            {"results": [...], "total": int, "has_more": bool}
        """
        db = SessionLocal()
        try:
            base = db.query(AIMemory).filter(AIMemory.source_type == source_type)
            if exclude_stale:
                base = base.filter(AIMemory.is_stale == False)

            if query.strip():
                # 使用 SQLite LIKE 模糊搜索 content 和 source_ref
                like = f"%{query.strip()}%"
                base = base.filter(
                    AIMemory.content.like(like) | AIMemory.source_ref.like(like)
                )

            total = base.count()
            entries = base.order_by(AIMemory.updated_at.desc()).offset(offset).limit(limit).all()

            return {
                "results": [self._entry_to_dict(e) for e in entries],
                "total": total,
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < total,
            }
        finally:
            db.close()

    # ======================================================================
    # 知识构建（从已有数据源批量构建）
    # ======================================================================

    def build_code_knowledge(self, days_back: int = 90) -> Dict[str, int]:
        """从已有数据源批量构建知识种子。

        Args:
            days_back: 只处理最近 N 天的 Item 数据

        Returns:
            各层构建数量统计
        """
        stats = {"docs": 0, "code_structure": 0, "issue_pr": 0, "article": 0, "model": 0}
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_back)

        # 1. 从 LocalCodeCache 构建代码结构 + 文档知识（走增量更新逻辑）
        code_stats = self._build_from_local_code()
        stats["docs"] = code_stats.get("docs", 0)
        stats["code_structure"] = code_stats.get("code_structure", 0)

        # 2. 从 Item 表构建 issue/PR 知识
        issue_stats = self._build_from_items(cutoff)
        stats["issue_pr"] = issue_stats.get("count", 0)

        # 3. 从 Article 表构建文章知识
        article_stats = self._build_from_articles()
        stats["article"] = article_stats.get("count", 0)

        # 4. 从 Operator / ModelAnatomy 表构建架构知识
        model_stats = self._build_from_model_anatomy()
        stats["model"] = model_stats.get("count", 0)

        logger.info(f"Knowledge build complete: {stats}")
        return stats

    def _is_doc_file_useful(self, file_path: str) -> bool:
        """判断文档文件是否对知识库有价值，跳过测试 fixture、配置文件等垃圾内容"""
        path_lower = file_path.lower()
        # 跳过测试 fixture 和 test output 文件
        if '/fixtures/' in path_lower or '/fixture/' in path_lower:
            return False
        if 'test_output_' in path_lower:
            return False
        # 跳过 requirements 和 CMakeLists 等构建配置文件
        if path_lower.endswith('requirements.txt') or path_lower.endswith('cmakelists.txt'):
            return False
        if path_lower.endswith('requirements-dev.txt') or path_lower.endswith('requirements-lint.txt'):
            return False
        # 跳过纯文本的配置文件列表（只有文件名列表，无实际内容）
        if path_lower.endswith(('models-small.txt', 'models-large.txt', 'models.txt')):
            return False
        if path_lower.endswith(('models-small-rocm.txt', 'models-large-rocm.txt', 'models-large-hopper.txt')):
            return False
        if path_lower.endswith(('models-mm-large-h100.txt', 'models-mm-small.txt')):
            return False
        if path_lower.endswith(('models-b200.txt', 'models-gfx942.txt', 'models-gfx950.txt', 'models-h100.txt')):
            return False
        if path_lower.endswith(('models-spark.txt', 'models-blackwell.txt', 'models-blackwell-ep.txt')):
            return False
        if path_lower.endswith(('models-h200.txt', 'models-mi3xx.txt', 'models-mi3xx-fp8-and-mixed.txt')):
            return False
        if path_lower.endswith(('models-pcp.txt', 'models-qwen35-blackwell.txt', 'models-qwen35-mi355.txt')):
            return False
        if path_lower.endswith(('models-small-tp.txt', 'models-turboquant.txt')):
            return False
        if path_lower.endswith(('config-b200.txt', 'config-h100.txt', 'config-test.txt')):
            return False
        if path_lower.endswith(('config-act-fp8.txt', 'config-act-int8.txt', 'config-int5wc-hadamard.txt')):
            return False
        # 跳过测试用的纯文本（诗歌、示例 prompt 等）
        if path_lower.endswith('sonnet.txt') or path_lower.endswith('long_prompt.txt'):
            return False
        if path_lower.endswith('example.txt') or path_lower.endswith('prompts.txt'):
            return False
        if path_lower.endswith('dataset.txt') or path_lower.endswith('rules-env.txt'):
            return False
        if path_lower.endswith('prompt.txt') or path_lower.endswith('sonnet3.5_nov2024.txt'):
            return False
        if path_lower.endswith('packages.txt'):
            return False
        # 跳过 AGENTS.md / CLAUDE.md 等 agent 配置文件
        if path_lower.endswith('agents.md') or path_lower.endswith('claude.md'):
            return False
        # 跳过 benchmark 数据集文件
        if '/benchmarks/' in path_lower and path_lower.endswith('.txt'):
            return False
        if '/benchmark/' in path_lower and path_lower.endswith('.txt'):
            return False
        # 跳过 docker 相关文本文件
        if '/docker/' in path_lower and path_lower.endswith('.txt'):
            return False
        return True

    def _build_from_local_code(self) -> Dict[str, int]:
        """从 LocalCodeCache 构建代码结构和文档知识"""
        from app.database import SessionLocal
        from app.models import LocalCodeCache

        stats = {"docs": 0, "code_structure": 0}
        db = SessionLocal()
        try:
            files = db.query(LocalCodeCache).all()
            # 按 repo 分组，先提取目录结构，再处理文件
            repo_dirs = {}  # repo -> set of dir paths
            for f in files:
                repo_dirs.setdefault(f.repo, set()).add(self._get_parent_dir(f.file_path))

            # 为每个 repo 存储目录结构
            for repo, dirs in repo_dirs.items():
                sorted_dirs = sorted(dirs)
                content = f"## {repo}/ 目录结构\n\n"
                content += "\n".join(f"- `{d}/`" for d in sorted_dirs if d)
                self.remember(
                    content=content,
                    source_type="code_structure",
                    source_ref=f"{repo}/",
                    tags=["code", repo],
                    checksum=hashlib.md5(json.dumps(sorted_dirs, ensure_ascii=False).encode()).hexdigest(),
                )
                stats["code_structure"] += 1

            # 处理每个文件
            seen_checksums = set()  # 用于 checksum 去重
            for f in files:
                if not f.content or not f.checksum:
                    continue

                # 文档文件：按扩展名判断
                if f.file_path.endswith((".md", ".rst", ".txt")):
                    if not self._is_doc_file_useful(f.file_path):
                        continue
                    # 跳过内容完全重复的文件
                    if f.checksum in seen_checksums:
                        continue
                    seen_checksums.add(f.checksum)
                    knowledge = self._extract_doc_structure(f.file_path, f.content)
                    if knowledge:
                        existing = self.find_by_source_ref(f.file_path)
                        if existing and existing.checksum == f.checksum:
                            continue
                        self.remember(
                            content=knowledge,
                            source_type="docs",
                            source_ref=f.file_path,
                            tags=["docs", f.repo],
                            checksum=f.checksum,
                        )
                        stats["docs"] += 1

                # 代码文件：只提取文件头注释和函数签名
                elif f.file_path.endswith((".py", ".cpp", ".cu", ".h", ".hpp", ".cuh")):
                    # 跳过已有且未变化的
                    existing = self.find_by_source_ref(f.file_path)
                    if existing and existing.checksum == f.checksum:
                        continue
                    knowledge = self._extract_code_structure(f.file_path, f.content)
                    if knowledge:
                        self.remember(
                            content=knowledge,
                            source_type="code_structure",
                            source_ref=f.file_path,
                            tags=["code", f.repo, self._file_module(f.file_path)],
                            checksum=f.checksum,
                        )
                        stats["code_structure"] += 1
        except Exception:
            logger.exception("Failed to build from local code")
        finally:
            db.close()
        return stats

    def _build_from_items(self, cutoff: datetime) -> Dict[str, int]:
        """从 Item 表增量构建 issue/PR 知识

        按 checksum（items 表的 updated_at）判断是否需要更新。
        """
        from app.database import SessionLocal
        from app.models import Item

        stats = {"count": 0}
        db = SessionLocal()
        try:
            items = (
                db.query(Item)
                .filter(Item.updated_at >= cutoff)
                .order_by(Item.updated_at.desc())
                .limit(500)
                .all()
            )
            for item in items:
                if not item.body or len(item.body.strip()) < 50:
                    continue

                labels = json.loads(item.labels) if item.labels else []
                area = item.area
                if not area:
                    # 从 labels 中推断 area：取第一个非通用标签名作为 area
                    generic_labels = {"bug", "feature request", "RFC", "stale", "ready", "needs-rebase",
                                      "good first issue", "help wanted", "documentation", "performance",
                                      "unstale", "keep-open", "ci-failure", "installation", "ci/build",
                                      "frontend", "rocm", "nvidia", "intel-gpu", "cpu", "quantization",
                                      "speculative-decoding", "deepseek", "kimi", "k3", "v1", "v1_core",
                                      "multi-modality", "rust", "tests", "moe", "attention", "distributed",
                                      "kv-connector", "model", "config", "kernels", "entrypoints",
                                      "sampling", "lora", "mamba", "compilation", "model_loader",
                                      "gpu_hardware", "docs"}
                    meaningful_labels = [l for l in labels if l not in generic_labels]
                    area = meaningful_labels[0] if meaningful_labels else "general"
                tags = [item.type, area, item.repo] + (labels[:5] if labels else [])

                title = item.title or ""
                body_preview = (item.body or "")
                content = (
                    f"## {title}\n\n"
                    f"**类型**: {'PR' if item.type == 'pr' else 'Issue'} "
                    f"**状态**: {item.state} "
                    f"**标签**: {', '.join(labels) if labels else '无'}\n\n"
                    f"**正文**: {body_preview}\n"
                )
                source_ref = f"{item.repo}#{item.number}"
                # 用 items 表的 updated_at 作为 checksum 判断变化
                item_checksum = str(item.updated_at.timestamp()) if item.updated_at else ""

                existing = self.find_by_source_ref(source_ref)
                if existing:
                    if existing.checksum == item_checksum:
                        continue
                    self.update(existing.id, content=content, checksum=item_checksum)
                    stats["count"] += 1
                else:
                    self.remember(
                        content=content,
                        source_type="pr" if item.type == "pr" else "issue",
                        source_ref=source_ref,
                        tags=tags,
                        checksum=item_checksum,
                    )
                    stats["count"] += 1
        except Exception:
            logger.exception("Failed to build from items")
        finally:
            db.close()
        return stats

    def _build_from_articles(self) -> Dict[str, int]:
        """从 Article 表增量构建文章知识

        按 checksum（articles 表的 updated_at）判断是否需要更新。
        """
        from app.database import SessionLocal
        from app.models import Article

        stats = {"count": 0}
        db = SessionLocal()
        try:
            articles = db.query(Article).filter(Article.status == "published").all()
            for article in articles:
                tags = json.loads(article.tags) if article.tags else []
                if article.area:
                    tags = [article.area] + tags

                source_ref = f"article#{article.id}"
                content = (
                    f"## {article.title}\n\n"
                    f"{article.content}\n"
                )
                article_checksum = str(article.updated_at.timestamp()) if article.updated_at else ""

                existing = self.find_by_source_ref(source_ref)
                if existing:
                    if existing.checksum == article_checksum:
                        continue
                    self.update(existing.id, content=content, checksum=article_checksum)
                    stats["count"] += 1
                else:
                    self.remember(
                        content=content,
                        source_type="article",
                        source_ref=source_ref,
                        tags=tags,
                        checksum=article_checksum,
                    )
                    stats["count"] += 1
        except Exception:
            logger.exception("Failed to build from articles")
        finally:
            db.close()
        return stats

    def _build_from_model_anatomy(self) -> Dict[str, int]:
        """从 Operator / ModelAnatomy 表增量构建架构知识

        按 checksum（updated_at）判断是否需要更新。
        """
        from app.database import SessionLocal
        from app.models import Operator, ModelAnatomy

        stats = {"count": 0}
        db = SessionLocal()
        try:
            # 算子
            operators = db.query(Operator).all()
            for op in operators:
                source_ref = f"operator#{op.id}"
                op_checksum = str(op.updated_at.timestamp()) if op.updated_at else ""

                tags = json.loads(op.tags) if op.tags else []
                tags = ["operator"] + tags
                content = (
                    f"## 算子: {op.display_name} ({op.name})\n\n"
                    f"**分类**: {op.category}\n"
                    f"**描述**: {op.description or '暂无'}\n"
                    f"**输入**: {op.input_shape_desc or 'N/A'}\n"
                    f"**输出**: {op.output_shape_desc or 'N/A'}\n"
                )

                existing = self.find_by_source_ref(source_ref)
                if existing:
                    if existing.checksum == op_checksum:
                        continue
                    self.update(existing.id, content=content, checksum=op_checksum)
                    stats["count"] += 1
                else:
                    self.remember(
                        content=content,
                        source_type="code_structure",
                        source_ref=source_ref,
                        tags=tags,
                        checksum=op_checksum,
                    )
                    stats["count"] += 1

            # 模型架构
            models = db.query(ModelAnatomy).all()
            for model in models:
                source_ref = f"model_anatomy#{model.id}"
                model_checksum = str(model.updated_at.timestamp()) if model.updated_at else ""

                tags = json.loads(model.tags) if model.tags else []
                tags = ["model_anatomy"] + tags
                content = (
                    f"## 模型: {model.display_name} ({model.name})\n\n"
                    f"**分类**: {model.category}\n"
                    f"**描述**: {model.description or '暂无'}\n"
                    f"**算子数量**: {model.operators_count or 0}\n"
                )

                existing = self.find_by_source_ref(source_ref)
                if existing:
                    if existing.checksum == model_checksum:
                        continue
                    self.update(existing.id, content=content, checksum=model_checksum)
                    stats["count"] += 1
                else:
                    self.remember(
                        content=content,
                        source_type="code_structure",
                        source_ref=source_ref,
                        tags=tags,
                        checksum=model_checksum,
                    )
                    stats["count"] += 1
        except Exception:
            logger.exception("Failed to build from model anatomy")
        finally:
            db.close()
        return stats

    # ======================================================================
    # 内部辅助方法
    # ======================================================================

    def _extract_doc_structure(self, file_path: str, content: str) -> str:
        """从文档文件提取结构化内容。

        按 ## 标题分割，保留标题+内容，太长则截断。
        """
        if not content:
            return ""

        # 提取标题（第一个 # 行）
        title = ""
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("# ") and not line.startswith("## "):
                title = line[2:].strip()
                break

        # 按 ## 章节分割
        sections = []
        current_section = f"## 简介\n"
        for line in content.split("\n"):
            if line.startswith("## ") and not line.startswith("### "):
                if current_section.strip():
                    sections.append(current_section.strip())
                current_section = f"{line}\n"
            else:
                current_section += f"{line}\n"
        if current_section.strip():
            sections.append(current_section.strip())

        # 只保留前 5 个章节
        result = []
        if title:
            result.append(f"# {title}\n")
        for section in sections[:5]:
            result.append(section)

        final = "\n\n".join(result)
        return final

    def _extract_code_structure(self, file_path: str, content: str) -> str:
        """从代码文件提取结构骨架。

        只提取：文件头注释、类定义、函数签名。
        不包含函数体实现。
        """
        if not content:
            return ""

        lines = content.split("\n")
        # 文件头注释（前 20 行内的注释块）
        header_comment = []
        in_header = True
        for line in lines[:20]:
            if in_header and (line.strip().startswith(("#", "\"\"\"", "'''", "//", "/*", "*")) or not line.strip()):
                header_comment.append(line.strip())
            else:
                in_header = False

        header = "\n".join(header_comment[:15]) if header_comment else ""

        # 提取类定义和函数签名
        signatures = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("class ", "def ", "async def ")):
                # 去掉函数体后的冒号，保留签名
                if stripped.endswith(":"):
                    stripped = stripped[:-1]
                signatures.append(stripped)

        # 构建结果
        parts = []
        parts.append(f"## 文件: {file_path}")
        if header:
            parts.append(f"### 文件说明\n```\n{header}\n```")
        if signatures:
            sig_text = "\n".join(signatures[:30])  # 最多 30 个签名
            if len(signatures) > 30:
                sig_text += f"\n...（共 {len(signatures)} 个定义）"
            parts.append(f"### 结构定义\n```\n{sig_text}\n```")
        else:
            parts.append("（无明显的类/函数定义）")

        return "\n\n".join(parts)

    def _escape_fts_query(self, query: str) -> str:
        """转义 FTS5 查询字符串，避免特殊字符导致语法错误"""
        # FTS5 特殊字符: ^ * + - ~ ( ) { } [ ] " : . 和空格
        # 如果包含特殊字符，用双引号括起来
        if any(c in query for c in '-"^+~(){}[]:.'):
            # 转义内部的引号
            escaped = query.replace('"', '""')
            return f'"{escaped}"'
        return query

    def _get_parent_dir(self, file_path: str) -> str:
        """获取文件父目录"""
        parts = file_path.split("/")
        if len(parts) > 1:
            return "/".join(parts[:-1])
        return ""

    def _file_module(self, file_path: str) -> str:
        """根据文件路径推断所属模块名"""
        parts = file_path.split("/")
        # 动态获取已知仓库名（加上常见语言目录名）
        from app.services._shared import get_active_repo_map
        known_repos = list(get_active_repo_map().keys()) + ["python", "rust", "csrc"]
        for p in parts:
            if p in known_repos:
                idx = parts.index(p)
                if idx + 1 < len(parts):
                    return parts[idx + 1]
        return "unknown"

    def _entry_to_dict(self, entry: AIMemory) -> Dict[str, Any]:
        """将 AIMemory ORM 对象转为 dict"""
        return {
            "id": entry.id,
            "content": entry.content,
            "source_type": entry.source_type,
            "source_ref": entry.source_ref,
            "tags": json.loads(entry.tags) if entry.tags else [],
            "checksum": entry.checksum,
            "created_at": entry.created_at.isoformat() + "Z" if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() + "Z" if entry.updated_at else None,
            "last_accessed_at": entry.last_accessed_at.isoformat() + "Z" if entry.last_accessed_at else None,
            "access_count": entry.access_count or 0,
            "is_stale": entry.is_stale or False,
        }