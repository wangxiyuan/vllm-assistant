"""vLLM 服务部署编排

容器形态的 vllm serve 实例生命周期：
- 部署：生成 serve 命令（可选 debugpy 调试注入 / --profiler-config 性能采集注入），
  经任务体系（persistent job）docker run -d 启动，随后后台健康检查直到 /health 200
- 停止：SSH docker rm -f；启动/重启：重放 payload 中的 docker_cmd
"""
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from app.config import Config
from app.database import SessionLocal
from app.models import NpuJob, NpuMachine, NpuServiceInstance
from app.services.npu import ssh

logger = logging.getLogger(__name__)

# 健康检查后台线程与取消标记（单进程内存态）
_health_threads: Dict[int, threading.Event] = {}
_health_lock = threading.Lock()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def build_serve_command(params: dict) -> str:
    """生成容器内执行的 vllm serve 命令（结构化参数版）。

    params 关键字段（全部可选，缺省不注入对应 CLI 参数）：
    - model_path（必填）、port、model_name、trust_remote_code
    - 并行策略：tp、dp、pp、pcp（prefill context parallel）、dcp（decode context
      parallel）、enable_ep、distributed_backend（mp/ray/...）。SP 无独立 CLI 参数：
      vllm-ascend 文档明确 TP>1 且 DP>1（MoE+EP）时自动启用，无需注入
    - 内存与缓存：max_model_len、gpu_memory_utilization、max_num_seqs、
      max_num_batched_tokens、block_size、kv_cache_dtype、swap_space
    - 精度与加载：dtype、quantization、load_format
    - 性能：enforce_eager、seed
    - JSON 配置：speculative_config、compilation_config、additional_config（dict，
      vllm-ascend 高频：ascend_scheduler_config / ascend_compilation_config 等）
    - serve_args：额外参数文本（保留，追加在最后）
    - 调试：debug_mode、debugpy_port、wait_for_client
    - Profiling：profiler_config（dict，注入 --profiler-config）
    """
    model_path = params.get("model_path") or ""
    if not model_path:
        raise ValueError("model_path 不能为空")
    port = int(params.get("port") or 8000)

    args: list = [f"vllm serve {model_path}", "--host 0.0.0.0", f"--port {port}"]

    def _num(key: str, flag: str, cast=int):
        v = params.get(key)
        if v not in (None, "", 0) or (key == "tp" and v):
            args.append(f"{flag} {cast(v)}")

    # 并行策略
    _num("tp", "--tensor-parallel-size")
    _num("dp", "--data-parallel-size")
    _num("pp", "--pipeline-parallel-size")
    _num("pcp", "--prefill-context-parallel-size")
    _num("dcp", "--decode-context-parallel-size")
    if params.get("enable_ep"):
        args.append("--enable-expert-parallel")
    backend = (params.get("distributed_backend") or "").strip()
    if backend and backend != "auto":
        args.append(f"--distributed-executor-backend {backend}")

    if params.get("model_name"):
        args.append(f"--served-model-name {params['model_name']}")
    if params.get("trust_remote_code"):
        args.append("--trust-remote-code")

    # 内存与缓存
    _num("max_model_len", "--max-model-len")
    _num("max_num_seqs", "--max-num-seqs")
    _num("max_num_batched_tokens", "--max-num-batched-tokens")
    _num("swap_space", "--swap-space", cast=float)
    if params.get("gpu_memory_utilization") not in (None, ""):
        args.append(f"--gpu-memory-utilization {params['gpu_memory_utilization']}")
    if params.get("block_size"):
        args.append(f"--block-size {params['block_size']}")
    if params.get("kv_cache_dtype"):
        args.append(f"--kv-cache-dtype {params['kv_cache_dtype']}")

    # 精度与加载
    if params.get("dtype") and params["dtype"] != "auto":
        args.append(f"--dtype {params['dtype']}")
    if params.get("quantization"):
        args.append(f"--quantization {params['quantization']}")
    if params.get("load_format") and params["load_format"] != "auto":
        args.append(f"--load-format {params['load_format']}")

    # 性能
    if params.get("enforce_eager"):
        args.append("--enforce-eager")
    if params.get("seed") not in (None, ""):
        args.append(f"--seed {params['seed']}")

    # JSON 配置（dict → JSON 字符串，单引号包裹安全）
    for key, flag in (("speculative_config", "--speculative-config"),
                      ("compilation_config", "--compilation-config"),
                      ("additional_config", "--additional-config")):
        cfg = params.get(key)
        if cfg:
            if isinstance(cfg, str):
                cfg = json.loads(cfg)
            args.append(f"{flag} '{json.dumps(cfg, ensure_ascii=False, separators=(',', ':'))}'")

    if (params.get("serve_args") or "").strip():
        args.append(params["serve_args"].strip())
    if params.get("profiler_config"):
        args.append(f"--profiler-config '{json.dumps(params['profiler_config'], ensure_ascii=False)}'")

    serve = " ".join(args)
    if params.get("debug_mode"):
        wait = "--wait-for-client " if params.get("wait_for_client") else ""
        debugpy_port = int(params.get("debugpy_port") or 5678)
        return (f"pip install debugpy -q && "
                f"python -m debugpy --listen 0.0.0.0:{debugpy_port} {wait}-- "
                f"{serve}")
    return serve


