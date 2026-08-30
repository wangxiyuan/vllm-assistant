"""NPU 模型服务实例 API

部署（三击：机器→模型→启动）、启停、健康检查、调试信息（debugpy attach），
以及统一推理网关（/proxy/v1/* 透传，Playground 与外部脚本的数据通道）。
"""
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

import httpx

from app.database import get_db
from app.models import NpuMachine, NpuServiceInstance
from app.services.npu import deploy as deploy_service

logger = logging.getLogger(__name__)
router = APIRouter()

_HOP_HEADERS = {"content-length", "transfer-encoding", "connection", "keep-alive",
                "host", "accept-encoding"}


class ServiceDeployRequest(BaseModel):
    machine_id: int
    name: str
    model_dir: str  # 机器上模型权重目录（同路径挂载进容器）
    model_name: str = ""  # --served-model-name，空 = 实例名
    image: str = ""  # 空 = 机型默认镜像
    port: int = 8000
    device_ids: Optional[List[int]] = None  # 使用的 NPU 卡号（docker --device），None = 全部卡
    network: str = "host"
    ports: List[str] = []  # bridge 模式映射；host 模式自动生成
    env: Dict[str, str] = {}
    trust_remote_code: bool = True
    serve_args: str = ""
    # 并行策略（SP 随 TP>1 且 DP>1 自动启用，无独立参数）
    tp: int = 1
    dp: Optional[int] = None
    pp: Optional[int] = None
    pcp: Optional[int] = None  # --prefill-context-parallel-size
    dcp: Optional[int] = None  # --decode-context-parallel-size
    enable_ep: bool = False
    distributed_backend: str = ""  # auto / mp / ray / ...
    # 内存与缓存
    max_model_len: Optional[int] = None
    gpu_memory_utilization: Optional[float] = None
    max_num_seqs: Optional[int] = None
    max_num_batched_tokens: Optional[int] = None
    block_size: Optional[int] = None
    kv_cache_dtype: Optional[str] = None
    swap_space: Optional[float] = None
    # 精度与加载
    dtype: str = "auto"
    quantization: str = ""
    load_format: str = "auto"
    # 性能
    enforce_eager: bool = False
    seed: Optional[int] = None
    # JSON 配置（vllm-ascend 高频：speculative/compilation/additional）
    speculative_config: Optional[dict] = None
    compilation_config: Optional[dict] = None
    additional_config: Optional[dict] = None
    # 调试与 Profiling
    debug_mode: bool = False
    debugpy_port: int = 5678
    wait_for_client: bool = False
    profiling_enabled: bool = False
    profiler_with_stack: bool = False

    @field_validator("network")
    @classmethod
    def _validate_network(cls, v):
        if v not in ("host", "bridge"):
            raise ValueError("network must be host/bridge")
        return v


def _get_instance_or_404(db: Session, instance_id: int) -> NpuServiceInstance:
    instance = db.query(NpuServiceInstance).filter(
        NpuServiceInstance.id == instance_id).first()
    if instance is None:
        raise HTTPException(status_code=404, detail="服务实例不存在")
    return instance


@router.get("")
def list_services(db: Session = Depends(get_db)):
    rows = db.query(NpuServiceInstance).order_by(NpuServiceInstance.id).all()
    return [s.to_dict() for s in rows]


@router.post("")
def deploy(req: ServiceDeployRequest, db: Session = Depends(get_db)):
    machine = db.query(NpuMachine).filter(NpuMachine.id == req.machine_id).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机器不存在")
    try:
        result = deploy_service.deploy_service(machine, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"部署发起失败: {e}")
    return result


@router.post("/{instance_id}/stop")
def stop(instance_id: int, db: Session = Depends(get_db)):
    _get_instance_or_404(db, instance_id)
    return deploy_service.stop_service(instance_id)


@router.post("/{instance_id}/start")
def start(instance_id: int, db: Session = Depends(get_db)):
    _get_instance_or_404(db, instance_id)
    return deploy_service.start_service(instance_id)


@router.post("/{instance_id}/restart")
def restart(instance_id: int, db: Session = Depends(get_db)):
    _get_instance_or_404(db, instance_id)
    deploy_service.stop_service(instance_id)
    return deploy_service.start_service(instance_id)


