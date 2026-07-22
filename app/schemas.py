"""
Pydantic数据模型（API请求/响应）
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel


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