def _health_url(machine_host: str, network: str, serve_port: int, ports: list) -> str:
    """计算管理服务可达的健康检查地址"""
    host_port = serve_port
    if network == "bridge":
        for p in ports or []:
            hp, _, cp = p.partition(":")
            if cp and cp == str(serve_port):
                host_port = int(hp)
                break
    return f"http://{machine_host}:{host_port}"


def deploy_service(machine: NpuMachine, params: dict) -> Dict[str, Any]:
    """创建服务实例并启动（返回 instance 与 job）"""
    name = (params.get("name") or "").strip()
    if not name:
        raise ValueError("实例名不能为空")
    model_dir = (params.get("model_dir") or "").strip()
    if not model_dir:
        raise ValueError("模型目录不能为空")
    port = int(params.get("port") or 8000)

    db = SessionLocal()
    try:
        exists = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.name == name).first()
        if exists:
            raise ValueError(f"实例名已存在: {name}")
    finally:
        db.close()

    container_name = f"va-serve-{name}"
    network = params.get("network") or "host"
    tp = int(params.get("tp") or 1)
    devices = params.get("device_ids")
    profiling_enabled = bool(params.get("profiling_enabled"))
    workdir = machine.workdir or "~/npu-workspace"

    profiling_dir = None
    profiler_config = None
    mounts = [model_dir]
    if profiling_enabled:
        # torch_profiler_dir 必须是绝对路径（容器内 ~ 不展开），
        # workdir 支持 ~/ 形式，经 SSH 取真实 $HOME 展开
        workdir_abs = workdir
        if workdir_abs.startswith("~/"):
            code, out, _ = ssh.run_command(machine.to_ssh_params(),
                                           "echo $HOME", timeout=20)
            workdir_abs = out.strip() + workdir_abs[1:]
        profiling_dir = f"{workdir_abs}/profiling/{name}"
        with_stack = bool(params.get("profiler_with_stack", False))
        profiler_config = {
            "profiler": "torch",
            "torch_profiler_dir": profiling_dir,
            "torch_profiler_with_stack": with_stack,
        }
        mounts.append(profiling_dir)
        # 预创建输出目录（同路径挂载，容器内进程直接写入机器目录）
        try:
            ssh.make_dir(machine.to_ssh_params(), profiling_dir)
        except Exception as e:
            logger.warning(f"create profiling dir failed: {e}")

    serve_params = {
        "model_path": model_dir,
        "port": port,
        "model_name": params.get("model_name") or name,
        "trust_remote_code": bool(params.get("trust_remote_code", True)),
        "serve_args": params.get("serve_args") or "",
        "debug_mode": bool(params.get("debug_mode")),
        "debugpy_port": int(params.get("debugpy_port") or 5678),
        "wait_for_client": bool(params.get("wait_for_client")),
        "profiler_config": profiler_config,
        # 并行策略
        "tp": params.get("tp") or 1,
        "dp": params.get("dp"),
        "pp": params.get("pp"),
        "pcp": params.get("pcp"),
        "dcp": params.get("dcp"),
        "enable_ep": bool(params.get("enable_ep")),
        "distributed_backend": params.get("distributed_backend") or "",
        # 内存与缓存
        "max_model_len": params.get("max_model_len"),
        "gpu_memory_utilization": params.get("gpu_memory_utilization"),
        "max_num_seqs": params.get("max_num_seqs"),
        "max_num_batched_tokens": params.get("max_num_batched_tokens"),
        "block_size": params.get("block_size"),
        "kv_cache_dtype": params.get("kv_cache_dtype"),
        "swap_space": params.get("swap_space"),
        # 精度与加载
        "dtype": params.get("dtype") or "auto",
        "quantization": params.get("quantization"),
        "load_format": params.get("load_format"),
        # 性能
        "enforce_eager": bool(params.get("enforce_eager")),
        "seed": params.get("seed"),
        # JSON 配置
        "speculative_config": params.get("speculative_config"),
        "compilation_config": params.get("compilation_config"),
        "additional_config": params.get("additional_config"),
    }
    try:
        serve_cmd = build_serve_command(serve_params)
    except ValueError as e:
        raise
    except Exception as e:
        raise ValueError(f"serve 命令生成失败: {e}")

    ports = params.get("ports") or []
    if network == "host":
        ports = [f"{port}:{port}"]

    spec = {
        "mode": "persistent",
        "image": params.get("image"),
        "device_ids": devices,
        "mounts": mounts,
        "env": params.get("env") or {},
        "network": network,
        "ports": ports,
        "command": serve_cmd,
        "shm_size": params.get("shm_size") or "",
    }

    db = SessionLocal()
    try:
        instance = NpuServiceInstance(
            machine_id=machine.id,
            name=name,
            model_dir=model_dir,
            model_name=params.get("model_name") or name,
            image=spec["image"],
            container_name=container_name,
            mounts=json.dumps(spec["mounts"]),
            env=json.dumps(spec["env"]),
            network=network,
            ports=json.dumps(ports),
            devices=json.dumps(devices) if devices is not None else None,
            tp=tp,
            serve_args=params.get("serve_args") or None,
            serve_params=json.dumps(serve_params, ensure_ascii=False),
            debug_mode=bool(params.get("debug_mode")),
            debugpy_port=int(params.get("debugpy_port") or 5678) if params.get("debug_mode") else None,
            wait_for_client=bool(params.get("wait_for_client")) if params.get("debug_mode") else False,
            profiling_enabled=profiling_enabled,
            profiling_dir=profiling_dir,
            health_url=_health_url(machine.host, network, port, ports),
            status="deploying",
        )
        db.add(instance)
        db.commit()
        db.refresh(instance)
        instance_id = instance.id
    finally:
        db.close()

    job = _submit_run_job(machine, instance_id, spec, job_type="deploy")
    _start_health_wait(instance_id)
    return {"instance_id": instance_id, "job_id": job.id}


