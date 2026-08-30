"""benchmark 压测编排

在 NPU 机器上起临时 bench 容器（与被测服务同镜像，--net=host）执行
`vllm bench serve`（新版 CLI，benchmark_serving.py 已废弃），自带
--ready-check-timeout-sec 等服务就绪；结果 JSON 经 SSH 取回解析落库。
"""
import json
import logging
import shlex
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import Config
from app.database import SessionLocal
from app.models import NpuBenchmarkRun, NpuJob, NpuMachine, NpuServiceInstance
from app.services.npu import ssh
from app.services.npu.profiles import build_docker_run

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _abs_workdir(machine: NpuMachine) -> str:
    """机器上的绝对工作目录（~ 展开）"""
    workdir = machine.workdir or "~/npu-workspace"
    if workdir.startswith("~/"):
        code, out, _ = ssh.run_command(machine.to_ssh_params(), "echo $HOME", timeout=20)
        workdir = out.strip() + workdir[1:]
    return workdir


def _pick(d: dict, *keys, default=None):
    """从结果 JSON 里按优先级取第一个非空值（版本间字段名有差异）"""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def _parse_result(raw: dict) -> Dict[str, Any]:
    """解析 vllm bench serve --save-result 输出的指标"""
    successful = raw.get("successful_requests")
    total = raw.get("num_prompts")
    return {
        "total_throughput": _pick(raw, "request_throughput", "total_token_throughput"),
        "output_throughput": _pick(raw, "output_throughput", "generate_throughput"),
        "ttft_p50": _pick(raw, "median_ttft_ms", "mean_ttft_ms", "p50_ttft_ms"),
        "ttft_p99": _pick(raw, "p99_ttft_ms"),
        "tpot_p50": _pick(raw, "median_tpot_ms", "mean_tpot_ms"),
        "tpot_p99": _pick(raw, "p99_tpot_ms"),
        "itl_p50": _pick(raw, "median_itl_ms", "mean_itl_ms"),
        "itl_p99": _pick(raw, "p99_itl_ms"),
        "e2el_p99": _pick(raw, "p99_e2el_ms", "p99_e2eL_ms"),
        "success_rate": (round(successful * 100.0 / total, 2)
                         if successful is not None and total else None),
        "raw": raw,
    }


