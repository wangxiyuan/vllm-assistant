"""
SQLAlchemy ORM 模型
对应 DESIGN.md 数据模型章节（lines 211-278）
"""
import json
from typing import Dict, Any, Optional
from datetime import datetime, timezone, date

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Date,
    Boolean,
    Text,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """将 naive datetime（UTC）序列化为带 Z 后缀的 ISO 字符串。

    DB 里所有 datetime 都以 naive UTC 存储（``datetime.now(timezone.utc).replace(tzinfo=None)`` 或
    ``_parse_dt`` 剥掉 tzinfo 后存入）。如果不加 ``Z``，浏览器会按本地时间
    解析，导致 UTC+8 用户看到的时间差 8 小时。这里统一补 ``Z``，让前端
    ``new Date()`` 正确识别为 UTC 并自动转换。
    """
    if dt is None:
        return None
    # 如果已经是 aware datetime，转成 UTC 再序列化
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"


class Item(Base):
    """缓存的issue/PR数据"""

    __tablename__ = "items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(10), nullable=False)  # 'issue' or 'pr'
    number = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text)  # issue/PR 正文（用于 AI 推荐标签）
    state = Column(String(20), nullable=False)  # 'open', 'closed', 'merged'
    labels = Column(Text)  # JSON array of label names
    area = Column(String(50))  # mapped from CODEOWNERS / labels
    author = Column(String(100))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    comments = Column(Integer, default=0)
    url = Column(String(500))
    base_sha = Column(String(40))  # for PR: base branch head sha
    head_sha = Column(String(40))  # for PR: current head sha
    additions = Column(Integer, default=0)  # for PR: lines added
    deletions = Column(Integer, default=0)  # for PR: lines deleted
    changed_files = Column(Integer, default=0)  # for PR: number of files changed
    last_sync = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("type", "number", name="uq_items_type_number"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "number": self.number,
            "title": self.title,
            "body": self.body or "",
            "state": self.state,
            "labels": json.loads(self.labels) if self.labels else [],
            "area": self.area,
            "author": self.author,
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
            "comments": self.comments,
            "url": self.url,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "additions": self.additions,
            "deletions": self.deletions,
            "changed_files": self.changed_files,
            "last_sync": _iso_utc(self.last_sync),
        }


class MyPR(Base):
    """用户的PR数据"""

    __tablename__ = "my_prs"

    pr_number = Column(Integer, primary_key=True)
    title = Column(Text)
    state = Column(String(20))  # 'open', 'merged', 'closed'
    branch = Column(String(200))
    base_sha = Column(String(40))  # main branch HEAD sha when PR was created
    head_sha = Column(String(40))  # current PR head sha
    ci_status = Column(String(20))  # 'pass', 'fail', 'pending', 'unknown'
    conflict_detected = Column(Boolean, default=False)
    conflict_commits = Column(Integer, default=0)  # how many commits behind main
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    changed_files = Column(Integer, default=0)
    created_at = Column(DateTime)  # PR 创建时间（GitHub API created_at，用于月度趋势）
    last_sync = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pr_number": self.pr_number,
            "title": self.title,
            "state": self.state,
            "branch": self.branch,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "ci_status": self.ci_status,
            "conflict_detected": self.conflict_detected,
            "conflict_commits": self.conflict_commits,
            "additions": self.additions,
            "deletions": self.deletions,
            "changed_files": self.changed_files,
            "created_at": _iso_utc(self.created_at),
            "last_sync": _iso_utc(self.last_sync),
        }


class Area(Base):
    """领域定义（来自 CODEOWNERS 解析）"""

    __tablename__ = "areas"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    paths = Column(Text)  # JSON array of file paths (from CODEOWNERS)
    description = Column(Text)
    last_sync = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "paths": json.loads(self.paths) if self.paths else [],
            "description": self.description,
        }


