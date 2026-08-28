"""
Pydantic数据模型（API请求/响应）
"""
from typing import List, Optional
from datetime import datetime, date
from pydantic import BaseModel, field_validator


class MyPRResponse(BaseModel):
    """用户PR响应"""
    repo: str
    pr_number: int
    author: Optional[str] = None
    title: str
    state: str
    branch: Optional[str] = None
    ci_status: str = "unknown"
    conflict_detected: bool = False
    conflict_commits: int = 0
    additions: int = 0  # DESIGN.md 81 行：变更摘要
    deletions: int = 0
    changed_files: int = 0
    last_sync: Optional[datetime] = None

    class Config:
        from_attributes = True


class AIReviewRequest(BaseModel):
    """AI Review 请求"""
    pr_number: int
    include_diff: bool = True
    repo: Optional[str] = None  # 完整 owner/repo，None 时用 Config 默认仓库


# ===== Personal TODO 请求模型 =====

class PersonalTaskCreate(BaseModel):
    """创建个人任务"""
    title: str
    description: str = ""
    source: str = "self"
    priority: str = "P2"
    area: str = ""
    assignee_id: Optional[int] = None
    tags: List[str] = []
    due_date: Optional[date] = None
    related_refs: List[dict] = []
    parent_id: Optional[int] = None  # 父任务 ID，用于创建子任务
    subtask_order: Optional[int] = None  # 子任务排序序号（可选）

    @field_validator("due_date", mode="before")
    @classmethod
    def normalize_due_date(cls, v):
        if v is None or v == "":
            return None
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v):
        if v not in ("self", "team", "community", "meeting"):
            raise ValueError("source must be one of: self, team, community, meeting")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        if v not in ("P0", "P1", "P2", "P3"):
            raise ValueError("priority must be one of: P0, P1, P2, P3")
        return v


class SubtaskRow(BaseModel):
    """批量创建子任务的一行"""
    title: str
    description: str = ""
    priority: Optional[str] = "P2"
    assignee_id: Optional[int] = None
    group: Optional[str] = None  # 所属分组标题，会作为 title 前缀


class BulkSubtaskCreate(BaseModel):
    """批量创建子任务请求"""
    rows: List[SubtaskRow] = []

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, v):
        if not v:
            raise ValueError("rows must not be empty")
        for row in v:
            if not (row.title or "").strip():
                raise ValueError("each subtask row must have a title")
        return v


class MarkdownParseRequest(BaseModel):
    """解析 Markdown 清单，生成子任务行预览"""
    text: str = ""


class MarkdownParseRow(BaseModel):
    """解析出的子任务行"""
    title: str
    description: str = ""
    priority: Optional[str] = "P2"
    assignee_id: Optional[int] = None
    group: Optional[str] = None  # 所属分组标题
    user_id: Optional[int] = None  # 责任人，未匹配到用户时为 None
    skipped: bool = False  # 是否被跳过（纯分隔行/表头）


class MarkdownParseResponse(BaseModel):
    """解析结果"""
    rows: List[MarkdownParseRow] = []


class PersonalTaskUpdate(BaseModel):
    """更新个人任务（所有字段可选）"""
    title: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    area: Optional[str] = None
    assignee_id: Optional[int] = None
    tags: Optional[List[str]] = None
    due_date: Optional[date] = None
    related_refs: Optional[List[dict]] = None
    parent_id: Optional[int] = None  # 父任务 ID
    subtask_order: Optional[int] = None  # 子任务排序序号

    @field_validator("due_date", mode="before")
    @classmethod
    def normalize_due_date(cls, v):
        # 空字符串归一为 None（前端清空日期输入时发送 ''）
        if v is None or v == "":
            return None
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v):
        if v is not None and v not in ("self", "team", "community", "meeting"):
            raise ValueError("source must be one of: self, team, community, meeting")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v):
        if v is not None and v not in ("P0", "P1", "P2", "P3"):
            raise ValueError("priority must be one of: P0, P1, P2, P3")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v):
        if v is not None and v not in ("todo", "in_progress", "done", "cancelled"):
            raise ValueError("status must be one of: todo, in_progress, done, cancelled")
        return v


class IntelligenceGenerateRequest(BaseModel):
    """生成洞察报告请求"""
    task_id: Optional[int] = None  # 关联任务（可选）
    title: str = ""
    sources: List[str] = []  # 空表示用全部可用来源（由后端从 RepoCache 动态解析）
    excluded_sources: List[str] = []
    extra_prompt: str = ""
    user_id: Optional[int] = None  # 创建人
    report_id: Optional[int] = None  # 重新生成时传入，覆盖已有报告

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, v):
        # 0 / None 表示未选择任务（可选）
        if v is None or v == 0:
            return None
        if v < 0:
            raise ValueError("task_id must be positive")
        return v


# ===== 模型拆解（building_block / model_assembly，YAML 为唯一数据源）=====


class BuildingBlockCreate(BaseModel):
    """创建积木"""
    name: str
    kind: str = "atomic"  # atomic / composite
    category: str = "other"
    description: str = ""
    formula: list = []
    params_schema: dict = {}
    ports: dict = {"inputs": [], "outputs": []}
    config: dict = {}
    children: list = []
    # 平铺实现字段（取代历史 vllm 嵌套层）
    file: Optional[str] = None
    weights: list = []
    ops: list = []
    edges: list = []
    segments: list = []
    forward_note: Optional[str] = None
    weight_prefix_note: Optional[str] = None
    note: Optional[str] = None
    state: list = []
    yaml: str = ""
    checksum: str = ""
    tags: list[str] = []


class BuildingBlockUpdate(BaseModel):
    """更新积木（所有字段可选）"""
    name: Optional[str] = None
    kind: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    formula: Optional[list] = None
    params_schema: Optional[dict] = None
    ports: Optional[dict] = None
    config: Optional[dict] = None
    children: Optional[list] = None
    file: Optional[str] = None
    weights: Optional[list] = None
    ops: Optional[list] = None
    edges: Optional[list] = None
    segments: Optional[list] = None
    forward_note: Optional[str] = None
    weight_prefix_note: Optional[str] = None
    note: Optional[str] = None
    state: Optional[list] = None
    yaml: Optional[str] = None
    checksum: Optional[str] = None
    tags: Optional[list[str]] = None


class ModelAssemblyCreate(BaseModel):
    """创建模型组装"""
    name: str
    category: str = "other"
    description: str = ""
    definition: dict = {"steps": [], "edges": [], "ports": {}}
    config: dict = {}
    checksum: str = ""
    tags: list[str] = []


class ModelAssemblyUpdate(BaseModel):
    """更新模型组装（所有字段可选）"""
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    definition: Optional[dict] = None
    config: Optional[dict] = None
    checksum: Optional[str] = None
    tags: Optional[list[str]] = None


class YAMLImportRequest(BaseModel):
    """YAML 导入请求：yaml 文本或多文档 YAML"""
    yaml: str
    source: str = ""  # 可选文件名溯源


class ValidationIssue(BaseModel):
    path: str = ""
    level: str = "error"  # error / warning / info
    message: str = ""


class AnatomyImportResult(BaseModel):
    imported_blocks: int = 0
    imported_assemblies: int = 0
    skipped: int = 0
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []


class QuickPromptCreate(BaseModel):
    """创建常用提示"""
    text: str


class QuickPromptUpdate(BaseModel):
    """更新常用提示"""
    text: Optional[str] = None
    sort_order: Optional[int] = None


class QuickPromptResponse(BaseModel):
    """常用提示响应"""
    id: int
    text: str
    sort_order: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True
