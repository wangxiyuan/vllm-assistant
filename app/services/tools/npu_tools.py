"""NPU 运维工具（npu category）

让 AI agent 以对话方式操作 NPU 机器：查机器/模型/服务、执行命令、
部署服务、跑 benchmark、采集 profile、跑用例。

安全约定：
- run_npu_command 必须显式传 confirm=true 才会执行（与 write 类删除工具
  同一守卫模式，system prompt 要求 AI 先向用户复述命令并征得同意）。
- 长任务（命令执行/部署/压测）立即返回 job/benchmark id，AI 用 get_npu_job /
  get_npu_benchmark_result 轮询，不要同步等待。
"""
import logging
from typing import Optional

from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)


def _db_run(fn, *args, **kwargs) -> dict:
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        return fn(db, *args, **kwargs)
    except Exception as e:
        logger.exception("npu tool failed")
        return {"error": str(e)}
    finally:
        db.close()


def _get_machine(db, machine_id):
    from app.models import NpuMachine
    return db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()


def _get_service(db, service_id):
    from app.models import NpuServiceInstance
    return db.query(NpuServiceInstance).filter(NpuServiceInstance.id == service_id).first()


# ----------------------------------------------------------------------
# 查询类
# ----------------------------------------------------------------------

def handle_list_npu_machines(args: dict) -> dict:
    from app.models import NpuMachine
    def _q(db):
        rows = db.query(NpuMachine).filter(NpuMachine.enabled == True).all()  # noqa: E712
        return [{"id": m.id, "name": m.name, "host": m.host, "status": m.status,
                 "machine_type": m.machine_type, "npu_count": m.npu_count,
                 "npu_chip": m.npu_chip, "last_check_at": str(m.last_check_at or "")}
                for m in rows]
    return {"machines": _db_run(_q)}


def handle_get_npu_machine_detail(args: dict) -> dict:
    machine_id = int(args.get("machine_id") or 0)
    def _q(db):
        m = _get_machine(db, machine_id)
        if m is None:
            return {"error": "机器不存在"}
        d = m.to_dict()
        d["ssh_cmd"] = f"ssh -p {m.port or 22} {m.username}@{m.host}"
        return d
    return _db_run(_q)


def handle_list_npu_models(args: dict) -> dict:
    machine_id = int(args.get("machine_id") or 0)
    def _q(db):
        from app.models import NpuModelDir
        rows = db.query(NpuModelDir).filter(NpuModelDir.machine_id == machine_id).all()
        return {"models": [{"id": r.id, "path": r.path, "note": r.note} for r in rows]}
    return _db_run(_q)


def handle_list_npu_services(args: dict) -> dict:
    from app.models import NpuServiceInstance
    def _q(db):
        rows = db.query(NpuServiceInstance).order_by(NpuServiceInstance.id).all()
        return {"services": [{"id": s.id, "name": s.name, "model_name": s.model_name,
                              "status": s.status, "image": s.image,
                              "debug_mode": bool(s.debug_mode),
                              "profiling_enabled": bool(s.profiling_enabled),
                              "health_ok": s.last_health_ok}
                             for s in rows]}
    return _db_run(_q)


def handle_get_npu_job(args: dict) -> dict:
    job_id = int(args.get("job_id") or 0)
    from app.database import SessionLocal
    from app.models import NpuJob, NpuMachine
    from app.services.npu.jobs import get_job_log
    db = SessionLocal()
    try:
        job = db.query(NpuJob).filter(NpuJob.id == job_id).first()
        if job is None:
            return {"error": "任务不存在"}
        machine = db.query(NpuMachine).filter(NpuMachine.id == job.machine_id).first()
        lg = get_job_log(job, machine.to_ssh_params() if machine else {}, offset=0, tail_lines=60)
        return {"job_id": job.id, "type": job.type, "mode": job.mode,
                "status": job.status, "exit_code": job.exit_code,
                "error": job.error_message,
                "log_tail": lg.get("content", "")[-3000:],
                "hint": ("任务仍在运行时稍后再次调用本工具轮询" if job.status in ("pending", "running") else "任务已结束")}
    finally:
        db.close()


# ----------------------------------------------------------------------
# 操作类
# ----------------------------------------------------------------------