class Watchlist(Base):
    """特别关注列表（用户手动收藏的 issue/PR）"""

    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    number = Column(Integer, nullable=False)  # issue/PR 编号
    item_type = Column(String(10), nullable=False)  # 'issue' or 'pr'
    title = Column(Text)
    url = Column(String(500))
    area = Column(String(50))  # 领域 ID（如 'attention', 'model'）
    issue_type = Column(String(30))  # issue 分类（如 'bug', 'rfc'），PR 为 None
    state = Column(String(20))  # 'open' / 'closed' / 'merged'
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("number", "item_type", name="uq_watchlist_number_type"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "number": self.number,
            "item_type": self.item_type,
            "title": self.title,
            "url": self.url,
            "area": self.area,
            "issue_type": self.issue_type,
            "state": self.state,
            "added_at": _iso_utc(self.added_at),
        }


class UserIssue(Base):
    """用户创建的 Issue 缓存（scheduler 同步）"""

    __tablename__ = "user_issues"

    number = Column(Integer, primary_key=True)
    title = Column(Text)
    body = Column(Text)
    state = Column(String(20))  # 'open' / 'closed'
    author = Column(String(100))
    labels = Column(Text)  # JSON array
    area = Column(String(50))
    comments = Column(Integer, default=0)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    url = Column(String(500))
    last_sync = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "state": self.state,
            "author": self.author,
            "comments": self.comments,
            "labels": json.loads(self.labels) if self.labels else [],
            "area": self.area,
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
            "url": self.url,
            "body": self.body or "",
        }


class AICache(Base):
    """AI 输出缓存（本地存储，不写 GitHub）

    按 (item_type, number, action) 唯一：action 可以是 'summary' 或 'review'。
    每次 AI 调用成功后覆盖写；打开 drawer 时先读缓存，避免重复调用。
    """

    __tablename__ = "ai_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(String(10), nullable=False)  # 'pr' / 'issue'
    number = Column(Integer, nullable=False)
    action = Column(String(20), nullable=False)  # 'summary' / 'review'
    result = Column(Text)  # JSON 字符串：summary 存 {"summary": "..."}；review 存完整结构
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("item_type", "number", "action", name="uq_ai_cache_key"),
    )


class PersonalTask(Base):
    """个人任务（DESIGN-PERSONAL-TODO.md 2.1）"""

    __tablename__ = "personal_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    description = Column(Text)

    # 来源分类: 'self' / 'team' / 'community' / 'meeting'
    source = Column(String(50), nullable=False)
    # 优先级: P0 / P1 / P2 / P3
    priority = Column(String(10), nullable=False, default="P2")
    # 状态: todo / in_progress / done / cancelled
    status = Column(String(20), nullable=False, default="todo")

    # 关联外部资源
    related_issue_number = Column(Integer)
    related_pr_number = Column(Integer)
    related_url = Column(String(500))

    # 分类
    area = Column(String(50))
    tags = Column(Text)  # JSON array

    # 时间追踪
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    due_date = Column(Date)
    completed_at = Column(DateTime)

    # AI 辅助字段
    dedup_check_result = Column(Text)  # JSON: 去重检查结果

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "source": self.source,
            "priority": self.priority,
            "status": self.status,
            "related_issue_number": self.related_issue_number,
            "related_pr_number": self.related_pr_number,
            "related_url": self.related_url,
            "area": self.area,
            "tags": json.loads(self.tags) if self.tags else [],
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "completed_at": _iso_utc(self.completed_at),
            "dedup_check_result": json.loads(self.dedup_check_result) if self.dedup_check_result else None,
        }


class TaskDedupCache(Base):
    """去重检查缓存（DESIGN-PERSONAL-TODO.md 2.2）"""

    __tablename__ = "task_dedup_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("personal_tasks.id"))
    check_type = Column(String(20))  # 'keyword' / 'semantic' / 'hybrid'
    matched_items = Column(Text)  # JSON: 匹配到的 issue/PR 列表
    checked_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class IntelligenceReport(Base):
    """洞察报告（DESIGN-PERSONAL-TODO.md 2.3）"""

    __tablename__ = "intelligence_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    content = Column(Text)  # nullable: generating/failed 状态时可能为空

    # 关联信息
    task_id = Column(Integer, ForeignKey("personal_tasks.id"))

    # 来源范围 JSON 数组: ["vllm", "vllm-ascend", "sglang", "academic", "news"]
    sources = Column(Text, nullable=False)
    excluded_sources = Column(Text)  # JSON array
    extra_prompt = Column(Text)

    # 元信息
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    status = Column(String(20), default="completed")  # generating / completed / failed
    error_message = Column(Text)

    def to_dict(self, include_content: bool = False, task_title: str = None) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "title": self.title,
            "task_id": self.task_id,
            "sources": json.loads(self.sources) if self.sources else [],
            "excluded_sources": json.loads(self.excluded_sources) if self.excluded_sources else [],
            "extra_prompt": self.extra_prompt or "",
            "created_at": _iso_utc(self.created_at),
            "status": self.status,
            "error_message": self.error_message,
            "word_count": len((self.content or "").split()) if self.content else 0,
        }
        if task_title is not None:
            d["task_title"] = task_title
        if include_content:
            d["content"] = self.content or ""
        return d


