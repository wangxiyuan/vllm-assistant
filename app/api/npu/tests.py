"""测试用例 API：用例 CRUD、运行、运行历史"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NpuTestCase, NpuTestRun
from app.services.npu import tests as test_service

logger = logging.getLogger(__name__)
router = APIRouter()


class TestCaseSaveRequest(BaseModel):
    name: str
    description: str = ""
    kind: str = "openai_chat"  # container_cmd / openai_chat
    payload: dict = {}
    target: str = "service"  # machine / service
    timeout_seconds: int = 600
    enabled: bool = True

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v):
        if v not in ("container_cmd", "openai_chat"):
            raise ValueError("kind must be container_cmd/openai_chat")
        return v

    @field_validator("target")
    @classmethod
    def _validate_target(cls, v):
        if v not in ("machine", "service"):
            raise ValueError("target must be machine/service")
        return v


class TestCaseRunRequest(BaseModel):
    machine_id: Optional[int] = None
    service_id: Optional[int] = None


@router.get("")
def list_cases(db: Session = Depends(get_db)):
    rows = db.query(NpuTestCase).order_by(NpuTestCase.id).all()
    return [c.to_dict() for c in rows]


@router.post("")
def create_case(req: TestCaseSaveRequest, db: Session = Depends(get_db)):
    if db.query(NpuTestCase).filter(NpuTestCase.name == req.name).first():
        raise HTTPException(status_code=400, detail=f"用例名已存在: {req.name}")
    row = NpuTestCase(
        name=req.name,
        description=req.description or None,
        kind=req.kind,
        payload=json.dumps(req.payload, ensure_ascii=False) if req.payload else None,
        target=req.target,
        timeout_seconds=req.timeout_seconds,
        enabled=req.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.put("/{case_id}")
def update_case(case_id: int, req: TestCaseSaveRequest, db: Session = Depends(get_db)):
    row = db.query(NpuTestCase).filter(NpuTestCase.id == case_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    dup = db.query(NpuTestCase).filter(
        NpuTestCase.name == req.name, NpuTestCase.id != case_id).first()
    if dup:
        raise HTTPException(status_code=400, detail=f"用例名已存在: {req.name}")
    row.name = req.name
    row.description = req.description or None
    row.kind = req.kind
    row.payload = json.dumps(req.payload, ensure_ascii=False) if req.payload else None
    row.target = req.target
    row.timeout_seconds = req.timeout_seconds
    row.enabled = req.enabled
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.delete("/{case_id}")
def delete_case(case_id: int, db: Session = Depends(get_db)):
    row = db.query(NpuTestCase).filter(NpuTestCase.id == case_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{case_id}/run")
def run_case(case_id: int, req: TestCaseRunRequest, db: Session = Depends(get_db)):
    try:
        return test_service.run_test(case_id, machine_id=req.machine_id,
                                     service_id=req.service_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/runs")
def list_runs(case_id: Optional[int] = None, limit: int = 100,
              db: Session = Depends(get_db)):
    q = db.query(NpuTestRun)
    if case_id is not None:
        q = q.filter(NpuTestRun.case_id == case_id)
    rows = q.order_by(NpuTestRun.id.desc()).limit(min(limit, 500)).all()
    return [r.to_dict() for r in rows]