def handle_run_npu_command(args: dict) -> dict:
    machine_id = int(args.get("machine_id") or 0)
    command = (args.get("command") or "").strip()
    confirm = args.get("confirm") is True
    timeout_minutes = min(int(args.get("timeout_minutes") or 5), 30)
    if not command:
        return {"error": "command 不能为空"}
    if not confirm:
        return {"need_confirm": True,
                "message": f"将在机器 #{machine_id} 上执行：{command}。请向用户复述并征得同意后，携带 confirm=true 再次调用。"}
    from app.database import SessionLocal
    from app.services.npu import jobs as job_service
    db = SessionLocal()
    try:
        machine = _get_machine(db, machine_id)
        if machine is None:
            return {"error": "机器不存在"}
        job = job_service.create_and_submit(
            machine, job_type="container", mode="oneshot", name=f"agent-cmd",
            spec={"mode": "oneshot", "command": command, "network": "host"},
            timeout=timeout_minutes * 60, source="agent")
    finally:
        db.close()
    return {"job_id": job.id, "status": "pending",
            "hint": "用 get_npu_job 轮询状态与日志（一般每 10-20 秒一次）"}


def handle_deploy_npu_service(args: dict) -> dict:
    machine_id = int(args.get("machine_id") or 0)
    from app.database import SessionLocal
    from app.services.npu import deploy as deploy_svc
    db = SessionLocal()
    try:
        machine = _get_machine(db, machine_id)
        if machine is None:
            return {"error": "机器不存在"}
        params = {
            "name": args.get("name"),
            "model_dir": args.get("model_dir"),
            "model_name": args.get("model_name") or "",
            "image": args.get("image") or "",
            "port": args.get("port") or 8000,
            "tp": args.get("tp") or 1,
            "device_ids": args.get("device_ids"),
            "serve_args": args.get("serve_args") or "",
            "debug_mode": bool(args.get("debug_mode")),
            "profiling_enabled": bool(args.get("profiling_enabled")),
        }
        try:
            result = deploy_svc.deploy_service(machine, params)
        except ValueError as e:
            return {"error": str(e)}
    finally:
        db.close()
    return {**result, "hint": "部署后自动健康检查，稍后用 list_npu_services 查看状态"}


def handle_stop_npu_service(args: dict) -> dict:
    instance_id = int(args.get("instance_id") or 0)
    from app.services.npu import deploy as deploy_svc
    return deploy_svc.stop_service(instance_id)


def handle_start_npu_benchmark(args: dict) -> dict:
    service_id = int(args.get("service_id") or 0)
    from app.database import SessionLocal
    from app.models import NpuMachine
    from app.services.npu import benchmark as bench_svc
    db = SessionLocal()
    try:
        service = _get_service(db, service_id)
        if service is None:
            return {"error": "服务实例不存在"}
        machine = db.query(NpuMachine).filter(NpuMachine.id == service.machine_id).first()
        if machine is None:
            return {"error": "机器不存在"}
        try:
            result = bench_svc.start_benchmark(machine, service, {
                "dataset_name": args.get("dataset_name") or "random",
                "dataset_path": args.get("dataset_path") or "",
                "num_prompts": args.get("num_prompts") or 10,
                "request_rate": args.get("request_rate"),
                "max_concurrency": args.get("max_concurrency"),
                "endpoint": args.get("endpoint") or "/v1/completions",
            })
        except ValueError as e:
            return {"error": str(e)}
    finally:
        db.close()
    return {**result, "hint": "压测进行中，用 get_npu_benchmark_result 轮询结果"}


def handle_get_npu_benchmark_result(args: dict) -> dict:
    run_id = int(args.get("benchmark_id") or 0)
    def _q(db):
        from app.models import NpuBenchmarkRun
        run = db.query(NpuBenchmarkRun).filter(NpuBenchmarkRun.id == run_id).first()
        if run is None:
            return {"error": "压测记录不存在"}
        d = run.to_dict()
        if d["status"] == "running":
            d["hint"] = "仍在压测，稍后再次调用轮询"
        return d
    return _db_run(_q)


def handle_start_npu_profile(args: dict) -> dict:
    instance_id = int(args.get("instance_id") or 0)
    from app.services.npu import profiler
    try:
        result = profiler.start_collection(instance_id, notes=args.get("notes") or "")
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}
    return {**result, "hint": "采集进行中，让用户产生一些请求流量后调 stop_npu_profile"}