# ======================================================================
# 学习文章管理系统（DESIGN-ARTICLES.md）
# ======================================================================


class Article(Base):
    """学习文章"""
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    content = Column(Text, nullable=False)  # Markdown 原文
    rendered_html = Column(Text)  # 渲染后的 HTML（缓存）

    # 元信息
    area = Column(String(50))  # 所属领域 (engine/model/...)
    tags = Column(Text)  # JSON array
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    # 状态
    status = Column(String(20), nullable=False, default="draft")  # draft / published / archived

    # 代码引用统计
    code_refs_count = Column(Integer, default=0)
    valid_refs_count = Column(Integer, default=0)
    outdated_refs_count = Column(Integer, default=0)

    # 最后验证时间
    last_verified_at = Column(DateTime)

    # ORM 关系
    refs = relationship("CodeReference", back_populates="article",
                        cascade="all, delete-orphan")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "area": self.area,
            "tags": json.loads(self.tags) if self.tags else [],
            "status": self.status,
            "code_refs_count": self.code_refs_count or 0,
            "valid_refs_count": self.valid_refs_count or 0,
            "outdated_refs_count": self.outdated_refs_count or 0,
            "last_verified_at": _iso_utc(self.last_verified_at),
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class CodeReference(Base):
    """文章中的代码引用记录"""
    __tablename__ = "code_references"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)

    # 引用位置（在文章中的位置）
    article_line_start = Column(Integer)
    article_line_end = Column(Integer)

    # 引用目标
    repo_name = Column(String(100), nullable=False)  # 仓库名，如 vllm、vllm-ascend
    file_path = Column(String(500), nullable=False)  # 仓库内相对路径
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer)

    # 引用内容快照
    content_snapshot = Column(Text)
    content_hash = Column(String(64))

    # 验证状态
    last_checked_at = Column(DateTime)
    is_valid = Column(Boolean, default=True)
    current_content = Column(Text)  # 当前代码内容（用于渲染）
    diff_summary = Column(Text)  # 变化摘要

    # ORM 关系
    article = relationship("Article", back_populates="refs")


class LocalCodeCache(Base):
    """本地代码缓存（按仓库隔离）"""
    __tablename__ = "local_code_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(100), nullable=False, default="vllm")
    file_path = Column(String(500), nullable=False)
    content = Column(Text)
    last_synced_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    checksum = Column(String(64))
    total_lines = Column(Integer)

    __table_args__ = (
        UniqueConstraint("repo", "file_path", name="uq_repo_file"),
    )


class RepoCache(Base):
    """已缓存的本地仓库记录"""
    __tablename__ = "repo_caches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(100), unique=True, nullable=False)
    clone_url = Column(String(500), nullable=False)
    local_path = Column(String(500), nullable=False)
    branch = Column(String(50), default="main")
    last_synced_at = Column(DateTime)
    commit_sha = Column(String(40))


class FileChangeHistory(Base):
    """文件变更历史记录（scheduler 同步时填充）

    记录每个 PR 变更了哪些文件，用于 O(1) 查询文件变更历史。
    避免了全表扫描 + GitHub API 调用的低效方案。
    """
    __tablename__ = "file_change_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(100), nullable=False, default="vllm")
    file_path = Column(String(500), nullable=False)
    pr_number = Column(Integer, nullable=False)
    pr_title = Column(Text)
    pr_state = Column(String(20))
    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    change_status = Column(String(20), default="modified")  # added / modified / removed
    last_synced_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        Index("idx_fch_repo_file", "repo", "file_path", mysql_length=255),
        Index("idx_fch_pr_number", "pr_number"),
    )
