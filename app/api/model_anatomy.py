"""
模型拆解 API（docs/model_anatomy.md）

算子管理 + 模型搭建 CRUD。
所有端点受 AuthMiddleware 保护（全局配置）。

预置数据请通过 scripts/init_db.py 手动初始化。
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