def start_benchmark(machine: NpuMachine, service: NpuServiceInstance, params: dict) -> Dict[str, Any]:
    """发起压测：建 run 记录 → 起临时 bench 容器（oneshot job）→ 后台线程收集结果"""
    dataset_name = params.get("dataset_name") or "random"
    if dataset_name not in ("random", "sharegpt"):
        raise ValueError("dataset_name 仅支持 random/sharegpt")
    dataset_path = (params.get("dataset_path") or "").strip()
    if dataset_name == "sharegpt" and not dataset_path:
        raise ValueError("sharegpt 数据集需要提供机器上的 dataset_path")

    import requests as _requests
    try:
        resp = _requests.get(f"{service.health_url}/health", timeout=10)
        if resp.status_code != 200:
            raise ValueError("服务健康检查未通过，无法压测")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"服务不可达: {e}")

    db = SessionLocal()
    try:
        run = NpuBenchmarkRun(
            machine_id=machine.id,
            service_id=service.id,
            model=service.model_name or "",
            endpoint=params.get("endpoint") or "/v1/completions",
            dataset_name=dataset_name,
            dataset_path=dataset_path or None,
            num_prompts=int(params.get("num_prompts") or 10),
            request_rate=params.get("request_rate"),
            max_concurrency=params.get("max_concurrency"),
            params=json.dumps({k: v for k, v in params.items()
                               if k not in ("machine_id", "service_id")}) if params else None,
            status="running",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    # 结果目录（绝对路径，同路径挂载进 bench 容器）
    try:
        base = _abs_workdir(machine)
    except Exception as e:
        _mark_failed(run_id, f"机器不可达: {e}")
        raise ValueError(f"机器不可达: {e}")
    result_dir = f"{base}/benchmarks"

    serve_port = 8000
    for p in (json.loads(service.ports) if service.ports else []):
        _, _, cp = p.partition(":")
        if cp:
            serve_port = int(cp)
            break

    bench_args = [
        "vllm", "bench", "serve",
        "--backend", "vllm",
        "--model", service.model_name or "",
        "--host", "127.0.0.1",
        "--port", str(serve_port),
        "--endpoint", params.get("endpoint") or "/v1/completions",
        "--dataset-name", dataset_name,
    ]
    if dataset_path:
        bench_args += ["--dataset-path", dataset_path]
    bench_args += ["--num-prompts", str(int(params.get("num_prompts") or 10))]
    if params.get("request_rate"):
        bench_args += ["--request-rate", str(params["request_rate"])]
    if params.get("max_concurrency"):
        bench_args += ["--max-concurrency", str(params["max_concurrency"])]
    bench_args += [
        "--percentile-metrics", "ttft,tpot,itl,e2el",
        "--save-result",
        "--result-dir", result_dir,
        "--result-filename", f"bench_{run_id}.json",
        "--ready-check-timeout-sec", "600",
    ]
    bench_cmd = " ".join(shlex.quote(a) for a in bench_args)

    mounts = [result_dir]
    if dataset_path:
        mounts.append(dataset_path)

    spec = {
        "mode": "oneshot",
        "image": service.image,
        "device_ids": [],  # bench 客户端不占 NPU
        "mounts": mounts,
        "env": {},
        "network": "host",  # 容器内 127.0.0.1 即机器网络栈
        "ports": [],
        "command": f"mkdir -p {shlex.quote(result_dir)} && {bench_cmd}",
        "shm_size": "",
    }

    from app.services.npu import jobs as job_service
    job = job_service.create_and_submit(
        machine,
        job_type="benchmark",
        mode="oneshot",
        name=f"bench-{run_id}",
        spec=spec,
        timeout=int(params.get("timeout") or Config.NPU_JOB_TIMEOUT),
        source="ui",
        benchmark_id=run_id,
    )

    db = SessionLocal()
    try:
        run = db.query(NpuBenchmarkRun).filter(NpuBenchmarkRun.id == run_id).first()
        if run:
            run.job_id = job.id
            run.result_file = f"{result_dir}/bench_{run_id}.json"
            db.commit()
    finally:
        db.close()

    # 后台线程等 job 结束后取回结果 JSON 解析落库
    threading.Thread(target=_collect_result, args=(run_id, job.id, machine.id),
                     daemon=True, name=f"npu-bench-{run_id}").start()

    return {"benchmark_id": run_id, "job_id": job.id}


def _mark_failed(run_id: int, message: str) -> None:
    db = SessionLocal()
    try:
        run = db.query(NpuBenchmarkRun).filter(NpuBenchmarkRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.error_message = message[:500]
            db.commit()
    finally:
        db.close()


def _collect_result(run_id: int, job_id: int, machine_id: int) -> None:
    """轮询 job 结束 → SSH cat 结果 JSON → 解析指标落库"""
    while True:
        time.sleep(5)
        db = SessionLocal()
        try:
            job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
            if job is None or job.status in ("completed", "failed", "cancelled"):
                job_status = job.status if job else "unknown"
                break
        finally:
            db.close()

    db = SessionLocal()
    try:
        run = db.query(NpuBenchmarkRun).filter(NpuBenchmarkRun.id == run_id).first()
        result_file = run.result_file if run else None
        job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
        job_exit = job.exit_code if job else None
    finally:
        db.close()

    if job_status != "completed" or job_exit != 0:
        _mark_failed(run_id, f"压测任务未成功结束（job {job_status}, exit {job_exit}）")
        return

    db = SessionLocal()
    try:
        machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
        ssh_params = machine.to_ssh_params() if machine else None
    finally:
        db.close()
    if not ssh_params or not result_file:
        _mark_failed(run_id, "缺少机器或结果文件路径")
        return

    try:
        code, out, err = ssh.run_command(ssh_params, f"cat {shlex.quote(result_file)}", timeout=60)
        if code != 0:
            raise RuntimeError(f"读取结果失败: {err[:200]}")
        raw = json.loads(out)
    except Exception as e:
        _mark_failed(run_id, f"结果解析失败: {e}")
        return

    parsed = _parse_result(raw)
    raw_metrics = parsed.pop("raw")
    db = SessionLocal()
    try:
        run = db.query(NpuBenchmarkRun).filter(NpuBenchmarkRun.id == run_id).first()
        if run:
            for k, v in parsed.items():
                setattr(run, k, v)
            run.raw_metrics = json.dumps(raw_metrics, ensure_ascii=False)
            run.status = "completed"
            db.commit()
            logger.info(f"Benchmark #{run_id} completed")
    finally:
        db.close()