def _submit_run_job(machine: NpuMachine, instance_id: int, spec: dict,
                    job_type: str) -> NpuJob:
    """经任务体系启动常驻服务容器（docker run -d）"""
    from app.services.npu import jobs as job_service
    return job_service.create_and_submit(
        machine,
        job_type=job_type,
        mode="persistent",
        name=f"serve-{instance_id}",
        spec=spec,
        source="ui",
        service_id=instance_id,
    )


def stop_service(instance_id: int) -> dict:
    """停止服务：docker rm -f 容器，取消健康检查线程"""
    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id).first()
        if instance is None:
            return {"ok": False, "message": "实例不存在"}
        machine = db.query(NpuMachine).filter(
            NpuMachine.id == instance.machine_id).first()
        container = instance.container_name
    finally:
        db.close()
    if machine is None:
        return {"ok": False, "message": "机器不存在"}

    _cancel_health_wait(instance_id)
    try:
        ssh.run_command(machine.to_ssh_params(),
                        f"docker rm -f {container} 2>/dev/null; true", timeout=120)
    except Exception as e:
        logger.warning(f"stop service {instance_id}: {e}")

    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id).first()
        if instance:
            instance.status = "stopped"
            instance.container_id = None
            db.commit()
    finally:
        db.close()

    # 关联的 persistent job 一并标记停止
    db = SessionLocal()
    try:
        jobs = db.query(NpuJob).filter(
            NpuJob.service_id == instance_id,
            NpuJob.status.in_(["pending", "running"])).all()
        for j in jobs:
            j.status = "cancelled"
            j.finished_at = _now()
        db.commit()
    finally:
        db.close()
    return {"ok": True}


