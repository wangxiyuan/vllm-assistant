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
