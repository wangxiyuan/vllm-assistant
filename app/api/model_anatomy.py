"""
模型拆解 API（docs/model_anatomy.md）

算子管理 + 模型搭建 CRUD。
所有端点受 AuthMiddleware 保护（全局配置）。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Operator, ModelAnatomy, OperatorCategory
from app.schemas import (
    CategoryCreate,
    CategoryUpdate,
    OperatorCreate,
    OperatorUpdate,
    OperatorResponse,
    ModelAnatomyCreate,
    ModelAnatomyUpdate,
    ModelAnatomyResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ===== 预置算子 =====

PRESET_OPERATORS = [
    # Embedding
    {"name": "Embedding", "display_name": "Embedding", "description": "Token embedding layer that maps input tokens to dense vectors", "category": "embedding", "params_schema": {"type": "object", "properties": {"vocab_size": {"type": "integer", "default": 32000, "description": "Vocabulary size"}, "hidden_size": {"type": "integer", "default": 4096, "description": "Embedding dimension"}}, "required": ["vocab_size", "hidden_size"]}, "input_shape_desc": "(batch_size, seq_len)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # Normalization
    {"name": "RMSNorm", "display_name": "RMS 归一化", "description": "Root Mean Square Layer Normalization", "category": "normalization", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096, "description": "Hidden size"}, "eps": {"type": "number", "default": 1e-6, "description": "Epsilon for numerical stability"}}, "required": ["hidden_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "LayerNorm", "display_name": "Layer 归一化", "description": "Layer Normalization", "category": "normalization", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "eps": {"type": "number", "default": 1e-5}}, "required": ["hidden_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # Attention
    {"name": "MultiHeadAttention", "display_name": "多头注意力", "description": "Multi-Head Attention (MHA)", "category": "attention", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "num_heads": {"type": "integer", "default": 32}, "num_kv_heads": {"type": "integer", "default": 32}, "head_dim": {"type": "integer", "default": 128}}, "required": ["hidden_size", "num_heads"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "GroupedQueryAttention", "display_name": "分组查询注意力", "description": "Grouped-Query Attention (GQA)", "category": "attention", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "num_heads": {"type": "integer", "default": 32}, "num_kv_heads": {"type": "integer", "default": 8}, "head_dim": {"type": "integer", "default": 128}}, "required": ["hidden_size", "num_heads", "num_kv_heads"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "MLA", "display_name": "多头潜注意力", "description": "Multi-head Latent Attention (MLA), used in DeepSeek series", "category": "attention", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 7168}, "num_heads": {"type": "integer", "default": 128}, "kv_lora_rank": {"type": "integer", "default": 512}, "qk_rope_head_dim": {"type": "integer", "default": 64}}, "required": ["hidden_size", "num_heads"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # MLP
    {"name": "MLP", "display_name": "MLP", "description": "Multi-Layer Perceptron (SwiGLU)", "category": "mlp", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "intermediate_size": {"type": "integer", "default": 11008}, "activation": {"type": "string", "default": "silu", "enum": ["silu", "gelu", "relu"]}}, "required": ["hidden_size", "intermediate_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    {"name": "MoE", "display_name": "混合专家", "description": "Mixture of Experts layer with router", "category": "mlp", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 7168}, "intermediate_size": {"type": "integer", "default": 2048}, "num_experts": {"type": "integer", "default": 256}, "num_experts_per_tok": {"type": "integer", "default": 8}}, "required": ["hidden_size", "num_experts"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, hidden_size)"},
    # Positional
    {"name": "RotaryEmbedding", "display_name": "RoPE", "description": "Rotary Position Embedding", "category": "positional", "params_schema": {"type": "object", "properties": {"dim": {"type": "integer", "default": 128}, "max_position_embeddings": {"type": "integer", "default": 131072}, "theta": {"type": "number", "default": 10000}}, "required": ["dim"]}, "input_shape_desc": "position_ids: (batch_size, seq_len)", "output_shape_desc": "cos/sin: (seq_len, dim)"},
    # Output
    {"name": "Linear", "display_name": "线性层", "description": "Linear projection layer", "category": "other", "params_schema": {"type": "object", "properties": {"in_features": {"type": "integer", "default": 4096}, "out_features": {"type": "integer", "default": 32000}, "bias": {"type": "boolean", "default": False}}, "required": ["in_features", "out_features"]}, "input_shape_desc": "(..., in_features)", "output_shape_desc": "(..., out_features)"},
    {"name": "LMHead", "display_name": "LM Head", "description": "Language model head (projection to vocabulary)", "category": "other", "params_schema": {"type": "object", "properties": {"hidden_size": {"type": "integer", "default": 4096}, "vocab_size": {"type": "integer", "default": 32000}}, "required": ["hidden_size", "vocab_size"]}, "input_shape_desc": "(batch_size, seq_len, hidden_size)", "output_shape_desc": "(batch_size, seq_len, vocab_size)"},
    # Activation
    {"name": "SiLU", "display_name": "SiLU", "description": "Sigmoid Linear Unit activation", "category": "activation", "params_schema": {"type": "object", "properties": {}}, "input_shape_desc": "(...) in_features", "output_shape_desc": "(...) in_features"},
]


PRESET_CATEGORIES = [
    {"name": "embedding", "display_name": "Embedding", "description": "Token embedding layers", "sort_order": 1},
    {"name": "normalization", "display_name": "Normalization", "description": "Layer normalization", "sort_order": 2},
    {"name": "attention", "display_name": "Attention", "description": "Attention mechanisms", "sort_order": 3},
    {"name": "mlp", "display_name": "MLP", "description": "Multi-Layer Perceptron", "sort_order": 4},
    {"name": "activation", "display_name": "Activation", "description": "Activation functions", "sort_order": 5},
    {"name": "positional", "display_name": "Positional Encoding", "description": "Positional embeddings", "sort_order": 6},
    {"name": "pooling", "display_name": "Pooling", "description": "Pooling layers", "sort_order": 7},
    {"name": "other", "display_name": "Other", "description": "Other layers", "sort_order": 99},
]

PRESET_MODEL_CATEGORIES = [
    {"name": "dense", "display_name": "Dense", "description": "Dense Transformer (e.g. LLaMA, Qwen, Mistral)"},
    {"name": "moe", "display_name": "MoE", "description": "Mixture of Experts (e.g. DeepSeek V2/V3, Mixtral)"},
    {"name": "hybrid", "display_name": "Hybrid", "description": "Hybrid dense + MoE (e.g. DeepSeek V4, Qwen3 MoE)"},
    {"name": "state_space", "display_name": "State Space", "description": "State space models (e.g. Mamba)"},
    {"name": "other", "display_name": "Other", "description": "Other architectures"},
]


def init_preset_operators(db: Session) -> None:
    """初始化预置算子和分类（仅首次运行时插入）"""
    now = _utcnow()

    # 初始化算子分类
    existing_cats = db.query(OperatorCategory).count()
    if existing_cats == 0:
        for cat_data in PRESET_CATEGORIES:
            cat = OperatorCategory(
                name=cat_data["name"],
                display_name=cat_data["display_name"],
                description=cat_data.get("description", ""),
                sort_order=cat_data.get("sort_order", 0),
                created_at=now,
                updated_at=now,
            )
            db.add(cat)
        db.commit()
        logger.info(f"Initialized {len(PRESET_CATEGORIES)} operator categories")

    # 初始化预置算子
    existing = db.query(Operator).count()
    if existing > 0:
        return
    for op_data in PRESET_OPERATORS:
        op = Operator(
            name=op_data["name"],
            display_name=op_data["display_name"],
            description=op_data.get("description", ""),
            category=op_data.get("category", "other"),
            params_schema=json.dumps(op_data.get("params_schema", {}), ensure_ascii=False),
            input_shape_desc=op_data.get("input_shape_desc", ""),
            output_shape_desc=op_data.get("output_shape_desc", ""),
            tags=json.dumps([], ensure_ascii=False),
            created_at=now,
            updated_at=now,
        )
        db.add(op)
    db.commit()
    logger.info(f"Initialized {len(PRESET_OPERATORS)} preset operators")


# ===== 算子分类 CRUD =====


@router.get("/operators/categories")
async def list_categories(db: Session = Depends(get_db)):
    """获取算子分类列表"""
    cats = db.query(OperatorCategory).order_by(OperatorCategory.sort_order).all()
    return {"categories": [cat.to_dict() for cat in cats]}


@router.post("/operators/categories", status_code=201)
async def create_category(req: "CategoryCreate", db: Session = Depends(get_db)):
    """创建算子分类"""
    # 检查 name 是否已存在
    existing = db.query(OperatorCategory).filter(OperatorCategory.name == req.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"分类标识「{req.name}」已存在")

    now = _utcnow()
    cat = OperatorCategory(
        name=req.name,
        display_name=req.display_name,
        description=req.description,
        sort_order=req.sort_order,
        created_at=now,
        updated_at=now,
    )
    db.add(cat)
    try:
        db.commit()
        db.refresh(cat)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"分类标识「{req.name}」已存在")
    return cat.to_dict()


@router.put("/operators/categories/{category_id}")
async def update_category(category_id: int, req: "CategoryUpdate", db: Session = Depends(get_db)):
    """更新算子分类"""
    cat = db.query(OperatorCategory).filter(OperatorCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    if req.name is not None:
        cat.name = req.name
    if req.display_name is not None:
        cat.display_name = req.display_name
    if req.description is not None:
        cat.description = req.description
    if req.sort_order is not None:
        cat.sort_order = req.sort_order
    cat.updated_at = _utcnow()
    db.commit()
    return cat.to_dict()


@router.delete("/operators/categories/{category_id}")
async def delete_category(category_id: int, db: Session = Depends(get_db)):
    """删除算子分类"""
    cat = db.query(OperatorCategory).filter(OperatorCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(cat)
    db.commit()
    return {"deleted": True, "id": category_id}


# ===== 算子 CRUD =====


@router.get("/operators")
async def list_operators(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """列出算子"""
    query = db.query(Operator)
    if category:
        query = query.filter(Operator.category == category)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            Operator.name.like(pattern) |
            Operator.display_name.like(pattern) |
            Operator.description.like(pattern)
        )
    operators = query.order_by(Operator.category, Operator.name).all()
    return {"operators": [op.to_dict() for op in operators]}


@router.post("/operators", status_code=201)
async def create_operator(req: OperatorCreate, db: Session = Depends(get_db)):
    """创建新算子"""
    now = _utcnow()
    op = Operator(
        name=req.name,
        display_name=req.display_name,
        description=req.description,
        category=req.category,
        params_schema=json.dumps(req.params_schema, ensure_ascii=False),
        input_shape_desc=req.input_shape_desc,
        output_shape_desc=req.output_shape_desc,
        vllm_code_refs=json.dumps(req.vllm_code_refs, ensure_ascii=False),
        tags=json.dumps(req.tags, ensure_ascii=False),
        user_id=req.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return op.to_dict()


@router.get("/operators/{operator_id}")
async def get_operator(operator_id: int, db: Session = Depends(get_db)):
    """获取算子详情"""
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")
    return op.to_dict()


@router.put("/operators/{operator_id}")
async def update_operator(operator_id: int, req: OperatorUpdate, db: Session = Depends(get_db)):
    """更新算子"""
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")

    if req.name is not None:
        op.name = req.name
    if req.display_name is not None:
        op.display_name = req.display_name
    if req.description is not None:
        op.description = req.description
    if req.category is not None:
        op.category = req.category
    if req.params_schema is not None:
        op.params_schema = json.dumps(req.params_schema, ensure_ascii=False)
    if req.input_shape_desc is not None:
        op.input_shape_desc = req.input_shape_desc
    if req.output_shape_desc is not None:
        op.output_shape_desc = req.output_shape_desc
    if req.vllm_code_refs is not None:
        op.vllm_code_refs = json.dumps(req.vllm_code_refs, ensure_ascii=False)
    if req.tags is not None:
        op.tags = json.dumps(req.tags, ensure_ascii=False)
    if req.user_id is not None:
        op.user_id = req.user_id

    op.updated_at = _utcnow()
    db.commit()
    return op.to_dict()


@router.delete("/operators/{operator_id}")
async def delete_operator(operator_id: int, db: Session = Depends(get_db)):
    """删除算子"""
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator not found")
    db.delete(op)
    db.commit()
    return {"deleted": True, "id": operator_id}


# ===== 模型 CRUD =====


@router.get("/models")
async def list_models(
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """列出模型"""
    query = db.query(ModelAnatomy)
    if category:
        query = query.filter(ModelAnatomy.category == category)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            ModelAnatomy.name.like(pattern) |
            ModelAnatomy.display_name.like(pattern)
        )
    models = query.order_by(ModelAnatomy.updated_at.desc()).all()
    return {"models": [m.to_dict() for m in models]}


@router.get("/models/categories")
async def list_model_categories(db: Session = Depends(get_db)):
    """获取模型分类列表"""
    from sqlalchemy import func
    rows = db.query(ModelAnatomy.category, func.count(ModelAnatomy.id)).group_by(ModelAnatomy.category).all()
    return {"categories": [{"name": row[0], "count": row[1]} for row in rows]}


@router.post("/models", status_code=201)
async def create_model(req: ModelAnatomyCreate, db: Session = Depends(get_db)):
    """创建新模型"""
    now = _utcnow()

    # 统计使用的算子种类数
    used_ids = set()
    def _collect_op_ids(stages):
        for stage in stages:
            if stage.get("type") == "operator":
                oid = stage.get("operator_id")
                if oid:
                    used_ids.add(oid)
            elif stage.get("type") == "repeat_block":
                for contents in stage.get("contents", []):
                    _collect_op_ids(contents)

    _collect_op_ids(req.architecture)

    model = ModelAnatomy(
        name=req.name,
        display_name=req.display_name,
        description=req.description,
        category=req.category,
        architecture=json.dumps(req.architecture, ensure_ascii=False),
        params_summary=json.dumps(req.params_summary, ensure_ascii=False),
        operators_count=len(used_ids),
        tags=json.dumps(req.tags, ensure_ascii=False),
        user_id=req.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    return model.to_dict()


@router.get("/models/{model_id}")
async def get_model(model_id: int, db: Session = Depends(get_db)):
    """获取模型详情"""
    model = db.query(ModelAnatomy).filter(ModelAnatomy.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model.to_dict()


@router.put("/models/{model_id}")
async def update_model(model_id: int, req: ModelAnatomyUpdate, db: Session = Depends(get_db)):
    """更新模型"""
    model = db.query(ModelAnatomy).filter(ModelAnatomy.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    if req.name is not None:
        model.name = req.name
    if req.display_name is not None:
        model.display_name = req.display_name
    if req.description is not None:
        model.description = req.description
    if req.architecture is not None:
        model.architecture = json.dumps(req.architecture, ensure_ascii=False)
        # 重新统计算子种类数
        used_ids = set()
        def _collect(stages):
            for stage in stages:
                if stage.get("type") == "operator":
                    oid = stage.get("operator_id")
                    if oid:
                        used_ids.add(oid)
                elif stage.get("type") == "repeat_block":
                    for contents in stage.get("contents", []):
                        _collect(contents)
        _collect(req.architecture)
        model.operators_count = len(used_ids)
    if req.params_summary is not None:
        model.params_summary = json.dumps(req.params_summary, ensure_ascii=False)
    if req.tags is not None:
        model.tags = json.dumps(req.tags, ensure_ascii=False)
    if req.user_id is not None:
        model.user_id = req.user_id

    model.updated_at = _utcnow()
    db.commit()
    return model.to_dict()


@router.delete("/models/{model_id}")
async def delete_model(model_id: int, db: Session = Depends(get_db)):
    """删除模型"""
    model = db.query(ModelAnatomy).filter(ModelAnatomy.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    db.delete(model)
    db.commit()
    return {"deleted": True, "id": model_id}