def start_service(instance_id: int) -> dict:
    """启动（重启）服务：重放 payload 中的 docker_cmd"""
    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id).first()
        if instance is None:
            return {"ok": False, "message": "实例不存在"}
        machine = db.query(NpuMachine).filter(
            NpuMachine.id == instance.machine_id).first()
        if machine is None:
            return {"ok": False, "message": "机器不存在"}
        mounts = json.loads(instance.mounts) if instance.mounts else []
        env = json.loads(instance.env) if instance.env else {}
        devices = json.loads(instance.devices) if instance.devices else None
        ports = json.loads(instance.ports) if instance.ports else []
        instance.status = "deploying"
        db.commit()
        instance_id_ = instance.id
    finally:
        db.close()

    # 重放持久化的结构化 serve 参数（与部署时完全一致）
    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id_).first()
        serve_params = json.loads(instance.serve_params) if instance.serve_params else None
    finally:
        db.close()

    if serve_params:
        serve_cmd = build_serve_command(serve_params)
    else:
        # 旧实例无 serve_params（升级前创建），按基础参数重建
        db = SessionLocal()
        try:
            instance = db.query(NpuServiceInstance).filter(
                NpuServiceInstance.id == instance_id_).first()
            serve_params = {
                "model_path": instance.model_dir,
                "port": _serve_port(instance),
                "model_name": instance.model_name or "",
                "trust_remote_code": True,
                "serve_args": instance.serve_args or "",
                "tp": instance.tp or 1,
                "debug_mode": bool(instance.debug_mode),
                "debugpy_port": instance.debugpy_port or 5678,
                "wait_for_client": bool(instance.wait_for_client),
                "profiler_config": (
                    {"profiler": "torch", "torch_profiler_dir": instance.profiling_dir,
                     "torch_profiler_with_stack": False}
                    if instance.profiling_enabled and instance.profiling_dir else None),
            }
            serve_cmd = build_serve_command(serve_params)
        finally:
            db.close()

    spec = {
        "mode": "persistent",
        "image": None,  # 由 _submit_run_job 内部无法拿到 image；见下
        "device_ids": devices,
        "mounts": mounts,
        "env": env,
        "network": "host" if not ports else "bridge",
        "ports": ports,
        "command": serve_cmd,
        "shm_size": "",
    }
    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id_).first()
        spec["image"] = instance.image
        spec["network"] = instance.network
    finally:
        db.close()

    job = _submit_run_job(machine, instance_id_, spec, job_type="service_start")
    _start_health_wait(instance_id_)
    return {"ok": True, "job_id": job.id}


def _serve_port(instance: NpuServiceInstance) -> int:
    """从 ports 约定解析 serve 端口（映射的容器侧端口）"""
    ports = json.loads(instance.ports) if instance.ports else []
    for p in ports:
        _, _, cp = p.partition(":")
        if cp:
            return int(cp)
    return 8000


def check_health_once(instance_id: int) -> dict:
    """手动健康检查一次"""
    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id).first()
        if instance is None:
            return {"ok": False, "message": "实例不存在"}
        health_url = instance.health_url
    finally:
        db.close()
    try:
        resp = requests.get(f"{health_url}/health", timeout=10)
        ok = resp.status_code == 200
        last_err = None
    except Exception as e:
        ok = False
        resp = None
        last_err = str(e)
    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id).first()
        if instance:
            instance.last_health_at = _now()
            instance.last_health_ok = ok
            if ok and instance.status in ("deploying", "unknown"):
                instance.status = "running"
            db.commit()
    finally:
        db.close()
    return {"ok": ok, "health_url": health_url, "error": last_err if not ok else None}


def _start_health_wait(instance_id: int) -> None:
    """启动后台健康检查线程：轮询 /health 直到 200 或超时"""
    stop_event = threading.Event()
    with _health_lock:
        _health_threads[instance_id] = stop_event

    def _wait():
        deadline = time.time() + Config.NPU_HEALTH_TIMEOUT
        # 给容器启动留缓冲，健康检查初期失败属正常（模型加载慢）
        time.sleep(5)
        ok = False
        while time.time() < deadline and not stop_event.is_set():
            db = SessionLocal()
            try:
                instance = db.query(NpuServiceInstance).filter(
                    NpuServiceInstance.id == instance_id).first()
                if instance is None or instance.status == "stopped":
                    return
                health_url = instance.health_url
                status_now = instance.status
            finally:
                db.close()
            try:
                resp = requests.get(f"{health_url}/health", timeout=10)
                ok = resp.status_code == 200
            except Exception:
                ok = False
            db = SessionLocal()
            try:
                instance = db.query(NpuServiceInstance).filter(
                    NpuServiceInstance.id == instance_id).first()
                if instance:
                    instance.last_health_at = _now()
                    instance.last_health_ok = ok
                    if ok:
                        instance.status = "running"
                    elif status_now == "deploying":
                        instance.status = "deploying"  # 仍在等
                    db.commit()
            finally:
                db.close()
            if ok:
                logger.info(f"NPU service #{instance_id} is healthy")
                return
            time.sleep(10)
        # 超时
        db = SessionLocal()
        try:
            instance = db.query(NpuServiceInstance).filter(
                NpuServiceInstance.id == instance_id).first()
            if instance and instance.status == "deploying":
                instance.status = "failed"
                instance.last_health_ok = False
                db.commit()
                logger.warning(f"NPU service #{instance_id} health check timed out")
        finally:
            db.close()
        with _health_lock:
            _health_threads.pop(instance_id, None)

    t = threading.Thread(target=_wait, daemon=True, name=f"npu-health-{instance_id}")
    t.start()


def _cancel_health_wait(instance_id: int) -> None:
    with _health_lock:
        ev = _health_threads.pop(instance_id, None)
    if ev:
        ev.set()