def handle_stop_npu_profile(args: dict) -> dict:
    session_id = int(args.get("session_id") or 0)
    from app.services.npu import profiler
    try:
        return profiler.stop_collection(session_id)
    except ValueError as e:
        return {"error": str(e)}


def handle_run_npu_test(args: dict) -> dict:
    case_id = int(args.get("case_id") or 0)
    from app.services.npu import tests as test_svc
    try:
        result = test_svc.run_test(case_id, machine_id=args.get("machine_id"),
                                   service_id=args.get("service_id"))
    except ValueError as e:
        return {"error": str(e)}
    return {**result, "hint": "用例异步执行，稍后查询 /api/npu/test-cases/runs 或让用户在页面查看"}


# ----------------------------------------------------------------------
# Schema 与注册
# ----------------------------------------------------------------------

LIST_MACHINES = {
    "type": "function", "function": {
        "name": "list_npu_machines",
        "description": "列出所有已纳管的 NPU 机器及状态（在线/离线、机型、卡数）",
        "parameters": {"type": "object", "properties": {}},
    }}

GET_MACHINE_DETAIL = {
    "type": "function", "function": {
        "name": "get_npu_machine_detail",
        "description": "查看一台 NPU 机器的详情（NPU 状态、驱动版本、标签等）",
        "parameters": {"type": "object", "properties": {
            "machine_id": {"type": "integer", "description": "机器 ID"},
        }, "required": ["machine_id"]},
    }}

LIST_MODELS = {
    "type": "function", "function": {
        "name": "list_npu_models",
        "description": "列出一台机器上可用的模型权重目录（部署服务时选择用）",
        "parameters": {"type": "object", "properties": {
            "machine_id": {"type": "integer", "description": "机器 ID"},
        }, "required": ["machine_id"]},
    }}

LIST_SERVICES = {
    "type": "function", "function": {
        "name": "list_npu_services",
        "description": "列出所有 vLLM 服务实例及状态",
        "parameters": {"type": "object", "properties": {}},
    }}

GET_JOB = {
    "type": "function", "function": {
        "name": "get_npu_job",
        "description": "查询远程任务状态与日志尾部（执行命令/部署等长任务用本工具轮询）",
        "parameters": {"type": "object", "properties": {
            "job_id": {"type": "integer", "description": "任务 ID"},
        }, "required": ["job_id"]},
    }}

RUN_COMMAND = {
    "type": "function", "function": {
        "name": "run_npu_command",
        "description": "在 NPU 机器上执行任意 shell 命令（一次性容器或宿主机）。高危操作，必须先向用户复述命令并征得同意后再带 confirm=true 调用。",
        "parameters": {"type": "object", "properties": {
            "machine_id": {"type": "integer", "description": "机器 ID"},
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "confirm": {"type": "boolean", "description": "必须为 true 才执行"},
            "timeout_minutes": {"type": "integer", "description": "超时分钟数，默认 5，最大 30"},
        }, "required": ["machine_id", "command"]},
    }}

DEPLOY_SERVICE = {
    "type": "function", "function": {
        "name": "deploy_npu_service",
        "description": "在 NPU 机器上以 docker 容器部署 vLLM 模型服务（自动机型模板/健康检查）。可先 list_npu_models 查可用模型目录。",
        "parameters": {"type": "object", "properties": {
            "machine_id": {"type": "integer", "description": "机器 ID"},
            "name": {"type": "string", "description": "实例名（唯一，如 qwen32b-a2）"},
            "model_dir": {"type": "string", "description": "机器上模型权重目录绝对路径"},
            "model_name": {"type": "string", "description": "对外模型名（served-model-name），空 = 实例名"},
            "port": {"type": "integer", "description": "服务端口，默认 8000"},
            "tp": {"type": "integer", "description": "tensor parallel 卡数，默认 1"},
            "device_ids": {"type": "array", "items": {"type": "integer"}, "description": "使用的 NPU 卡号列表，缺省 = 全部卡"},
            "serve_args": {"type": "string", "description": "vllm serve 额外参数"},
            "debug_mode": {"type": "boolean", "description": "是否注入 debugpy 调试"},
            "profiling_enabled": {"type": "boolean", "description": "是否开启 Profiling 采集支持"},
        }, "required": ["machine_id", "name", "model_dir"]},
    }}

