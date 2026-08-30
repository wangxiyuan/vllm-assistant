"""NPU 任务中心 API

容器任务提交（自定义命令为主，预设快捷填充）、命令预览、任务列表/详情、
增量日志、停止，以及容器任务模板 CRUD。
"""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NpuJob, NpuMachine, NpuContainerTemplate
from app.services.npu import jobs as job_service
from app.services.npu.profiles import build_docker_run, default_image

logger = logging.getLogger(__name__)
router = APIRouter()


class JobCreateRequest(BaseModel):
    machine_id: int
    mode: str = "oneshot"  # persistent / oneshot
    type: str = "container"
    name: str = ""
    image: str = ""  # 空 = 机型默认镜像
    device_ids: Optional[List[int]] = None  # None = 全部卡
    mounts: List[str] = []  # "host:container"（container 省略 = 同路径）
    env: Dict[str, str] = {}
    network: str = "host"  # host / bridge
    ports: List[str] = []  # "host:container"
    command: str = ""  # 容器内执行命令
    shm_size: str = ""  # 空 = 机型默认
    extra_devices: List[str] = []
    timeout: Optional[int] = None

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, v):
        if v not in ("oneshot", "persistent"):
            raise ValueError("mode must be oneshot/persistent")
        return v


class TemplateSaveRequest(BaseModel):
    name: str
    mode: str = "oneshot"
    machine_type: str = ""
    image: str = ""
    device_ids: Optional[List[int]] = None
    mounts: List[str] = []
    env: Dict[str, str] = {}
    network: str = "host"
    ports: List[str] = []
    command: str = ""
    shm_size: str = ""
    notes: str = ""


def _get_machine_or_404(db: Session, machine_id: int) -> NpuMachine:
    machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机器不存在")
    return machine


def _spec_from_req(req: JobCreateRequest, machine: NpuMachine) -> dict:
    return {
        "mode": req.mode,
        "image": req.image or default_image(machine.machine_type),
        "device_ids": req.device_ids,
        "mounts": req.mounts,
        "env": req.env,
        "network": req.network,
        "ports": req.ports,
        "command": req.command,
        "shm_size": req.shm_size,
        "extra_devices": req.extra_devices,
    }


@router.post("/preview")
def preview_command(req: JobCreateRequest, db: Session = Depends(get_db)):
    """生成 docker run 命令预览（不创建任务）

    提交时容器名按 va-<type>-<任务id> 自动生成，预览用固定占位名。
    """
    machine = _get_machine_or_404(db, req.machine_id)
    spec = _spec_from_req(req, machine)
    spec["container_name"] = "va-preview"
    try:
        cmd = build_docker_run(machine.machine_type, spec)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"docker_cmd": cmd, "image": spec["image"]}


@router.post("")
def create_job(req: JobCreateRequest, db: Session = Depends(get_db)):
    """提交容器任务（异步执行，返回任务记录）"""
    machine = _get_machine_or_404(db, req.machine_id)
    spec = _spec_from_req(req, machine)
    try:
        job = job_service.create_and_submit(
            machine,
            job_type=req.type,
            mode=req.mode,
            name=req.name,
            spec=spec,
            timeout=req.timeout,
            source="ui",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return job.to_dict()


@router.get("")
def list_jobs(machine_id: Optional[int] = None, status: Optional[str] = None,
              job_type: Optional[str] = None, limit: int = Query(50, le=500),
              db: Session = Depends(get_db)):
    q = db.query(NpuJob)
    if machine_id is not None:
        q = q.filter(NpuJob.machine_id == machine_id)
    if status:
        q = q.filter(NpuJob.status == status)
    if job_type:
        q = q.filter(NpuJob.type == job_type)
    rows = q.order_by(NpuJob.id.desc()).limit(limit).all()
    return [j.to_dict() for j in rows]


# ----------------------------------------------------------------------
# 容器任务模板
# ----------------------------------------------------------------------

@router.get("/templates")
def list_templates(db: Session = Depends(get_db)):
    rows = db.query(NpuContainerTemplate).order_by(NpuContainerTemplate.id).all()
    return [t.to_dict() for t in rows]


@router.post("/templates")
def create_template(req: TemplateSaveRequest, db: Session = Depends(get_db)):
    import json
    if db.query(NpuContainerTemplate).filter(NpuContainerTemplate.name == req.name).first():
        raise HTTPException(status_code=400, detail=f"模板名已存在: {req.name}")
    row = NpuContainerTemplate(
        name=req.name,
        mode=req.mode,
        machine_type=req.machine_type or None,
        image=req.image or None,
        devices=json.dumps(req.device_ids) if req.device_ids is not None else None,
        mounts=json.dumps(req.mounts) if req.mounts else None,
        env=json.dumps(req.env) if req.env else None,
        network=req.network,
        ports=json.dumps(req.ports) if req.ports else None,
        command=req.command,
        shm_size=req.shm_size or None,
        notes=req.notes or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    row = db.query(NpuContainerTemplate).filter(NpuContainerTemplate.id == template_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


# 注意：带路径参数的路由必须注册在静态路径（/preview、/templates）之后，
# 否则 "preview"/"templates" 会被当作 job_id 匹配。

@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict()


@router.get("/{job_id}/log")
def get_job_log(job_id: int, offset: int = 0, tail: int = Query(200, le=2000),
                db: Session = Depends(get_db)):
    """任务日志：oneshot 按 offset 增量读文件；persistent 运行中拉 docker logs"""
    job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    machine = db.query(NpuMachine).filter(NpuMachine.id == job.machine_id).first()
    params = machine.to_ssh_params() if machine else {}
    return job_service.get_job_log(job, params, offset=offset, tail_lines=tail)


@router.post("/{job_id}/stop")
def stop_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job_service.stop_job(job_id)
