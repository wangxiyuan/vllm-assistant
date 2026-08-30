"""测试用例执行

- container_cmd：机器上起一次性容器跑 shell 命令（自定义镜像可选），
  走任务体系执行，后台线程等待结束后按 exit_code 判定 passed/failed
- openai_chat：管理端直接向服务实例发 OpenAI 兼容请求，
  断言 HTTP 200 且（可选）输出包含期望关键字
"""
import json
import logging
import shlex
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from app.config import Config
from app.database import SessionLocal
from app.models import NpuJob, NpuMachine, NpuServiceInstance, NpuTestCase, NpuTestRun
from app.services.npu.profiles import default_image

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def run_test(case_id: int, machine_id: Optional[int] = None,
             service_id: Optional[int] = None) -> Dict[str, Any]:
    """运行一个用例（异步返回 run_id；结果落 NpuTestRun）"""
    db = SessionLocal()
    try:
        case = db.query(NpuTestCase).filter(NpuTestCase.id == case_id).first()
        if case is None:
            raise ValueError("用例不存在")
        if not case.enabled:
            raise ValueError("用例已禁用")
        payload = json.loads(case.payload) if case.payload else {}
        kind = case.kind
        timeout_s = case.timeout_seconds or 600
    finally:
        db.close()

    if kind == "container_cmd":
        if machine_id is None:
            raise ValueError("container_cmd 用例需要指定 machine_id")
        run_id = _run_container_cmd(case_id, machine_id, payload, timeout_s)
    elif kind == "openai_chat":
        if service_id is None:
            raise ValueError("openai_chat 用例需要指定 service_id")
        run_id = _run_openai_chat(case_id, service_id, payload, timeout_s)
    else:
        raise ValueError(f"未知用例类型: {kind}")
    return {"run_id": run_id}


def _create_run(case_id: int, machine_id: Optional[int],
                service_id: Optional[int]) -> int:
    db = SessionLocal()
    try:
        run = NpuTestRun(case_id=case_id, machine_id=machine_id,
                         service_id=service_id, status="running")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def _finish_run(run_id: int, status: str, duration_ms: float,
                output_summary: str, job_id: Optional[int] = None) -> None:
    db = SessionLocal()
    try:
        run = db.query(NpuTestRun).filter(NpuTestRun.id == run_id).first()
        if run:
            run.status = status
            run.duration_ms = duration_ms
            run.output_summary = output_summary[:4000]
            if job_id:
                run.job_id = job_id
            db.commit()
    finally:
        db.close()


def _run_container_cmd(case_id: int, machine_id: int, payload: dict,
                       timeout_s: int) -> int:
    run_id = _create_run(case_id, machine_id, None)

    def _worker():
        t0 = time.time()
        db = SessionLocal()
        try:
            machine = db.query(NpuMachine).filter(NpuMachine.id == machine_id).first()
            ssh_params = machine.to_ssh_params() if machine else None
            machine_type = machine.machine_type if machine else "other"
        finally:
            db.close()
        if not ssh_params:
            _finish_run(run_id, "error", 0, "机器不存在")
            return

        command = payload.get("command") or "echo 'no command'"
        image = payload.get("image") or default_image(machine_type)
        mounts = payload.get("mounts") or []
        env = payload.get("env") or {}
        device_ids = payload.get("device_ids")

        from app.services.npu import jobs as job_service
        try:
            # machine 为 detached 对象但属性已加载，create_and_submit 只读 id/机型
            job = job_service.create_and_submit(
                machine,
                job_type="test",
                mode="oneshot",
                name=f"test-case-{case_id}",
                spec={"mode": "oneshot", "image": image, "device_ids": device_ids,
                      "mounts": mounts, "env": env, "network": "host", "ports": [],
                      "command": command, "shm_size": ""},
                timeout=timeout_s,
                source="ui",
                test_case_id=case_id,
            )
        except Exception as e:
            _finish_run(run_id, "error", (time.time() - t0) * 1000, str(e))
            return

        # 轮询任务结束
        while time.time() - t0 < timeout_s + 30:
            time.sleep(3)
            db = SessionLocal()
            try:
                j = db.query(NpuJob).filter(NpuJob.id == job.id).first()
                st = (j.status, j.exit_code) if j else (None, None)
            finally:
                db.close()
            if st[0] in ("completed", "failed", "cancelled"):
                break
        # 取日志尾部作为摘要
        log_tail = ""
        db = SessionLocal()
        try:
            j = db.query(NpuJob).filter(NpuJob.id == job.id).first()
            machine = db.query(NpuMachine).filter(NpuMachine.id == j.machine_id).first()
            from app.services.npu.jobs import get_job_log
            lg = get_job_log(j, machine.to_ssh_params() if machine else {}, offset=max(0, (j.log_size or 0) - 4000))
            log_tail = lg.get("content", "")
        finally:
            db.close()
        status = "passed" if st[0] == "completed" else (
            "error" if st[0] == "cancelled" else "failed")
        _finish_run(run_id, status, (time.time() - t0) * 1000,
                    log_tail or f"job {st[0]} exit={st[1]}", job_id=job.id)

    threading.Thread(target=_worker, daemon=True, name=f"npu-test-{run_id}").start()
    return run_id


def _run_openai_chat(case_id: int, service_id: int, payload: dict,
                     timeout_s: int) -> int:
    run_id = _create_run(case_id, None, service_id)
    t0 = time.time()

    db = SessionLocal()
    try:
        service = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == service_id).first()
        health_url = service.health_url if service else None
        model_name = service.model_name if service else ""
    finally:
        db.close()
    if not health_url:
        _finish_run(run_id, "error", 0, "服务实例缺少地址")
        return run_id

    message = payload.get("message") or "Hello, reply with one word."
    expect_keyword = payload.get("expect_keyword") or ""
    max_tokens = int(payload.get("max_tokens") or 64)

    try:
        resp = requests.post(
            f"{health_url}/v1/chat/completions",
            json={"model": model_name, "messages": [{"role": "user", "content": message}],
                  "max_tokens": max_tokens},
            timeout=min(timeout_s, 120))
    except Exception as e:
        _finish_run(run_id, "error", (time.time() - t0) * 1000, f"请求失败: {e}")
        return run_id

    duration = (time.time() - t0) * 1000
    if resp.status_code != 200:
        _finish_run(run_id, "failed", duration,
                    f"HTTP {resp.status_code}: {resp.text[:500]}")
        return run_id
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        _finish_run(run_id, "error", duration, f"响应解析失败: {e}")
        return run_id
    if expect_keyword and expect_keyword not in content:
        _finish_run(run_id, "failed", duration,
                    f"输出不含期望关键字 '{expect_keyword}'：{content[:300]}")
        return run_id
    _finish_run(run_id, "passed", duration, content[:1000])
    return run_id
