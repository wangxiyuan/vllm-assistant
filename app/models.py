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
    Float,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    UniqueConstraint,
    JSON,
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
    repo = Column(String(100), nullable=False)
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
        UniqueConstraint("repo", "type", "number", name="uq_items_repo_type_number"),
        Index("idx_items_type_state", "type", "state"),
        Index("idx_items_area", "area"),
        Index("idx_items_updated_at", "updated_at"),
        Index("idx_items_repo", "repo"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
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

    __table_args__ = (
        # 复合主键：一个用户在一个仓库可以有一个 PR 一次
        PrimaryKeyConstraint("repo", "pr_number", "github_id", name="pk_my_prs"),
        Index("idx_my_prs_state", "state"),
        Index("idx_my_prs_created_at", "created_at"),
        Index("idx_my_prs_github_id", "github_id"),
    )

    repo = Column(String(100), primary_key=True)
    pr_number = Column(Integer, primary_key=True)
    github_id = Column(String(100), nullable=True, default="", primary_key=True)
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
            "repo": self.repo,
            "pr_number": self.pr_number,
            "github_id": self.github_id,
            "author": self.github_id or "",
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
    repo = Column(String(100))
    number = Column(Integer, nullable=False)  # issue/PR 编号
    item_type = Column(String(10), nullable=False)  # 'issue' or 'pr'
    title = Column(Text)
    url = Column(String(500))
    area = Column(String(50))  # 领域 ID（如 'attention', 'model'）
    issue_type = Column(String(30))  # issue 分类（如 'bug', 'rfc'），PR 为 None
    state = Column(String(20))  # 'open' / 'closed' / 'merged'
    note = Column(Text)  # 用户备注，可选
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 责任人
    added_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    # 最近一次状态跃迁时间（open -> closed/merged 等），由定时刷新任务维护；
    # 前端据此在总览页展示"状态变化"提示
    last_state_change_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint("repo", "number", "item_type", name="uq_watchlist_repo_number_type"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "number": self.number,
            "item_type": self.item_type,
            "title": self.title,
            "url": self.url,
            "area": self.area,
            "issue_type": self.issue_type,
            "state": self.state,
            "note": self.note or "",
            "assignee_id": self.assignee_id,
            "added_at": _iso_utc(self.added_at),
            "last_state_change_at": _iso_utc(self.last_state_change_at),
        }


class UserIssue(Base):
    """用户创建的 Issue 缓存（scheduler 同步）"""

    __tablename__ = "user_issues"

    __table_args__ = (
        PrimaryKeyConstraint("number", "github_id", name="pk_user_issues"),
        Index("idx_user_issues_state", "state"),
        Index("idx_user_issues_github_id", "github_id"),
    )

    number = Column(Integer, primary_key=True)
    github_id = Column(String(100), nullable=True, default="", primary_key=True)
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
        Index("idx_ai_cache_created_at", "created_at"),
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

    # 关联外部资源（JSON 数组，每个元素包含 repo/number/type/url）
    related_refs = Column(JSON, default=list)

    # 分类
    area = Column(String(50))
    tags = Column(Text)  # JSON array

    # 责任人
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 任务责任人

    # 子任务关系
    parent_id = Column(Integer, ForeignKey("personal_tasks.id"), nullable=True, default=None)
    subtask_order = Column(Integer, default=0)  # 子任务排序序号

    # 时间追踪
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    due_date = Column(Date)
    completed_at = Column(DateTime)

    # ORM 关系
    children = relationship("PersonalTask", backref="parent", remote_side=[id],
                            cascade="all, delete")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description or "",
            "source": self.source,
            "priority": self.priority,
            "status": self.status,
            "parent_id": self.parent_id,
            "subtask_order": self.subtask_order,
            "related_refs": self.related_refs if self.related_refs else [],
            "area": self.area,
            "assignee_id": self.assignee_id,
            "tags": json.loads(self.tags) if self.tags else [],
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "completed_at": _iso_utc(self.completed_at),
        }


