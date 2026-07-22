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
    tags: List[str] = []
    due_date: Optional[date] = None
    related_issue_number: Optional[int] = None
    related_pr_number: Optional[int] = None
    related_url: str = ""
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
    tags: Optional[List[str]] = None
    due_date: Optional[date] = None
    related_issue_number: Optional[int] = None
    related_pr_number: Optional[int] = None
    related_url: Optional[str] = None

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

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, v):
        if v <= 0:
            raise ValueError("task_id must be positive")
        return v
