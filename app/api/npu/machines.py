"""NPU 机器纳管 API

机器 CRUD、连通性测试（SSH + npu-smi 探测）、立即巡检、巡检历史、
镜像/模型目录扫描缓存、SSH 配置片段生成（供 VSCode Remote-SSH 等）。
"""
import json
import logging
from typing import List, Optional

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.config import Config
from app.database import get_db
from app.models import NpuImage, NpuMachine, NpuMachineMetric, NpuModelDir
from app.services.npu import ssh
from app.services.npu.collector import inspect_machine, test_machine
from app.services.npu.profiles import get_profile, profile_options

logger = logging.getLogger(__name__)
router = APIRouter()


class MachineCreateRequest(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str
    auth_type: str = "key"  # key / password
    key_content: str = ""  # 私钥内容（粘贴或文件读取，Fernet 加密落库，优先于 key_path）
    key_path: str = ""  # 服务端私钥路径（兼容模式）
    password: str = ""  # 明文入参，Fernet 加密后落库，不回显
    machine_type: str = "a2"  # a2 / a3 / 310p / other
    workdir: str = "~/npu-workspace"
    model_root: str = ""
    tags: List[str] = []
    enabled: bool = True

    @field_validator("auth_type")
    @classmethod
    def _validate_auth(cls, v):
        if v not in ("key", "password"):
            raise ValueError("auth_type must be 'key' or 'password'")
        return v

    @field_validator("machine_type")
    @classmethod
    def _validate_machine_type(cls, v):
        if v not in ("a2", "a3", "310p", "other"):
            raise ValueError("machine_type must be a2/a3/310p/other")
        return v


class MachineUpdateRequest(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    auth_type: Optional[str] = None
    key_content: Optional[str] = None  # 传空字符串表示清除私钥内容
    key_path: Optional[str] = None
    password: Optional[str] = None  # 传空字符串表示清除密码
    machine_type: Optional[str] = None
    workdir: Optional[str] = None
    model_root: Optional[str] = None
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None

    @field_validator("auth_type")
    @classmethod
    def _validate_auth(cls, v):
        if v is not None and v not in ("key", "password"):
            raise ValueError("auth_type must be 'key' or 'password'")
        return v

    @field_validator("machine_type")
    @classmethod
    def _validate_machine_type(cls, v):
        if v is not None and v not in ("a2", "a3", "310p", "other"):
            raise ValueError("machine_type must be a2/a3/310p/other")
        return v


class ModelDirAddRequest(BaseModel):
    path: str
    note: str = ""


def _get_machine_or_404(db: Session, machine_id: int) -> NpuMachine:
    machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机器不存在")
    return machine


def _encrypt_password(plain: str) -> str:
    return Fernet(Config.get_npu_secret_key()).encrypt(plain.encode()).decode()


@router.get("/profile-options")
def get_profile_options():
    """机型下拉选项（含默认镜像/卡数/说明）"""
    return profile_options()


@router.get("")
def list_machines(db: Session = Depends(get_db)):
    machines = db.query(NpuMachine).order_by(NpuMachine.id).all()
    return [m.to_dict() for m in machines]


@router.post("")
def create_machine(req: MachineCreateRequest, db: Session = Depends(get_db)):
    if db.query(NpuMachine).filter(NpuMachine.name == req.name).first():
        raise HTTPException(status_code=400, detail=f"机器名已存在: {req.name}")
    if req.auth_type == "password" and not req.password:
        raise HTTPException(status_code=400, detail="密码认证方式必须提供密码")
    if req.auth_type == "key" and not req.key_content.strip() and not req.key_path:
        raise HTTPException(status_code=400, detail="密钥认证方式必须提供私钥内容或私钥路径")

    machine = NpuMachine(
        name=req.name,
        host=req.host,
        port=req.port or 22,
        username=req.username,
        auth_type=req.auth_type,
        key_path=req.key_path or None,
        key_content_enc=_encrypt_password(req.key_content) if req.key_content.strip() else None,
        password_enc=_encrypt_password(req.password) if req.password else None,
        machine_type=req.machine_type,
        workdir=req.workdir or "~/npu-workspace",
        model_root=req.model_root or None,
        tags=json.dumps(req.tags) if req.tags else None,
        enabled=req.enabled,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return machine.to_dict()


@router.put("/{machine_id}")
def update_machine(machine_id: int, req: MachineUpdateRequest, db: Session = Depends(get_db)):
    machine = _get_machine_or_404(db, machine_id)
    if req.auth_type is not None:
        machine.auth_type = req.auth_type
    if req.password is not None:
        machine.password_enc = _encrypt_password(req.password) if req.password else None
    if req.key_content is not None:
        machine.key_content_enc = _encrypt_password(req.key_content) if req.key_content.strip() else None
    for field in ("host", "port", "username", "key_path", "machine_type", "workdir", "model_root", "enabled"):
        value = getattr(req, field)
        if value is not None:
            setattr(machine, field, value)
    if req.tags is not None:
        machine.tags = json.dumps(req.tags)
    db.commit()
    db.refresh(machine)
    # 凭证/地址可能变更，丢弃旧连接
    ssh.drop_conn(machine.to_ssh_params())
    return machine.to_dict()


@router.delete("/{machine_id}")
def delete_machine(machine_id: int, db: Session = Depends(get_db)):
    machine = _get_machine_or_404(db, machine_id)
    ssh.drop_conn(machine.to_ssh_params())
    db.delete(machine)
    db.commit()
    return {"ok": True}


@router.post("/{machine_id}/test")
def test_machine_connection(machine_id: int, db: Session = Depends(get_db)):
    """连通性测试：SSH 连接 + npu-smi 探测（同步，最长约 2 分钟）"""
    _get_machine_or_404(db, machine_id)
    return test_machine(machine_id)


@router.post("/{machine_id}/refresh")
def refresh_machine(machine_id: int, db: Session = Depends(get_db)):
    """立即巡检一次（同步）"""
    _get_machine_or_404(db, machine_id)
    return inspect_machine(machine_id)


@router.get("/{machine_id}/metrics")
def machine_metrics(machine_id: int, hours: int = Query(24, ge=1, le=24 * 30),
                    db: Session = Depends(get_db)):
    """巡检历史（利用率曲线数据点）"""
    _get_machine_or_404(db, machine_id)
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    rows = (db.query(NpuMachineMetric)
            .filter(NpuMachineMetric.machine_id == machine_id,
                    NpuMachineMetric.ts >= since)
            .order_by(NpuMachineMetric.ts)
            .limit(5000)
            .all())
    return [r.to_dict() for r in rows]


@router.get("/{machine_id}/images")
def machine_images(machine_id: int, db: Session = Depends(get_db)):
    """机器上的容器镜像列表（扫描缓存）"""
    _get_machine_or_404(db, machine_id)
    rows = (db.query(NpuImage)
            .filter(NpuImage.machine_id == machine_id)
            .order_by(NpuImage.full_name)
            .all())
    return [r.to_dict() for r in rows]


@router.get("/{machine_id}/models")
def machine_models(machine_id: int, db: Session = Depends(get_db)):
    """机器上的模型权重目录（扫描 + 手动登记）"""
    _get_machine_or_404(db, machine_id)
    rows = (db.query(NpuModelDir)
            .filter(NpuModelDir.machine_id == machine_id)
            .order_by(NpuModelDir.path)
            .all())
    return [r.to_dict() for r in rows]


@router.post("/{machine_id}/models")
def add_model_dir(machine_id: int, req: ModelDirAddRequest, db: Session = Depends(get_db)):
    """手动登记模型目录（扫描发现不了的场景，如自定义结构）"""
    _get_machine_or_404(db, machine_id)
    path = req.path.strip().rstrip("/")
    if not path:
        raise HTTPException(status_code=400, detail="path 不能为空")
    existing = db.query(NpuModelDir).filter(
        NpuModelDir.machine_id == machine_id, NpuModelDir.path == path).first()
    if existing:
        return existing.to_dict()
    row = NpuModelDir(machine_id=machine_id, path=path, note=req.note, source="manual")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.to_dict()


@router.delete("/{machine_id}/models/{model_dir_id}")
def delete_model_dir(machine_id: int, model_dir_id: int, db: Session = Depends(get_db)):
    row = db.query(NpuModelDir).filter(
        NpuModelDir.id == model_dir_id, NpuModelDir.machine_id == machine_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="模型目录不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/{machine_id}/npus")
def machine_npus(machine_id: int, db: Session = Depends(get_db)):
    """NPU 卡占用情况：卡号多选组件数据源

    total 来自巡检结果（npu_count），缺失时回退机型 profile 默认卡数；
    occupied 聚合运行中服务实例与运行中常驻任务声明的卡号。
    """
    machine = _get_machine_or_404(db, machine_id)
    from app.models import NpuJob, NpuServiceInstance
    from app.services.npu.profiles import get_profile

    total = machine.npu_count or get_profile(machine.machine_type).get("npu_count") or 0
    occupied: dict = {}
    instances = db.query(NpuServiceInstance).filter(
        NpuServiceInstance.machine_id == machine_id,
        NpuServiceInstance.status.in_(["deploying", "running"])).all()
    for s in instances:
        try:
            for i in (json.loads(s.devices) if s.devices else []):
                occupied.setdefault(int(i), s.name)
        except (ValueError, TypeError):
            pass
    jobs = db.query(NpuJob).filter(
        NpuJob.machine_id == machine_id,
        NpuJob.mode == "persistent",
        NpuJob.status == "running").all()
    for j in jobs:
        try:
            payload = json.loads(j.payload) if j.payload else {}
            for i in (payload.get("device_ids") or []):
                occupied.setdefault(int(i), j.container_name or f"job-{j.id}")
        except (ValueError, TypeError):
            pass
    return {
        "machine_id": machine_id,
        "total": total,
        "occupied": occupied,  # {卡号: 占用者名}
    }


@router.get("/{machine_id}/ssh-info")
def machine_ssh_info(machine_id: int, db: Session = Depends(get_db)):
    """生成 SSH 连接命令与 ~/.ssh/config 片段（复制到本机使用）"""
    machine = _get_machine_or_404(db, machine_id)
    ssh_cmd = f"ssh -p {machine.port or 22} {machine.username}@{machine.host}"
    config_block = (
        f"Host npu-{machine.name}\n"
        f"    HostName {machine.host}\n"
        f"    Port {machine.port or 22}\n"
        f"    User {machine.username}\n"
        + (f"    IdentityFile ~/.ssh/<你的私钥>\n" if machine.auth_type == "key" else "")
    )
    exec_hint = f"ssh -t -p {machine.port or 22} {machine.username}@{machine.host} " \
                f"'docker exec -it <容器名> bash'"
    return {
        "ssh_cmd": ssh_cmd,
        "ssh_config": config_block,
        "exec_hint": exec_hint,
        "machine_type": machine.machine_type,
        "profile_notes": get_profile(machine.machine_type).get("notes", ""),
    }