STOP_SERVICE = {
    "type": "function", "function": {
        "name": "stop_npu_service",
        "description": "停止一个 vLLM 服务实例（docker rm -f）",
        "parameters": {"type": "object", "properties": {
            "instance_id": {"type": "integer", "description": "服务实例 ID"},
        }, "required": ["instance_id"]},
    }}

START_BENCHMARK = {
    "type": "function", "function": {
        "name": "start_npu_benchmark",
        "description": "对一个运行中的 vLLM 服务发起性能压测（vllm bench serve，结果自动解析落库）",
        "parameters": {"type": "object", "properties": {
            "service_id": {"type": "integer", "description": "服务实例 ID"},
            "dataset_name": {"type": "string", "description": "random 或 sharegpt，默认 random"},
            "dataset_path": {"type": "string", "description": "sharegpt 数据集在机器上的路径（json 文件）"},
            "num_prompts": {"type": "integer", "description": "请求数，默认 10"},
            "request_rate": {"type": "number", "description": "请求速率 req/s，缺省 = 全并发"},
            "max_concurrency": {"type": "integer", "description": "最大并发数"},
            "endpoint": {"type": "string", "description": "默认 /v1/completions；chat 模型可用 /v1/chat/completions"},
        }, "required": ["service_id"]},
    }}

GET_BENCHMARK = {
    "type": "function", "function": {
        "name": "get_npu_benchmark_result",
        "description": "查询压测结果（吞吐/TTFT/TPOT 等指标）",
        "parameters": {"type": "object", "properties": {
            "benchmark_id": {"type": "integer", "description": "压测记录 ID"},
        }, "required": ["benchmark_id"]},
    }}

START_PROFILE = {
    "type": "function", "function": {
        "name": "start_npu_profile",
        "description": "对一个以 Profiling 模式部署的运行中服务开始性能采集（torch profiler）",
        "parameters": {"type": "object", "properties": {
            "instance_id": {"type": "integer", "description": "服务实例 ID"},
            "notes": {"type": "string", "description": "本次采集备注"},
        }, "required": ["instance_id"]},
    }}

STOP_PROFILE = {
    "type": "function", "function": {
        "name": "stop_npu_profile",
        "description": "停止 Profiling 采集并生成文件清单",
        "parameters": {"type": "object", "properties": {
            "session_id": {"type": "integer", "description": "采集会话 ID"},
        }, "required": ["session_id"]},
    }}

RUN_TEST = {
    "type": "function", "function": {
        "name": "run_npu_test",
        "description": "运行一个预定义测试用例（容器命令类或 OpenAI 接口探活类）",
        "parameters": {"type": "object", "properties": {
            "case_id": {"type": "integer", "description": "用例 ID"},
            "machine_id": {"type": "integer", "description": "container_cmd 类需要"},
            "service_id": {"type": "integer", "description": "openai_chat 类需要"},
        }, "required": ["case_id"]},
    }}


register_tool("list_npu_machines", LIST_MACHINES, handle_list_npu_machines)
register_tool("get_npu_machine_detail", GET_MACHINE_DETAIL, handle_get_npu_machine_detail)
register_tool("list_npu_models", LIST_MODELS, handle_list_npu_models)
register_tool("list_npu_services", LIST_SERVICES, handle_list_npu_services)
register_tool("get_npu_job", GET_JOB, handle_get_npu_job)
register_tool("run_npu_command", RUN_COMMAND, handle_run_npu_command)
register_tool("deploy_npu_service", DEPLOY_SERVICE, handle_deploy_npu_service)
register_tool("stop_npu_service", STOP_SERVICE, handle_stop_npu_service)
register_tool("start_npu_benchmark", START_BENCHMARK, handle_start_npu_benchmark)
register_tool("get_npu_benchmark_result", GET_BENCHMARK, handle_get_npu_benchmark_result)
register_tool("start_npu_profile", START_PROFILE, handle_start_npu_profile)
register_tool("stop_npu_profile", STOP_PROFILE, handle_stop_npu_profile)
register_tool("run_npu_test", RUN_TEST, handle_run_npu_test)
