"""NPU 远程任务执行器

所有任务统一通过 docker 容器在 NPU 机器上执行：
- oneshot：docker run --rm 跑完退出，日志流式写文件，exit_code 落库
- persistent：docker run -d 常驻容器（bash 常住开发容器），running 即长期状态，
  日志经 `docker logs` 动态拉取，页面可停止（docker stop/rm）

日志只落文件系统（data/npu_jobs/{id}.log），DB 仅存路径与大小。
执行走独立线程池（NPU_JOB_WORKERS），不占用 FastAPI 默认线程池与
知识库构建的 _bg_executor。
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.config import Config
from app.database import SessionLocal
from app.models import NpuJob, NpuMachine
from app.services.npu import ssh
from app.services.npu.profiles import build_docker_run
from app.services.npu.ssh import SshCommandTimeout

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=Config.NPU_JOB_WORKERS, thread_name_prefix="npu-job")
_log_dir = Config.BASE_DIR / "data" / "npu_jobs"


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log_path(job_id: int) -> Path:
    _log_dir.mkdir(parents=True, exist_ok=True)
    return _log_dir / f"{job_id}.log"


def create_and_submit(
    machine: NpuMachine,
    *,
    job_type: str = "container",
    mode: str = "oneshot",
    name: str = "",
    spec: dict,
    timeout: Optional[int] = None,
    source: str = "ui",
    service_id: Optional[int] = None,
    test_case_id: Optional[int] = None,
    benchmark_id: Optional[int] = None,
    on_submitted: Optional[Callable[[NpuJob], None]] = None,
) -> NpuJob:
    """创建任务记录并提交到执行线程池，返回 job（pending 状态）

    spec 为容器规格（image/device_ids/mounts/env/network/ports/command/
    shm_size/extra_devices），docker_cmd 由 build_docker_run 生成后写入 payload。
    """
    if mode not in ("oneshot", "persistent"):
        raise ValueError("mode must be oneshot/persistent")

    db = SessionLocal()
    try:
        job = NpuJob(
            machine_id=machine.id,
            type=job_type,
            mode=mode,
            name=name,
            status="pending",
            source=source,
            service_id=service_id,
            test_case_id=test_case_id,
            benchmark_id=benchmark_id,
            created_at=_now(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        container_name = f"va-{job_type}-{job.id}"
        spec = dict(spec or {})
        spec["container_name"] = container_name
        docker_cmd = build_docker_run(machine.machine_type, spec)

        job.container_name = container_name
        job.payload = json.dumps(_payload_with_cmd(spec, docker_cmd), ensure_ascii=False)
        job.log_file = str(_log_path(job.id))
        db.commit()
        job_id = job.id
    finally:
        db.close()

    _executor.submit(_execute_job, job_id, timeout)
    logger.info(f"NPU job submitted: #{job_id} {job_type}/{mode} on {machine.name}")
    if on_submitted:
        on_submitted(job)
    return job


def _payload_with_cmd(spec: dict, docker_cmd: str) -> dict:
    # spec 可能含不可 JSON 序列化对象，保险起见走 round-trip
    try:
        spec = json.loads(json.dumps(spec, ensure_ascii=False))
    except Exception:
        spec = {}
    return {**spec, "docker_cmd": docker_cmd}


def _execute_job(job_id: int, timeout: Optional[int]) -> None:
    """执行线程主体：读任务与机器参数（session 即取即关），执行并落库"""
    try:
        _run_job(job_id, timeout)
    except Exception:
        # 线程池 submit 的 Future 无人读取，异常必须在这里兜底落库，
        # 否则任务会永远停在 running
        logger.exception(f"NPU job #{job_id} execution crashed")
        db = SessionLocal()
        try:
            j = db.query(NpuJob).filter(NpuJob.id == job_id).first()
            if j and j.status in ("pending", "running"):
                j.status = "failed"
                j.error_message = "任务执行内部异常，详见服务日志"
                j.finished_at = _now()
                db.commit()
        finally:
            db.close()


def _run_job(job_id: int, timeout: Optional[int]) -> None:
    db = SessionLocal()
    try:
        job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
        if job is None:
            return
        machine = db.query(NpuMachine).filter(NpuMachine.id == job.machine_id).first()
        if machine is None:
            job.status = "failed"
            job.error_message = "机器不存在"
            db.commit()
            return
        payload = json.loads(job.payload) if job.payload else {}
        # session 关闭前取出全部字段（expire_on_commit=True，detached 后访问会抛错）
        docker_cmd = payload.get("docker_cmd", "")
        job_mode = job.mode
        log_file = job.log_file
        job.status = "running"
        job.started_at = _now()
        db.commit()
        ssh_params = machine.to_ssh_params()
    finally:
        db.close()

    log_path = Path(log_file or _log_path(job_id))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_log(chunk: str) -> None:
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write(chunk)

    def on_output(tag: str, data: str) -> None:
        _write_log(data)

    _write_log(f"$ {docker_cmd}\n")

    effective_timeout = timeout or Config.NPU_JOB_TIMEOUT
    try:
        code, out, err = ssh.run_command(ssh_params, docker_cmd,
                                         timeout=effective_timeout, on_output=on_output)
    except SshCommandTimeout:
        _write_log(f"\n[超时] 任务超过 {effective_timeout}s 被终止\n")
        db = SessionLocal()
        try:
            j = db.query(NpuJob).filter(NpuJob.id == job_id).first()
            if j:
                j.status = "failed"
                j.error_message = f"任务超时（{effective_timeout}s）"
                j.finished_at = _now()
                j.log_size = log_path.stat().st_size if log_path.exists() else 0
                db.commit()
        finally:
            db.close()
        return
    except Exception as e:
        _write_log(f"\n[异常] {e}\n")
        db = SessionLocal()
        try:
            j = db.query(NpuJob).filter(NpuJob.id == job_id).first()
            if j:
                j.status = "failed"
                j.error_message = str(e)[:500]
                j.finished_at = _now()
                j.log_size = log_path.stat().st_size if log_path.exists() else 0
                db.commit()
        finally:
            db.close()
        return

    db = SessionLocal()
    try:
        j = db.query(NpuJob).filter(NpuJob.id == job_id).first()
        if j is None:
            return
        j.exit_code = code
        if job_mode == "persistent":
            # docker run -d 立即返回容器 id，running 即长期状态
            j.status = "running" if code == 0 else "failed"
            if code != 0:
                j.error_message = (err or out or "")[:500]
            else:
                j.container_id = (out or "").strip()[-64:] or None
        else:
            j.status = "completed" if code == 0 else "failed"
            if code != 0:
                j.error_message = (err or out or f"exit code {code}")[:500]
            j.finished_at = _now()
        j.log_size = log_path.stat().st_size if log_path.exists() else 0
        db.commit()
    finally:
        db.close()
    logger.info(f"NPU job #{job_id} finished: exit={code}")


def stop_job(job_id: int) -> dict:
    """停止任务：persistent=docker stop/rm；oneshot running=docker rm -f"""
    db = SessionLocal()
    try:
        job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
        if job is None:
            raise ValueError("任务不存在")
        if job.status not in ("pending", "running"):
            return {"ok": False, "message": f"任务已结束（{job.status}）"}
        machine = db.query(NpuMachine).filter(NpuMachine.id == job.machine_id).first()
        container = job.container_name
    finally:
        db.close()
    if machine is None or not container:
        return {"ok": False, "message": "缺少机器或容器信息"}

    try:
        ssh.run_command(machine.to_ssh_params(),
                        f"docker rm -f {container} 2>/dev/null; true", timeout=120)
    except Exception as e:
        logger.warning(f"stop job {job_id}: remote rm failed: {e}")

    db = SessionLocal()
    try:
        j = db.query(NpuJob).filter(NpuJob.id == job_id).first()
        if j and j.status in ("pending", "running"):
            j.status = "cancelled"
            j.finished_at = _now()
            p = Path(j.log_file) if j.log_file else None
            if p and p.exists():
                j.log_size = p.stat().st_size
            db.commit()
    finally:
        db.close()
    return {"ok": True}


def get_job_log(job: NpuJob, machine_params: dict, offset: int = 0,
                tail_lines: int = 200) -> dict:
    """读取任务日志。

    persistent 运行中：经 `docker logs --tail` 拉取（tail 模式，全量替换）；
    其余：按文件 offset 增量读取。
    """
    if job.mode == "persistent" and job.container_name and job.status == "running":
        try:
            code, out, err = ssh.run_command(
                machine_params,
                f"docker logs --tail {int(tail_lines)} {job.container_name} 2>&1",
                timeout=60)
            return {"mode": "tail", "content": out or err, "status": job.status,
                    "log_size": 0, "offset": 0}
        except Exception as e:
            return {"mode": "tail", "content": f"[日志拉取失败] {e}", "status": job.status,
                    "log_size": 0, "offset": 0}

    p = Path(job.log_file) if job.log_file else None
    size = p.stat().st_size if p and p.exists() else 0
    if offset >= size:
        return {"mode": "incremental", "content": "", "offset": offset, "size": size,
                "status": job.status}
    with open(p, "rb") as f:
        f.seek(offset)
        data = f.read()
    return {"mode": "incremental", "content": data.decode("utf-8", errors="replace"),
            "offset": offset + len(data), "size": size, "status": job.status}


def reconcile_on_startup() -> None:
    """服务重启后对账：oneshot 任务的重启前 running/pending 实际已中断，标 failed。

    persistent 容器仍在机器上运行（docker 层持久），DB 中 running 状态依旧成立，
    无需处理。
    """
    db = SessionLocal()
    try:
        rows = db.query(NpuJob).filter(
            NpuJob.status.in_(["pending", "running"]),
            NpuJob.mode == "oneshot").all()
        for job in rows:
            job.status = "failed"
            job.error_message = "管理服务重启，任务中断"
            job.finished_at = _now()
        if rows:
            db.commit()
            logger.info(f"Reconciled {len(rows)} interrupted NPU jobs after restart")
    finally:
        db.close()