class IntelligenceReport(Base):
    """洞察报告（DESIGN-PERSONAL-TODO.md 2.3）"""

    __tablename__ = "intelligence_reports"

    __table_args__ = (
        Index("idx_intel_reports_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    content = Column(Text)  # nullable: generating/failed 状态时可能为空

    # 关联信息
    task_id = Column(Integer, ForeignKey("personal_tasks.id"))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 创建人

    # 来源范围 JSON 数组: ["vllm", "vllm-ascend", "sglang", "academic", "news"]
    sources = Column(Text, nullable=False)
    excluded_sources = Column(Text)  # JSON array
    extra_prompt = Column(Text)

    # 元信息
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    status = Column(String(20), default="completed")  # generating / completed / failed
    error_message = Column(Text)
    category = Column(String(50), default="manual", index=True)  # daily / manual

    def to_dict(self, include_content: bool = False, task_title: str = None) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "title": self.title,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "sources": json.loads(self.sources) if self.sources else [],
            "excluded_sources": json.loads(self.excluded_sources) if self.excluded_sources else [],
            "extra_prompt": self.extra_prompt or "",
            "created_at": _iso_utc(self.created_at),
            "status": self.status,
            "category": self.category or "manual",
            "error_message": self.error_message,
            "word_count": len((self.content or "").split()) if self.content else 0,
        }
        if task_title is not None:
            d["task_title"] = task_title
        if include_content:
            d["content"] = self.content or ""
        return d


class IntelligenceReportTrace(Base):
    """报告生成过程痕迹（每阶段一条，含提示词/工具调用/用量，供追溯）"""

    __tablename__ = "intelligence_report_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("intelligence_reports.id", ondelete="CASCADE"), nullable=False, index=True)

    # 阶段信息
    stage = Column(String(20), nullable=False)  # search / detail / report / fallback
    stage_index = Column(Integer, default=0)
    system_prompt = Column(Text)  # 该阶段完整 instructions
    user_input = Column(Text)     # 阶段用户输入（可能含上一阶段结果）

    # 执行结果
    final_output = Column(Text)
    tool_calls = Column(Text)     # JSON: [{name, arguments, output}]
    turns = Column(Integer, default=0)
    usage = Column(Text)          # JSON: {input_tokens, output_tokens, total_tokens}

    # 运行时元信息
    temperature = Column(Float)
    max_turns = Column(Integer)
    model = Column(String(100))
    duration_ms = Column(Integer)
    fallback = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "report_id": self.report_id,
            "stage": self.stage,
            "stage_index": self.stage_index or 0,
            "system_prompt": self.system_prompt or "",
            "user_input": self.user_input or "",
            "final_output": self.final_output or "",
            "tool_calls": json.loads(self.tool_calls) if self.tool_calls else [],
            "turns": self.turns or 0,
            "usage": json.loads(self.usage) if self.usage else {},
            "temperature": self.temperature,
            "max_turns": self.max_turns,
            "model": self.model or "",
            "duration_ms": self.duration_ms or 0,
            "fallback": bool(self.fallback),
            "created_at": _iso_utc(self.created_at),
        }


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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 作者
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
        # 解析作者名
        user_name = None
        if self.user_id is not None:
            try:
                from app.database import SessionLocal
                db = SessionLocal()
                user = db.query(User).filter(User.id == self.user_id).first()
                if user:
                    user_name = user.name
                db.close()
            except Exception:
                pass
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "area": self.area,
            "tags": json.loads(self.tags) if self.tags else [],
            "user_id": self.user_id,
            "user_name": user_name,
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
    repo = Column(String(100), nullable=False)
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
    status = Column(String(20), default="active")  # active / deleted
    tracked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "clone_url": self.clone_url,
            "local_path": self.local_path,
            "branch": self.branch or "main",
            "last_synced_at": _iso_utc(self.last_synced_at),
            "commit_sha": self.commit_sha,
            "status": self.status or "active",
            "tracked": bool(self.tracked),
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class User(Base):
    """用户（非租户，仅用于责任人关联）"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # 姓名
    github_id = Column(String(100), nullable=False)  # GitHub ID，必填
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "github_id": self.github_id,
            "created_at": _iso_utc(self.created_at),
        }


class FileChangeHistory(Base):
    """文件变更历史记录（scheduler 同步时填充）

    记录每个 PR 变更了哪些文件，用于 O(1) 查询文件变更历史。
    避免了全表扫描 + GitHub API 调用的低效方案。
    """
    __tablename__ = "file_change_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo = Column(String(100), nullable=False)
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


# ======================================================================
# 模型拆解模块（building_block / model_assembly，YAML 为唯一数据源）
# ======================================================================


class BuildingBlock(Base):
    """积木（building_block）：atomic（原子）或 composite（组合）零件"""

    __tablename__ = "building_block"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False, unique=True)
    kind = Column(String(20), nullable=False, default="atomic")  # atomic / composite
    category = Column(String(50), nullable=False, default="other")
    description = Column(Text)
    formula = Column(Text)          # JSON（计算公式，list[string]；如 y = x·Wᵀ + b）
    params_schema = Column(Text)  # JSON（JSON Schema）
    ports = Column(Text)          # JSON（inputs/outputs 端口 + 形状表达式）
    config = Column(Text)         # JSON（用户随 YAML 提供的模型 config，供 ${config.x} 解析）
    children = Column(Text)       # JSON（composite 子积木列表 + edges + segments）
    vllm = Column(Text)           # JSON（vllm 类/文件/权重映射）
    state = Column(Text)          # JSON（含内状态积木，如 KDA conv_state/recurrent_state）
    yaml = Column(Text)           # 该积木的原始 YAML 片段（round-trip 溯源）
    checksum = Column(String(64)) # yaml 内容哈希
    tags = Column(Text)           # JSON array
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        # vllm 列承载的平铺实现字段（file/weights/ops/edges/segments/notes）
        extra = json.loads(self.vllm) if self.vllm else {}
        d = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "category": self.category,
            "description": self.description or "",
            "formula": json.loads(self.formula) if self.formula else [],
            "params_schema": json.loads(self.params_schema) if self.params_schema else {},
            "ports": json.loads(self.ports) if self.ports else {"inputs": [], "outputs": []},
            "config": json.loads(self.config) if self.config else {},
            "children": json.loads(self.children) if self.children else [],
            "state": json.loads(self.state) if self.state else [],
            "yaml": self.yaml or "",
            "checksum": self.checksum or "",
            "tags": json.loads(self.tags) if self.tags else [],
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }
        # 平铺实现字段到顶层；只放行受支持的键（过滤历史遗留 class/base_class 等）
        _flat_allow = {
            "file", "weights", "ops", "edges", "segments",
            "forward_note", "weight_prefix_note", "note",
        }
        for k, v in extra.items():
            if k in _flat_allow and v:
                d[k] = v
        return d


class ModelAssembly(Base):
    """模型组装（model_assembly）：把积木搭成模型成品"""

    __tablename__ = "model_assembly"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False, unique=True)
    kind = Column(String(20), nullable=False, default="assembly")
    category = Column(String(50), nullable=False, default="other")
    description = Column(Text)
    definition = Column(Text)  # JSON（steps + edges + ports）
    config = Column(Text)      # JSON（用户随 YAML 提供的模型 config）
    checksum = Column(String(64))
    tags = Column(Text)        # JSON array
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "category": self.category,
            "description": self.description or "",
            "definition": json.loads(self.definition) if self.definition else {"steps": [], "edges": [], "ports": {}},
            "config": json.loads(self.config) if self.config else {},
            "checksum": self.checksum or "",
            "tags": json.loads(self.tags) if self.tags else [],
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class AIMemory(Base):
    """持久记忆/知识库条目（AI Agent 用）

    存储从 issue/PR/文档/代码/对话中提取的结构化知识，
    通过 FTS5 全文检索，供 AI 调用时快速 recall。
    """
    __tablename__ = "ai_memory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)  # 知识内容（Markdown 格式）
    source_type = Column(String(30), nullable=False, default="manual")  # issue/pr/article/conversation/manual/code_structure/docs
    source_ref = Column(Text)  # 来源引用，如 "vllm-project/vllm#1234"
    tags = Column(Text)  # JSON 数组标签，如 '["attention","kernel"]'
    checksum = Column(String(64))  # 文件内容 hash（增量更新用，非代码/文档知识为 null）
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    last_accessed_at = Column(DateTime)  # 最后访问时间
    access_count = Column(Integer, default=0)  # 访问次数
    is_stale = Column(Boolean, default=False)  # 是否过时

    __table_args__ = (
        Index("idx_ai_memory_source_type", "source_type"),
        Index("idx_ai_memory_source_ref", "source_ref"),
        Index("idx_ai_memory_updated_at", "updated_at"),
        Index("idx_ai_memory_is_stale", "is_stale"),
    )


class AIChatSession(Base):
    """AI 对话会话"""
    __tablename__ = "ai_chat_sessions"

    id = Column(String(36), primary_key=True)  # UUID
    title = Column(String(200), default="新对话")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    message_count = Column(Integer, default=0)


class AIChatMessage(Base):
    """AI 对话消息"""
    __tablename__ = "ai_chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user / assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    # 对话过程（thinking/工具调用），JSON 字符串；assistant 消息可能携带，user 消息为空
    steps = Column(Text, nullable=True)
    # 应答用量与耗时（可选）
    usage = Column(Text, nullable=True)
    duration_s = Column(Float, nullable=True)


class QuickPrompt(Base):
    """AI Agent 常用提示"""
    __tablename__ = "quick_prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class Comment(Base):
    """评论（多态关联，支持 article / report 等目标类型）"""
    __tablename__ = "comments"
    __table_args__ = (
        Index("idx_comments_target", "target_type", "target_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_type = Column(String(20), nullable=False)   # 'article' | 'report'
    target_id = Column(Integer, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    content = Column(Text, nullable=False)
    rendered_html = Column(Text)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        user_name = None
        if self.user_id is not None:
            try:
                from app.database import SessionLocal
                db = SessionLocal()
                user = db.query(User).filter(User.id == self.user_id).first()
                if user:
                    user_name = user.name
                db.close()
            except Exception:
                pass
        return {
            "id": self.id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "user_id": self.user_id,
            "user_name": user_name,
            "content": self.content,
            "rendered_html": self.rendered_html or "",
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class SlackConfig(Base):
    """Slack 采集配置"""
    __tablename__ = "slack_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(Text)  # Slack xoxc token（前端配置）
    cookie = Column(Text)  # Slack xoxd cookie（前端配置）
    channels = Column(Text)  # JSON 数组，如 '["#general","#development"]'
    collect_interval = Column(Integer, default=360)  # 采集间隔（分钟）
    collect_lookback = Column(Integer, default=1440)  # 每次采集回溯多少分钟的数据（默认1天）
    cred_exists = Column(Boolean, default=False)
    last_collect_at = Column(DateTime)
    total_messages = Column(Integer, default=0)
    last_refresh_at = Column(DateTime)  # 最近一次成功刷新凭证的时间
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "token": self.token or "",
            "cookie": self.cookie or "",
            "cred_exists": self.cred_exists or False,
            "channels": json.loads(self.channels) if self.channels else [],
            "collect_interval": self.collect_interval or 360,
            "collect_lookback": self.collect_lookback or 1440,
            "last_collect_at": _iso_utc(self.last_collect_at),
            "total_messages": self.total_messages or 0,
            "last_refresh_at": _iso_utc(self.last_refresh_at),
            "updated_at": _iso_utc(self.updated_at),
            "created_at": _iso_utc(self.created_at),
        }


# ======================================================================
# AI 筛选规则（总览页）：每条规则 = 一段自然语言筛选要求，
# 定时对社区条目（items）做增量分诊，命中结果在总览页按规则分 tab 展示
# ======================================================================


class AIRule(Base):
    """AI 筛选规则（每条 enabled 规则在总览页呈现为一个 tab）"""

    __tablename__ = "ai_triage_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # tab 显示名
    prompt = Column(Text, nullable=False)  # 自然语言筛选要求
    item_type = Column(String(10), nullable=False, default="both")  # 'pr' / 'issue' / 'both'
    include_commits = Column(Boolean, default=True)  # 是否同时分析已合入 commit
    repos = Column(Text)  # JSON array，完整仓库名（与 items.repo 同格式），空 = 全部
    areas = Column(Text)  # JSON array，领域 ID（areas.id），空 = 全部
    enabled = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, default=0)  # tab 排序
    last_triage_at = Column(DateTime)  # 增量水位线：只分诊 items.last_sync 晚于该时间的条目
    last_run_at = Column(DateTime)  # 最近一次执行时间（含无候选的空跑）
    last_error = Column(Text)  # 最近一次失败原因，成功后清空
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self, match_count: Optional[int] = None) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "item_type": self.item_type or "both",
            "include_commits": self.include_commits if self.include_commits is not None else True,
            "repos": json.loads(self.repos) if self.repos else [],
            "areas": json.loads(self.areas) if self.areas else [],
            "enabled": bool(self.enabled),
            "sort_order": self.sort_order or 0,
            "last_triage_at": _iso_utc(self.last_triage_at),
            "last_run_at": _iso_utc(self.last_run_at),
            "last_error": self.last_error,
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }
        if match_count is not None:
            d["match_count"] = match_count
        return d


class AIRuleMatch(Base):
    """AI 筛选规则命中结果

    存编号引用而非 items.id 外键（items 会被清理任务删除），
    展示时按 (repo, item_type, number) join items。
    """

    __tablename__ = "ai_triage_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("ai_triage_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    repo = Column(String(100), nullable=False)
    item_type = Column(String(10), nullable=False)  # 'pr' / 'issue'
    number = Column(Integer, nullable=False)
    reason = Column(Text)  # AI 给出的一句话命中理由
    matched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("rule_id", "repo", "item_type", "number", name="uq_ai_rule_match"),
    )


class AIRuleCommitMatch(Base):
    """AI 筛选规则的 commit 命中结果

    commit 没有 number，无法复用 AIRuleMatch（number 为非空 Integer），
    单独成表；repo 存全名（与 items.repo 同格式），冗余展示字段
    （title/author/committed_at）避免依赖本地 git 仓库存活。
    """

    __tablename__ = "ai_triage_commit_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("ai_triage_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    repo = Column(String(100), nullable=False)  # owner/name 全名
    sha = Column(String(40), nullable=False)
    short_sha = Column(String(10))
    title = Column(Text)  # commit subject
    author = Column(String(200))
    committed_at = Column(DateTime)
    reason = Column(Text)  # AI 给出的一句话命中理由
    matched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("rule_id", "repo", "sha", name="uq_ai_rule_commit_match"),
    )


# ======================================================================
# NPU 算力管理：机器纳管（SSH）、容器任务、模型服务部署、Profiling 采集、
# 用例测试与 benchmark。所有任务统一通过 docker 容器在 NPU 机器上运行
# （巡检除外，巡检在宿主机跑 npu-smi），机型差异由 profiles 模板吸收。
# ======================================================================


class NpuMachine(Base):
    """NPU 机器（SSH 纳管）"""

    __tablename__ = "npu_machines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)  # 展示名，也是 docker 主机别名
    host = Column(String(200), nullable=False)
    port = Column(Integer, nullable=False, default=22)
    username = Column(String(100), nullable=False)
    auth_type = Column(String(20), nullable=False, default="key")  # 'key' / 'password'
    key_path = Column(String(500))  # 服务端私钥文件路径（兼容模式，优先用 key_content）
    key_content_enc = Column(Text)  # Fernet 加密的私钥内容（前端粘贴/文件读取，优先于 key_path）
    password_enc = Column(Text)  # Fernet 加密的密码（auth_type=password 时使用），永不外泄
    machine_type = Column(String(20), nullable=False, default="a2")  # a2 / a3 / 310p / other
    workdir = Column(String(500), default="~/npu-workspace")  # 远程工作目录（任务/日志/profiling 根）
    model_root = Column(String(500))  # 模型仓库根目录（扫描模型权重目录用）
    tags = Column(Text)  # JSON array，自定义标签（用途/位置等）
    status = Column(String(20), nullable=False, default="unknown")  # online / offline / unknown
    status_message = Column(Text)  # 最近一次巡检的异常信息
    last_check_at = Column(DateTime)
    npu_count = Column(Integer)  # NPU 卡数（纳管探测/巡检更新）
    npu_chip = Column(String(100))  # 芯片型号
    driver_version = Column(String(200))
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        Index("idx_npu_machines_status", "status"),
    )

    def to_ssh_params(self) -> Dict[str, Any]:
        """SSH 层连接参数（含加密密码/私钥内容，仅限服务端内部使用，勿返回给前端）"""
        return {
            "host": self.host,
            "port": self.port or 22,
            "username": self.username,
            "auth_type": self.auth_type or "key",
            "key_path": self.key_path,
            "key_content_enc": self.key_content_enc,
            "password_enc": self.password_enc,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "port": self.port or 22,
            "username": self.username,
            "auth_type": self.auth_type,
            "key_path": self.key_path,
            "has_key_content": bool(self.key_content_enc),
            "has_password": bool(self.password_enc),
            "machine_type": self.machine_type,
            "workdir": self.workdir,
            "model_root": self.model_root,
            "tags": json.loads(self.tags) if self.tags else [],
            "status": self.status,
            "status_message": self.status_message,
            "last_check_at": _iso_utc(self.last_check_at),
            "npu_count": self.npu_count,
            "npu_chip": self.npu_chip,
            "driver_version": self.driver_version,
            "enabled": bool(self.enabled),
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class NpuMachineMetric(Base):
    """机器巡检历史（利用率曲线数据点）"""

    __tablename__ = "npu_machine_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, ForeignKey("npu_machines.id", ondelete="CASCADE"), nullable=False, index=True)
    ts = Column(DateTime, nullable=False, index=True,
                default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    npu_util = Column(Text)  # JSON array，每卡利用率 %
    npu_mem_used = Column(Text)  # JSON array，每卡已用显存 MB
    npu_mem_total = Column(Text)  # JSON array，每卡总显存 MB
    temperature = Column(Text)  # JSON array，每卡温度 ℃
    power = Column(Text)  # JSON array，每卡功耗 W
    cpu = Column(Float)  # 宿主机 CPU 利用率 %
    mem = Column(Float)  # 宿主机内存利用率 %
    disk = Column(Float)  # 宿主机磁盘利用率 %

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "ts": _iso_utc(self.ts),
            "npu_util": json.loads(self.npu_util) if self.npu_util else [],
            "npu_mem_used": json.loads(self.npu_mem_used) if self.npu_mem_used else [],
            "npu_mem_total": json.loads(self.npu_mem_total) if self.npu_mem_total else [],
            "temperature": json.loads(self.temperature) if self.temperature else [],
            "power": json.loads(self.power) if self.power else [],
            "cpu": self.cpu,
            "mem": self.mem,
            "disk": self.disk,
        }


class NpuImage(Base):
    """机器上的容器镜像（巡检扫描缓存，部署表单下拉数据源）"""

    __tablename__ = "npu_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, ForeignKey("npu_machines.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name = Column(String(300), nullable=False)  # repo:tag
    source = Column(String(20), nullable=False, default="scan")  # scan / manual
    scanned_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("machine_id", "full_name", name="uq_npu_image"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "full_name": self.full_name,
            "source": self.source,
            "scanned_at": _iso_utc(self.scanned_at),
        }


class NpuModelDir(Base):
    """机器上的模型权重目录（部署时下拉选择并挂载进容器）"""

    __tablename__ = "npu_model_dirs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, ForeignKey("npu_machines.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(500), nullable=False)
    note = Column(String(300))
    source = Column(String(20), nullable=False, default="scan")  # scan / manual
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("machine_id", "path", name="uq_npu_model_dir"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "path": self.path,
            "note": self.note,
            "source": self.source,
            "created_at": _iso_utc(self.created_at),
        }


class NpuContainerTemplate(Base):
    """容器任务模板（保存整套任务配置，一键套用改参数）"""

    __tablename__ = "npu_container_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    mode = Column(String(20), nullable=False, default="oneshot")  # persistent / oneshot
    machine_type = Column(String(20))  # 适用机型（空 = 通用）
    image = Column(String(300))
    devices = Column(Text)  # JSON array，NPU 卡索引列表（如 [0,1,2,3]）
    mounts = Column(Text)  # JSON array，宿主机:容器内 挂载对列表
    env = Column(Text)  # JSON object，环境变量
    network = Column(String(20), default="host")  # host / bridge
    ports = Column(Text)  # JSON array，"host:container" 端口映射（bridge 模式）
    command = Column(Text)  # 容器内执行命令
    shm_size = Column(String(50))
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode,
            "machine_type": self.machine_type,
            "image": self.image,
            "devices": json.loads(self.devices) if self.devices else [],
            "mounts": json.loads(self.mounts) if self.mounts else [],
            "env": json.loads(self.env) if self.env else {},
            "network": self.network or "host",
            "ports": json.loads(self.ports) if self.ports else [],
            "command": self.command,
            "shm_size": self.shm_size,
            "notes": self.notes,
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class NpuJob(Base):
    """NPU 远程任务（统一任务中心记录）

    type: container(自定义容器任务) / deploy(部署服务) / service_start / service_stop /
          test / benchmark。
    mode: persistent(docker run -d 常驻容器，running 即长期状态，页面可停止) /
          oneshot(docker run --rm 跑完退出，exit_code 落库)。
    payload: 容器规格 JSON（image/devices/mounts/env/network/ports/command/shm_size）
             + docker_cmd（最终生成的完整命令，可复现）。
    日志只落文件系统（log_file 指向 data/npu_jobs/{id}.log），DB 仅存路径与大小。
    """

    __tablename__ = "npu_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, ForeignKey("npu_machines.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), nullable=False, default="container")
    mode = Column(String(20), nullable=False, default="oneshot")  # persistent / oneshot
    name = Column(String(200))
    payload = Column(Text)  # JSON：容器规格 + docker_cmd
    status = Column(String(20), nullable=False, default="pending", index=True)
    # pending / running / completed / failed / cancelled
    exit_code = Column(Integer)
    container_name = Column(String(200))
    log_file = Column(String(500))
    log_size = Column(Integer, default=0)
    error_message = Column(Text)
    source = Column(String(10), nullable=False, default="ui")  # ui / agent
    service_id = Column(Integer, index=True)  # 关联部署实例（deploy/service_start/service_stop）
    test_case_id = Column(Integer, index=True)
    benchmark_id = Column(Integer, index=True)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    __table_args__ = (
        Index("idx_npu_jobs_machine", "machine_id", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "type": self.type,
            "mode": self.mode,
            "name": self.name,
            "payload": json.loads(self.payload) if self.payload else {},
            "status": self.status,
            "exit_code": self.exit_code,
            "container_name": self.container_name,
            "log_file": self.log_file,
            "log_size": self.log_size or 0,
            "error_message": self.error_message,
            "source": self.source,
            "service_id": self.service_id,
            "test_case_id": self.test_case_id,
            "benchmark_id": self.benchmark_id,
            "started_at": _iso_utc(self.started_at),
            "finished_at": _iso_utc(self.finished_at),
            "created_at": _iso_utc(self.created_at),
        }


class NpuServiceInstance(Base):
    """vLLM 模型服务实例（docker 容器形态，生命周期由管理服务托管）

    network=host 时服务端口即 ports[0] 的宿主端口；bridge 时 ports 为
    "host:container" 映射，健康检查走宿主端口。
    """

    __tablename__ = "npu_service_instances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, ForeignKey("npu_machines.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, unique=True)
    model_dir = Column(String(500))  # 模型权重目录（机器路径，挂载进容器）
    model_name = Column(String(200))  # --served-model-name（对外模型名）
    image = Column(String(300), nullable=False)
    container_name = Column(String(200), nullable=False, unique=True)
    mounts = Column(Text)  # JSON array，模型目录等额外挂载
    env = Column(Text)  # JSON object
    network = Column(String(20), nullable=False, default="host")
    ports = Column(Text)  # JSON array
    devices = Column(Text)  # JSON array，NPU 卡索引
    tp = Column(Integer, default=1)  # --tensor-parallel-size
    serve_args = Column(Text)  # vllm serve 额外参数文本
    serve_params = Column(Text)  # JSON：完整结构化 serve 参数（并行策略/内存/精度/JSON 配置），启动/重启重放用
    debug_mode = Column(Boolean, nullable=False, default=False)
    debugpy_port = Column(Integer)  # 调试模式 debugpy 监听端口
    wait_for_client = Column(Boolean, default=False)  # 调试模式是否挂起等 attach
    profiling_enabled = Column(Boolean, nullable=False, default=False)
    profiling_dir = Column(String(500))  # 机器上 profiling 输出目录（与容器内同路径挂载）
    health_url = Column(String(300))
    container_id = Column(String(100))
    status = Column(String(20), nullable=False, default="deploying", index=True)
    # deploying / running / stopped / failed / unknown
    last_health_at = Column(DateTime)
    last_health_ok = Column(Boolean)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "name": self.name,
            "model_dir": self.model_dir,
            "model_name": self.model_name,
            "image": self.image,
            "container_name": self.container_name,
            "mounts": json.loads(self.mounts) if self.mounts else [],
            "env": json.loads(self.env) if self.env else {},
            "network": self.network,
            "ports": json.loads(self.ports) if self.ports else [],
            "devices": json.loads(self.devices) if self.devices else [],
            "tp": self.tp or 1,
            "serve_args": self.serve_args,
            "serve_params": json.loads(self.serve_params) if self.serve_params else {},
            "debug_mode": bool(self.debug_mode),
            "debugpy_port": self.debugpy_port,
            "wait_for_client": bool(self.wait_for_client),
            "profiling_enabled": bool(self.profiling_enabled),
            "profiling_dir": self.profiling_dir,
            "health_url": self.health_url,
            "container_id": self.container_id,
            "status": self.status,
            "last_health_at": _iso_utc(self.last_health_at),
            "last_health_ok": bool(self.last_health_ok) if self.last_health_ok is not None else None,
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class NpuProfileSession(Base):
    """Profiling 采集会话（对应一次 /start_profile → /stop_profile）

    files 为输出目录文件快照 JSON（[{name,size,mtime}]），可 refresh 重扫。
    """

    __tablename__ = "npu_profile_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_id = Column(Integer, ForeignKey("npu_service_instances.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    machine_id = Column(Integer, nullable=False, index=True)
    status = Column(String(20), nullable=False, default="collecting")  # collecting / completed / failed
    output_dir = Column(String(500), nullable=False)  # 机器上的输出目录
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    stopped_at = Column(DateTime)
    duration_s = Column(Float)
    files = Column(Text)  # JSON：[{name, size, mtime}]
    total_size = Column(Integer, default=0)
    notes = Column(Text)
    error_message = Column(Text)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "service_id": self.service_id,
            "machine_id": self.machine_id,
            "status": self.status,
            "output_dir": self.output_dir,
            "started_at": _iso_utc(self.started_at),
            "stopped_at": _iso_utc(self.stopped_at),
            "duration_s": self.duration_s,
            "files": json.loads(self.files) if self.files else [],
            "total_size": self.total_size or 0,
            "notes": self.notes,
            "error_message": self.error_message,
            "created_at": _iso_utc(self.created_at),
        }


class NpuTestCase(Base):
    """测试用例

    kind=container_cmd：在机器上起一次性容器跑 shell 命令（payload: {image?, command}）；
    kind=openai_chat：管理端直接向服务实例发 OpenAI 兼容请求断言响应
    （payload: {message?, expect_keyword?, max_tokens?}）。
    """

    __tablename__ = "npu_test_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    kind = Column(String(20), nullable=False, default="openai_chat")  # container_cmd / openai_chat
    payload = Column(Text)  # JSON，结构随 kind
    target = Column(String(20), nullable=False, default="service")  # machine / service
    timeout_seconds = Column(Integer, default=600)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "payload": json.loads(self.payload) if self.payload else {},
            "target": self.target,
            "timeout_seconds": self.timeout_seconds or 600,
            "enabled": bool(self.enabled),
            "created_at": _iso_utc(self.created_at),
            "updated_at": _iso_utc(self.updated_at),
        }


class NpuTestRun(Base):
    """测试用例运行记录"""

    __tablename__ = "npu_test_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, ForeignKey("npu_test_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    machine_id = Column(Integer, index=True)
    service_id = Column(Integer, index=True)
    job_id = Column(Integer, index=True)  # container_cmd 类关联的远程任务
    status = Column(String(20), nullable=False)  # passed / failed / error
    duration_ms = Column(Float)
    output_summary = Column(Text)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "machine_id": self.machine_id,
            "service_id": self.service_id,
            "job_id": self.job_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "output_summary": self.output_summary,
            "created_at": _iso_utc(self.created_at),
        }


class NpuBenchmarkRun(Base):
    """benchmark 压测记录（指标由 vllm bench serve 输出 JSON 解析）"""

    __tablename__ = "npu_benchmark_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(Integer, ForeignKey("npu_machines.id", ondelete="CASCADE"), nullable=False, index=True)
    service_id = Column(Integer, index=True)
    job_id = Column(Integer, index=True)
    model = Column(String(300))
    endpoint = Column(String(100), default="/v1/completions")
    dataset_name = Column(String(50), default="random")  # random / sharegpt
    dataset_path = Column(String(500))
    num_prompts = Column(Integer, default=10)
    request_rate = Column(Float)
    max_concurrency = Column(Integer)
    params = Column(Text)  # JSON，其余 bench 参数
    status = Column(String(20), nullable=False, default="running")  # running / completed / failed
    total_throughput = Column(Float)
    output_throughput = Column(Float)
    ttft_p50 = Column(Float)
    ttft_p99 = Column(Float)
    tpot_p50 = Column(Float)
    tpot_p99 = Column(Float)
    itl_p50 = Column(Float)
    itl_p99 = Column(Float)
    e2el_p99 = Column(Float)
    success_rate = Column(Float)
    result_file = Column(String(500))  # 机器上结果 JSON 路径
    raw_metrics = Column(Text)  # JSON，原始指标（供后续扩展展示）
    notes = Column(Text)
    error_message = Column(Text)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
                        index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "service_id": self.service_id,
            "job_id": self.job_id,
            "model": self.model,
            "endpoint": self.endpoint,
            "dataset_name": self.dataset_name,
            "dataset_path": self.dataset_path,
            "num_prompts": self.num_prompts,
            "request_rate": self.request_rate,
            "max_concurrency": self.max_concurrency,
            "params": json.loads(self.params) if self.params else {},
            "status": self.status,
            "total_throughput": self.total_throughput,
            "output_throughput": self.output_throughput,
            "ttft_p50": self.ttft_p50,
            "ttft_p99": self.ttft_p99,
            "tpot_p50": self.tpot_p50,
            "tpot_p99": self.tpot_p99,
            "itl_p50": self.itl_p50,
            "itl_p99": self.itl_p99,
            "e2el_p99": self.e2el_p99,
            "success_rate": self.success_rate,
            "result_file": self.result_file,
            "raw_metrics": json.loads(self.raw_metrics) if self.raw_metrics else {},
            "notes": self.notes,
            "error_message": self.error_message,
            "created_at": _iso_utc(self.created_at),
        }
