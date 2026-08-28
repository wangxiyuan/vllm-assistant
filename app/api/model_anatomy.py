"""
模型拆解 API —— 积木式（building_block / model_assembly），YAML 为唯一数据源。

端点：
  - GET/POST    /blocks                   积木列表 / 创建
  - GET/PUT/DELETE /blocks/{id}           积木详情 / 更新 / 删除
  - GET/POST/PUT/DELETE /assemblies        模型组装 CRUD
  - GET  /assemblies/{id}
  - POST /import                          导入一份 YAML（多文档/单列表均可）
  - GET  /export                           导出全部积木+组装为 YAML
  - GET  /validate                         对已存积木/组装重跑校验
所有端点受 AuthMiddleware 保护（全局配置）。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.anatomy import (
    AnatomyValidator,
    AnatomyYAMLError,
    ValidationReport,
    assembly_from_dict,
    block_from_dict,
    build_validation_context,
    checksum_of,
    parse_yaml,
    validate_duplicates,
)
from app.database import get_db
from app.models import BuildingBlock, ModelAssembly
from app.schemas import (
    AnatomyImportResult,
    BuildingBlockCreate,
    BuildingBlockUpdate,
    ModelAssemblyCreate,
    ModelAssemblyUpdate,
    ValidationIssue,
    YAMLImportRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_FLAT_KEYS = (
    "file", "weights", "ops",
    "edges", "segments",
    "forward_note", "weight_prefix_note", "note",
)


def _flat_impl(req) -> dict:
    """把请求中平铺的实现字段收集为 vllm 列存储的 extra dict。"""
    extra = {}
    for k in _FLAT_KEYS:
        v = getattr(req, k, None)
        if v:
            extra[k] = v
    return extra


def _flat_impl_updated(req) -> bool:
    """请求中是否有任一平铺实现字段被显式提交（需重建 extra）。"""
    return any(getattr(req, k, None) is not None for k in _FLAT_KEYS)


def _config_for_ctx() -> Optional[dict]:
    """从内置示例 config 构造校验上下文（可在无真实 config 时给出宽松符号）。"""
    return None


def _validate_reports(report: ValidationReport) -> AnatomyImportResult:
    errors = [ValidationIssue(**e) for e in report.errors]
    warnings = [ValidationIssue(**e) for e in report.warnings]
    return errors, warnings


# ===== 积木 CRUD =====


@router.get("/blocks")
async def list_blocks(
    kind: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """列出积木。可按 kind / category / search 过滤。"""
    query = db.query(BuildingBlock)
    if kind:
        query = query.filter(BuildingBlock.kind == kind)
    if category:
        query = query.filter(BuildingBlock.category == category)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            BuildingBlock.name.like(pattern)
            | BuildingBlock.description.like(pattern)
        )
    blocks = query.order_by(BuildingBlock.kind, BuildingBlock.category, BuildingBlock.name).all()
    return {"blocks": [b.to_dict() for b in blocks]}


@router.get("/blocks/categories")
async def block_categories(db: Session = Depends(get_db)):
    """积木分类聚合（供前端筛选）。"""
    from sqlalchemy import func
    rows = db.query(BuildingBlock.category, func.count(BuildingBlock.id)).group_by(
        BuildingBlock.category).all()
    return {"categories": [{"name": r, "count": c} for r, c in rows]}


@router.post("/blocks", status_code=201)
async def create_block(req: BuildingBlockCreate, db: Session = Depends(get_db)):
    """创建积木。"""
    if req.kind not in ("atomic", "composite"):
        raise HTTPException(status_code=400, detail="kind 必须是 atomic 或 composite")
    now = _utcnow()
    extra = _flat_impl(req)
    block = BuildingBlock(
        name=req.name,
        kind=req.kind,
        category=req.category,
        description=req.description,
        formula=json.dumps(req.formula, ensure_ascii=False),
        params_schema=json.dumps(req.params_schema, ensure_ascii=False),
        ports=json.dumps(req.ports, ensure_ascii=False),
        children=json.dumps(req.children, ensure_ascii=False),
        vllm=json.dumps(extra, ensure_ascii=False),
        state=json.dumps(req.state, ensure_ascii=False),
        yaml=req.yaml or "",
        checksum=req.checksum or (checksum_of(req.yaml) if req.yaml else ""),
        tags=json.dumps(req.tags, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block.to_dict()


@router.get("/blocks/{block_id}")
async def get_block(block_id: int, db: Session = Depends(get_db)):
    block = db.query(BuildingBlock).filter(BuildingBlock.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    return block.to_dict()


@router.put("/blocks/{block_id}")
async def update_block(block_id: int, req: BuildingBlockUpdate, db: Session = Depends(get_db)):
    block = db.query(BuildingBlock).filter(BuildingBlock.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    if req.name is not None:
        block.name = req.name
    if req.kind is not None:
        block.kind = req.kind
    if req.category is not None:
        block.category = req.category
    if req.description is not None:
        block.description = req.description
    if req.formula is not None:
        block.formula = json.dumps(req.formula, ensure_ascii=False)
    if req.params_schema is not None:
        block.params_schema = json.dumps(req.params_schema, ensure_ascii=False)
    if req.ports is not None:
        block.ports = json.dumps(req.ports, ensure_ascii=False)
    if req.config is not None:
        block.config = json.dumps(req.config, ensure_ascii=False)
    if req.children is not None:
        block.children = json.dumps(req.children, ensure_ascii=False)
    if _flat_impl_updated(req):
        # 任一平铺字段被显式更新：整体重建 extra 字典
        block.vllm = json.dumps(_flat_impl(req), ensure_ascii=False)
    if req.state is not None:
        block.state = json.dumps(req.state, ensure_ascii=False)
    if req.yaml is not None:
        block.yaml = req.yaml
        block.checksum = checksum_of(req.yaml) if req.yaml else ""
    if req.checksum is not None:
        block.checksum = req.checksum
    if req.tags is not None:
        block.tags = json.dumps(req.tags, ensure_ascii=False)
    block.updated_at = _utcnow()
    db.commit()
    db.refresh(block)
    return block.to_dict()


@router.delete("/blocks/{block_id}")
async def delete_block(block_id: int, db: Session = Depends(get_db)):
    block = db.query(BuildingBlock).filter(BuildingBlock.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    db.delete(block)
    db.commit()
    return {"deleted": True, "id": block_id}


# ===== 模型组装 CRUD =====


@router.get("/assemblies")
async def list_assemblies(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(ModelAssembly)
    if category:
        query = query.filter(ModelAssembly.category == category)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            ModelAssembly.name.like(pattern)
            | ModelAssembly.description.like(pattern)
        )
    items = query.order_by(ModelAssembly.updated_at.desc()).all()
    return {"assemblies": [a.to_dict() for a in items]}


@router.get("/assemblies/{assembly_id}")
async def get_assembly(assembly_id: int, db: Session = Depends(get_db)):
    item = db.query(ModelAssembly).filter(ModelAssembly.id == assembly_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assembly not found")
    return item.to_dict()


@router.post("/assemblies", status_code=201)
async def create_assembly(req: ModelAssemblyCreate, db: Session = Depends(get_db)):
    now = _utcnow()
    item = ModelAssembly(
        name=req.name,
        category=req.category,
        description=req.description,
        definition=json.dumps(req.definition, ensure_ascii=False),
        checksum=req.checksum or "",
        tags=json.dumps(req.tags, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Assembly already exists")
    return item.to_dict()


@router.put("/assemblies/{assembly_id}")
async def update_assembly(assembly_id: int, req: ModelAssemblyUpdate, db: Session = Depends(get_db)):
    item = db.query(ModelAssembly).filter(ModelAssembly.id == assembly_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assembly not found")
    if req.name is not None:
        item.name = req.name
    if req.category is not None:
        item.category = req.category
    if req.description is not None:
        item.description = req.description
    if req.definition is not None:
        item.definition = json.dumps(req.definition, ensure_ascii=False)
    if req.config is not None:
        item.config = json.dumps(req.config, ensure_ascii=False)
    if req.checksum is not None:
        item.checksum = req.checksum
    if req.tags is not None:
        item.tags = json.dumps(req.tags, ensure_ascii=False)
    item.updated_at = _utcnow()
    db.commit()
    db.refresh(item)
    return item.to_dict()


@router.delete("/assemblies/{assembly_id}")
async def delete_assembly(assembly_id: int, db: Session = Depends(get_db)):
    item = db.query(ModelAssembly).filter(ModelAssembly.id == assembly_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assembly not found")
    db.delete(item)
    db.commit()
    return {"deleted": True, "id": assembly_id}


# ===== YAML 导入（核心：YAML 为唯一数据源）=====


@router.post("/import", response_model=AnatomyImportResult)
async def import_yaml(req: YAMLImportRequest, db: Session = Depends(get_db)):
    """导入一份 YAML（单列表或多文档）。

    对每个 atomic/composite 写入 building_block；assembly 写入 model_assembly。
    导入前做引用完整性校验，不合法则跳过该对象（保留错误信息）。
    """
    try:
        docs = parse_yaml(req.yaml)
    except AnatomyYAMLError as e:
        return AnatomyImportResult(errors=[ValidationIssue(message=str(e))])

    dup = validate_duplicates(docs)
    if dup:
        return AnatomyImportResult(
            errors=[ValidationIssue(message=f"YAML 内存在重复 name: {', '.join(dup)}")]
        )

    # 先建索引：确认所有被引用积木要么在本文档内，要么已存在于 DB
    doc_names = {d["name"] for d in docs}
    existing_names = set(n for (n,) in db.query(BuildingBlock.name).all())
    referenceable = doc_names | existing_names

    result = AnatomyImportResult()
    ctx = build_validation_context(config={})

    # 分两趟：先落库所有积木，再校验+落 assembly（以便 assembly 能引用本文档积木）
    # 第一趟：积木
    for doc in docs:
        kind = doc.get("kind")
        if kind == "assembly":
            continue
        if db.query(BuildingBlock).filter(BuildingBlock.name == doc["name"]).first():
            result.skipped += 1
            result.warnings.append(ValidationIssue(
                path=doc["name"], message="积木已存在，跳过（如需覆盖请先删除）"
            ))
            continue
        fields = block_from_dict(doc)
        block = BuildingBlock(
            name=fields["name"], kind=fields["kind"], category=fields["category"],
            description=fields["description"],
            formula=json.dumps(fields.get("formula", []), ensure_ascii=False),
            params_schema=json.dumps(fields["params_schema"], ensure_ascii=False),
            ports=json.dumps(fields["ports"], ensure_ascii=False),
            config=json.dumps(fields["config"], ensure_ascii=False),
            children=json.dumps(fields["children"], ensure_ascii=False),
            vllm=json.dumps(fields["vllm"], ensure_ascii=False),
            state=json.dumps(fields["state"], ensure_ascii=False),
            tags=json.dumps(fields["tags"], ensure_ascii=False),
            created_at=_utcnow(), updated_at=_utcnow(),
        )
        db.add(block)
        result.imported_blocks += 1
    db.flush()

    # 重新查询积木（含刚插入的）用于 assembly 校验；并把本文档的 assembly 也加入
    # 引用空间（好让 Glm5NextForCausalLM 能引用同文档的 Glm5NextModel）。
    all_blocks = [b.to_dict() for b in db.query(BuildingBlock).all()]
    assembly_docs = [assembly_from_dict(d) for d in docs if d.get("kind") == "assembly"
                     and d.get("name")]
    assembly_objs = [{**ad, "kind": "assembly", "name": ad["name"],
                      "definition": ad["definition"]} for ad in assembly_docs]
    validator = AnatomyValidator(all_blocks, assembly_objs)

    # 第二趟：assembly
    for doc in docs:
        if doc.get("kind") != "assembly":
            continue
        fields = assembly_from_dict(doc)
        report = ValidationReport()
        validator.validate_assembly(fields["definition"], report, ctx, name=fields["name"])
        errs, warns = _validate_reports(report)
        result.errors.extend(errs)
        result.warnings.extend(warns)
        if not report.ok:
            result.skipped += 1
            continue
        if db.query(ModelAssembly).filter(ModelAssembly.name == fields["name"]).first():
            result.skipped += 1
            continue
        item = ModelAssembly(
            name=fields["name"], category=fields["category"],
            description=fields["description"],
            definition=json.dumps(fields["definition"], ensure_ascii=False),
            config=json.dumps(fields.get("config", {}), ensure_ascii=False),
            tags=json.dumps(fields["tags"], ensure_ascii=False),
            created_at=_utcnow(), updated_at=_utcnow(),
        )
        db.add(item)
        result.imported_assemblies += 1

    db.commit()
    return result


# ===== 单块 YAML 视图（供前端编辑）=====


def _block_to_yaml_doc(b: BuildingBlock) -> dict:
    """把单个 building_block 渲染为 YAML doc dict（与 export 一致）。"""
    d = {
        "kind": b.kind,
        "name": b.name,
        "category": b.category,
    }
    if b.description:
        d["description"] = b.description
    if b.formula:
        d["formula"] = json.loads(b.formula)
    if b.params_schema:
        d["params_schema"] = json.loads(b.params_schema)
    if b.ports:
        d["ports"] = json.loads(b.ports)
    if b.config:
        d["config"] = json.loads(b.config)
    if b.kind == "composite" and b.children:
        d["children"] = json.loads(b.children)
    if b.vllm:
        extra = json.loads(b.vllm)
        for k in _FLAT_KEYS:
            if k in extra:
                d[k] = extra[k]
    if b.state:
        d["state"] = json.loads(b.state)
    return d


def _assembly_to_yaml_doc(a: ModelAssembly) -> dict:
    d = {"kind": "assembly", "name": a.name, "category": a.category}
    if a.description:
        d["description"] = a.description
    if a.config:
        d["config"] = json.loads(a.config)
    d.update(json.loads(a.definition))
    return d


@router.get("/blocks/{block_id}/yaml")
async def get_block_yaml(block_id: int, db: Session = Depends(get_db)):
    """返回单个积木的 YAML 片段（供编辑）。"""
    import yaml
    block = db.query(BuildingBlock).filter(BuildingBlock.id == block_id).first()
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    doc = _block_to_yaml_doc(block)
    text = yaml.dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return {"yaml": text}


@router.get("/assemblies/{assembly_id}/yaml")
async def get_assembly_yaml(assembly_id: int, db: Session = Depends(get_db)):
    """返回单个模型的 YAML 片段（供编辑）。"""
    import yaml
    item = db.query(ModelAssembly).filter(ModelAssembly.id == assembly_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Assembly not found")
    doc = _assembly_to_yaml_doc(item)
    text = yaml.dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return {"yaml": text}


@router.get("/yaml/template")
async def yaml_template(kind: str = "atomic", db: Session = Depends(get_db)):
    """返回指定 kind 的空白 YAML 模板（新建用）。"""
    import yaml
    if kind == "assembly":
        doc = {"kind": "assembly", "name": "", "category": "other",
               "description": "", "config": {},
               "steps": [], "edges": [], "ports": {"inputs": [], "outputs": []}}
    elif kind == "composite":
        doc = {"kind": "composite", "name": "", "category": "other", "description": "",
               "params_schema": {"type": "object", "properties": {}},
               "ports": {"inputs": [], "outputs": []},
               "children": [], "edges": [], "file": ""}
    else:
        doc = {"kind": "atomic", "name": "", "category": "other", "description": "",
               "params_schema": {"type": "object", "properties": {}},
               "ports": {"inputs": [], "outputs": []}, "file": ""}
    text = yaml.dump(doc, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return {"yaml": text}


# ===== 导出（YAML 圆整回写）=====


@router.get("/export")
async def export_yaml(db: Session = Depends(get_db)):
    """导出全部积木 + 组装为一份 YAML 文本。"""
    import yaml

    blocks = db.query(BuildingBlock).order_by(BuildingBlock.kind).all()
    assemblies = db.query(ModelAssembly).order_by(ModelAssembly.name).all()
    docs = []
    for b in blocks:
        d = {}
        d["kind"] = b.kind
        d["name"] = b.name
        d["category"] = b.category
        if b.description:
            d["description"] = b.description
        if b.formula:
            d["formula"] = json.loads(b.formula)
        if b.params_schema:
            d["params_schema"] = json.loads(b.params_schema)
        if b.ports:
            d["ports"] = json.loads(b.ports)
        if b.config:
            d["config"] = json.loads(b.config)
        if b.kind == "composite" and b.children:
            d["children"] = json.loads(b.children)
        if b.vllm:
            extra = json.loads(b.vllm)
            for k in _FLAT_KEYS:
                if k in extra:
                    d[k] = extra[k]
        if b.state:
            d["state"] = json.loads(b.state)
        docs.append(d)
    for a in assemblies:
        d = {}
        d["kind"] = "assembly"
        d["name"] = a.name
        d["category"] = a.category
        if a.description:
            d["description"] = a.description
        if a.config:
            d["config"] = json.loads(a.config)
        d.update(json.loads(a.definition))
        docs.append(d)
    text = yaml.dump(docs, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return {"yaml": text}


# ===== 单块 YAML 保存（编辑后写回）=====


@router.post("/apply-yaml")
async def apply_yaml(req: YAMLImportRequest, db: Session = Depends(get_db)):
    """用一份 YAML（单块）覆盖/sub 保存对应积木或模型。

    请求体 {yaml: <单块 YAML>}。按 name 存在则覆盖，否则新建。
    """
    try:
        docs = parse_yaml(req.yaml)
    except AnatomyYAMLError as e:
        return AnatomyImportResult(errors=[ValidationIssue(message=str(e))])
    if len(docs) != 1:
        return AnatomyImportResult(errors=[ValidationIssue(message="请提交恰好一个积木/模型")])
    doc = docs[0]
    kind = doc.get("kind")
    if kind == "assembly":
        fields = assembly_from_dict(doc)
        existing = db.query(ModelAssembly).filter(ModelAssembly.name == fields["name"]).first()
        now = _utcnow()
        if existing:
            existing.category = fields["category"]
            existing.description = fields["description"]
            existing.definition = json.dumps(fields["definition"], ensure_ascii=False)
            existing.config = json.dumps(fields["config"], ensure_ascii=False)
            existing.tags = json.dumps(fields["tags"], ensure_ascii=False)
            existing.updated_at = now
            item = existing
        else:
            item = ModelAssembly(
                name=fields["name"], category=fields["category"],
                description=fields["description"],
                definition=json.dumps(fields["definition"], ensure_ascii=False),
                config=json.dumps(fields["config"], ensure_ascii=False),
                tags=json.dumps(fields["tags"], ensure_ascii=False),
                created_at=now, updated_at=now,
            )
            db.add(item)
        db.commit()
        db.refresh(item)
        return {"ok": True, "entity": item.to_dict()}
    else:
        fields = block_from_dict(doc)
        existing = db.query(BuildingBlock).filter(BuildingBlock.name == fields["name"]).first()
        now = _utcnow()
        if existing:
            existing.kind = fields["kind"]
            existing.category = fields["category"]
            existing.description = fields["description"]
            existing.formula = json.dumps(fields["formula"], ensure_ascii=False)
            existing.params_schema = json.dumps(fields["params_schema"], ensure_ascii=False)
            existing.ports = json.dumps(fields["ports"], ensure_ascii=False)
            existing.config = json.dumps(fields["config"], ensure_ascii=False)
            existing.children = json.dumps(fields["children"], ensure_ascii=False)
            existing.vllm = json.dumps(fields["vllm"], ensure_ascii=False)
            existing.state = json.dumps(fields["state"], ensure_ascii=False)
            existing.tags = json.dumps(fields["tags"], ensure_ascii=False)
            existing.updated_at = now
            block = existing
        else:
            block = BuildingBlock(
                name=fields["name"], kind=fields["kind"], category=fields["category"],
                description=fields["description"],
                formula=json.dumps(fields["formula"], ensure_ascii=False),
                params_schema=json.dumps(fields["params_schema"], ensure_ascii=False),
                ports=json.dumps(fields["ports"], ensure_ascii=False),
                config=json.dumps(fields["config"], ensure_ascii=False),
                children=json.dumps(fields["children"], ensure_ascii=False),
                vllm=json.dumps(fields["vllm"], ensure_ascii=False),
                state=json.dumps(fields["state"], ensure_ascii=False),
                tags=json.dumps(fields["tags"], ensure_ascii=False),
                created_at=now, updated_at=now,
            )
            db.add(block)
        db.commit()
        db.refresh(block)
        return {"ok": True, "entity": block.to_dict()}


# ===== 校验已存数据 =====


@router.get("/validate")
async def validate_all(db: Session = Depends(get_db)):
    """对已存积木 + 组装重跑校验，返回结构化 errors/warnings。"""
    blocks = [b.to_dict() for b in db.query(BuildingBlock).all()]
    assembly_rows = db.query(ModelAssembly).all()
    assemblies = [a.to_dict() for a in assembly_rows]
    validator = AnatomyValidator(blocks, assemblies)
    ctx = build_validation_context(config={})
    report = ValidationReport()
    for b in blocks:
        validator.validate_block(b, report, ctx)
    for a in assemblies:
        validator.validate_assembly(a.get("definition") or {}, report, ctx,
                                    name=a.get("name") or "")
    errs, warns = _validate_reports(report)
    return {"ok": report.ok, "errors": errs, "warnings": warns}