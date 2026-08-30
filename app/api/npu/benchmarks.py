"""benchmark 压测 API：发起、列表、详情、删除"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NpuBenchmarkRun, NpuMachine, NpuServiceInstance
from app.services.npu import benchmark as bench_service

logger = logging.getLogger(__name__)
router = APIRouter()


class BenchmarkStartRequest(BaseModel):
    machine_id: Optional[int] = None  # 缺省取服务所在机器
    service_id: int
    endpoint: str = "/v1/completions"
    dataset_name: str = "random"  # random / sharegpt
    dataset_path: str = ""  # sharegpt 必填，机器上数据集文件路径
    num_prompts: int = 10
    request_rate: Optional[float] = None
    max_concurrency: Optional[int] = None
    timeout: Optional[int] = None


@router.post("")
def start_benchmark(req: BenchmarkStartRequest, db: Session = Depends(get_db)):
    service = db.query(NpuServiceInstance).filter(
        NpuServiceInstance.id == req.service_id).first()
    if service is None:
        raise HTTPException(status_code=404, detail="服务实例不存在")
    machine_id = req.machine_id or service.machine_id
    machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机器不存在")
    try:
        return bench_service.start_benchmark(machine, service, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
def list_benchmarks(service_id: Optional[int] = None, limit: int = 50,
                    db: Session = Depends(get_db)):
    q = db.query(NpuBenchmarkRun)
    if service_id is not None:
        q = q.filter(NpuBenchmarkRun.service_id == service_id)
    rows = q.order_by(NpuBenchmarkRun.id.desc()).limit(min(limit, 200)).all()
    return [r.to_dict() for r in rows]


@router.get("/{run_id}")
def get_benchmark(run_id: int, db: Session = Depends(get_db)):
    row = db.query(NpuBenchmarkRun).filter(NpuBenchmarkRun.id == run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="压测记录不存在")
    return row.to_dict()


@router.delete("/{run_id}")
def delete_benchmark(run_id: int, db: Session = Depends(get_db)):
    row = db.query(NpuBenchmarkRun).filter(NpuBenchmarkRun.id == run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="压测记录不存在")
    if row.status == "running":
        raise HTTPException(status_code=400, detail="压测进行中，不能删除")
    db.delete(row)
    db.commit()
    return {"ok": True}
