"""
Pydantic数据模型（API请求/响应）
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


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


class IntelligenceGenerateRequest(BaseModel):
    """生成洞察报告请求"""
    title: str = ""
    sources: List[str] = []  # 空表示用全部可用来源（由后端从 RepoCache 动态解析）
    excluded_sources: List[str] = []
    extra_prompt: str = ""
    user_id: Optional[int] = None  # 创建人
    report_id: Optional[int] = None  # 重新生成时传入，覆盖已有报告


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
