"""
Pydantic数据模型（API请求/响应）
"""
from typing import List, Optional
from datetime import datetime, date
from pydantic import BaseModel, field_validator


class ItemResponse(BaseModel):
    """Issue/PR响应"""
    type: str
    number: int
    title: str
    state: str
    labels: List[str] = []
    area: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    comments: int = 0
    url: Optional[str] = None
    is_new: bool = False  # DESIGN.md 67 行：2 小时内创建高亮

    class Config:
        from_attributes = True


class MyPRResponse(BaseModel):
    """用户PR响应"""
    pr_number: int
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
    """AI Review请求"""
    pr_number: int
    include_diff: bool = True


class AIAnalyzeRequest(BaseModel):
    """AI分析请求"""
    changed_files: List[str]


class AISuggestLabelRequest(BaseModel):
    """AI 推荐 Issue 标签请求（DESIGN.md 135 行：查看 issue 时手动触发）"""
    issue_title: str
    issue_body: str = ""


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
    trigger_dedup_check: bool = False

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


class DedupCheckRequest(BaseModel):
    """去重检查请求"""
    repos: List[str] = []
    check_type: str = "hybrid"

    @field_validator("check_type")
    @classmethod
    def validate_check_type(cls, v):
        if v not in ("keyword", "semantic", "hybrid"):
            raise ValueError("check_type must be one of: keyword, semantic, hybrid")
        return v


class IntelligenceGenerateRequest(BaseModel):
    """生成洞察报告请求"""
    task_id: int
    title: str = ""
    sources: List[str] = ["vllm", "vllm-ascend", "sglang", "academic", "news"]
    excluded_sources: List[str] = []
    extra_prompt: str = ""
    user_id: Optional[int] = None  # 创建人

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, v):
        if v <= 0:
            raise ValueError("task_id must be positive")
        return v


# ===== 模型拆解（docs/model_anatomy.md）=====


class CategoryCreate(BaseModel):
    """创建分类"""
    name: str
    display_name: str
    description: str = ""
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    """更新分类"""
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


class OperatorCreate(BaseModel):
    """创建算子"""
    name: str
    display_name: str
    description: str = ""
    category: str = "other"
    params_schema: dict = {}
    input_shape_desc: str = ""
    output_shape_desc: str = ""
    vllm_code_refs: list = []
    tags: list[str] = []
    user_id: Optional[int] = None  # 责任人


class OperatorUpdate(BaseModel):
    """更新算子（所有字段可选）"""
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    params_schema: Optional[dict] = None
    input_shape_desc: Optional[str] = None
    output_shape_desc: Optional[str] = None
    vllm_code_refs: Optional[list] = None
    tags: Optional[list[str]] = None
    user_id: Optional[int] = None  # 责任人


class OperatorResponse(BaseModel):
    """算子响应"""
    id: int
    name: str
    display_name: str
    description: str = ""
    category: str
    params_schema: dict = {}
    input_shape_desc: str = ""
    output_shape_desc: str = ""
    vllm_code_refs: list = []
    tags: list[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ModelAnatomyCreate(BaseModel):
    """创建模型"""
    name: str
    display_name: str
    description: str = ""
    category: str = "other"
    architecture: list = []
    params_summary: dict = {}
    tags: list[str] = []
    user_id: Optional[int] = None  # 责任人


class ModelAnatomyUpdate(BaseModel):
    """更新模型（所有字段可选）"""
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    architecture: Optional[list] = None
    params_summary: Optional[dict] = None
    tags: Optional[list[str]] = None
    user_id: Optional[int] = None  # 责任人


class ModelAnatomyResponse(BaseModel):
    """模型响应"""
    id: int
    name: str
    display_name: str
    description: str = ""
    category: str = "other"
    architecture: list = []
    params_summary: dict = {}
    operators_count: int = 0
    tags: list[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True