@router.get("/{instance_id}/health")
def health(instance_id: int, db: Session = Depends(get_db)):
    _get_instance_or_404(db, instance_id)
    return deploy_service.check_health_once(instance_id)


@router.delete("/{instance_id}")
def delete(instance_id: int, db: Session = Depends(get_db)):
    instance = _get_instance_or_404(db, instance_id)
    if instance.status in ("running", "deploying"):
        deploy_service.stop_service(instance_id)
    row = db.query(NpuServiceInstance).filter(
        NpuServiceInstance.id == instance_id).first()
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{instance_id}/profile/start")
def start_profile(instance_id: int, db: Session = Depends(get_db),
                  notes: str = ""):
    """开始 Profiling 采集（服务需以 Profiling 模式部署且在运行中）"""
    _get_instance_or_404(db, instance_id)
    from app.services.npu import profiler
    try:
        return profiler.start_collection(instance_id, notes=notes)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{instance_id}/debug-info")
def debug_info(instance_id: int, db: Session = Depends(get_db)):
    """调试模式实例的 attach 信息：VSCode launch.json 片段 + 命令行 attach 命令"""
    instance = _get_instance_or_404(db, instance_id)
    machine = db.query(NpuMachine).filter(
        NpuMachine.id == instance.machine_id).first()
    if instance.debug_mode is False or not instance.debugpy_port:
        raise HTTPException(status_code=400, detail="该实例未开启调试模式")
    host = machine.host if machine else "<machine-host>"
    connect_host = host
    # bridge 网络时 debugpy 端口映射与 serve 端口同理（ports 里找 debugpy 端口映射）
    debug_port = instance.debugpy_port
    launch_json = {
        "name": f"Attach NPU {instance.name}",
        "type": "debugpy",
        "request": "attach",
        "connect": {"host": connect_host, "port": debug_port},
        "justMyCode": False,
        "pathMappings": [
            {"localRoot": "${workspaceFolder}",
             "remoteRoot": "/vllm-workspace"},
        ],
    }
    return {
        "attach_host": connect_host,
        "attach_port": debug_port,
        "wait_for_client": bool(instance.wait_for_client),
        "launch_json": launch_json,
        "cli_cmd": f"python -m debugpy --connect {connect_host}:{debug_port}",
        "hint": ("未开启 wait_for_client 时服务立即启动，可随时 attach；"
                 "开启后服务会挂起直到调试器连接。断点打在 /vllm-workspace 下的源码。"),
    }


# ----------------------------------------------------------------------
# 统一推理网关：/proxy/v1/* 透传（含 SSE 流式）
# ----------------------------------------------------------------------

def _target_base_url(instance: NpuServiceInstance, machine: NpuMachine) -> str:
    import json
    host_port = 8000
    ports = json.loads(instance.ports) if instance.ports else []
    for p in ports:
        hp, _, cp = p.partition(":")
        if cp:
            host_port = int(hp)
            break
    return f"http://{machine.host}:{host_port}"


@router.api_route("/{instance_id}/proxy/v1/{path:path}",
                  methods=["GET", "POST"])
async def proxy_v1(instance_id: int, path: str, request: Request,
                   db: Session = Depends(get_db)):
    """OpenAI 兼容 API 透传（/v1/chat/completions、/v1/models、/v1/completions 等）"""
    instance = _get_instance_or_404(db, instance_id)
    if instance.status != "running":
        raise HTTPException(status_code=409,
                            detail=f"服务实例未在运行（{instance.status}）")
    machine = db.query(NpuMachine).filter(NpuMachine.id == instance.machine_id).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机器不存在")
    base = _target_base_url(instance, machine)

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _HOP_HEADERS}
    body = await request.body()

    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, read=600.0))
    try:
        req = client.build_request(
            request.method, f"{base}/v1/{path}",
            content=body, headers=headers,
            params=dict(request.query_params))
        resp = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"上游服务请求失败: {e}")

    out_headers = {k: v for k, v in resp.headers.items()
                   if k.lower() not in _HOP_HEADERS}
    media_type = resp.headers.get("content-type", "application/json")

    async def _stream():
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(_stream(), status_code=resp.status_code,
                             headers=out_headers, media_type=media_type)
