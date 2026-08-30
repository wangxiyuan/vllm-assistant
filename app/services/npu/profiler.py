"""Profiling 采集会话管理

依托 vLLM 服务自带的 /start_profile、/stop_profile 端点（部署时以
--profiler-config 启动才会注册）。管理端直接 HTTP 调用开始/停止采集，
输出文件落在机器上的 profiling 目录（同路径挂载），经 SSH/SFTP 浏览下载，
供 MindStudio Insight 离线分析。
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from app.config import Config
from app.database import SessionLocal
from app.models import NpuMachine, NpuProfileSession, NpuServiceInstance
from app.services.npu import ssh

logger = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _post_profile_api(instance: NpuServiceInstance, endpoint: str,
                      timeout: int = 60) -> None:
    """调用服务的 /start_profile 或 /stop_profile"""
    base = instance.health_url
    if not base:
        raise ValueError("实例缺少健康检查地址，无法定位服务端口")
    try:
        resp = requests.post(f"{base}/{endpoint}", timeout=timeout)
    except requests.RequestException as e:
        raise RuntimeError(f"调用 /{endpoint} 失败: {e}")
    if resp.status_code == 404:
        raise RuntimeError("服务未注册 /%s 端点（需以 Profiling 模式重新部署）" % endpoint)
    if resp.status_code != 200:
        raise RuntimeError(f"/{endpoint} 返回 {resp.status_code}")


def start_collection(instance_id: int, notes: str = "") -> Dict[str, Any]:
    """开始采集：校验 + POST /start_profile + 建会话记录"""
    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id).first()
        if instance is None:
            raise ValueError("服务实例不存在")
        if not instance.profiling_enabled or not instance.profiling_dir:
            raise ValueError("该实例未开启 Profiling 支持，请以 Profiling 模式重新部署")
        if not instance.status == "running":
            raise ValueError(f"服务实例未在运行（{instance.status}）")
        # 已有进行中的会话则拒绝重复开启
        active = db.query(NpuProfileSession).filter(
            NpuProfileSession.service_id == instance_id,
            NpuProfileSession.status == "collecting").first()
        if active:
            raise ValueError(f"已有进行中的采集会话 #{active.id}，请先停止")
        session = NpuProfileSession(
            service_id=instance_id,
            machine_id=instance.machine_id,
            status="collecting",
            output_dir=instance.profiling_dir,
            notes=notes or None,
            started_at=_now(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        session_id = session.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == instance_id).first()
    finally:
        db.close()

    try:
        _post_profile_api(instance, "start_profile")
    except Exception as e:
        db = SessionLocal()
        try:
            s = db.query(NpuProfileSession).filter(
                NpuProfileSession.id == session_id).first()
            if s:
                s.status = "failed"
                s.error_message = str(e)[:500]
                db.commit()
        finally:
            db.close()
        raise

    logger.info(f"Profiling session #{session_id} started on service #{instance_id}")
    return {"session_id": session_id}


def _scan_files(machine_params: dict, output_dir: str) -> List[dict]:
    """SSH 扫描输出目录文件清单"""
    entries = ssh.list_dir(machine_params, output_dir)
    return [e for e in entries if not e.get("is_dir")]


def stop_collection(session_id: int) -> Dict[str, Any]:
    """停止采集：POST /stop_profile + 扫描输出文件落库"""
    db = SessionLocal()
    try:
        session = db.query(NpuProfileSession).filter(
            NpuProfileSession.id == session_id).first()
        if session is None:
            raise ValueError("采集会话不存在")
        if session.status != "collecting":
            raise ValueError(f"会话状态为 {session.status}，无需停止")
        instance = db.query(NpuServiceInstance).filter(
            NpuServiceInstance.id == session.service_id).first()
        machine = db.query(NpuMachine).filter(
            NpuMachine.id == session.machine_id).first()
        session_id_ = session.id
        service_id = session.service_id
        output_dir = session.output_dir
    finally:
        db.close()

    error = None
    try:
        _post_profile_api(instance, "stop_profile")
    except Exception as e:
        error = str(e)

    files: List[dict] = []
    try:
        files = _scan_files(machine.to_ssh_params(), output_dir)
    except Exception as e:
        logger.warning(f"scan profiling dir failed: {e}")

    db = SessionLocal()
    try:
        s = db.query(NpuProfileSession).filter(
            NpuProfileSession.id == session_id_).first()
        if s:
            s.stopped_at = _now()
            if s.started_at:
                s.duration_s = (s.stopped_at - s.started_at).total_seconds()
            s.files = None if not files else json.dumps(files)
            s.total_size = sum(f.get("size") or 0 for f in files)
            s.status = "failed" if error else "completed"
            s.error_message = error[:500] if error else None
            db.commit()
    finally:
        db.close()
    logger.info(f"Profiling session #{session_id_} stopped: {len(files)} files")
    return {"session_id": session_id_, "status": "completed" if not error else "failed",
            "files": len(files), "error": error}


def get_session_detail(session_id: int, refresh: bool = False) -> Dict[str, Any]:
    """会话详情；refresh=True 重新扫描输出目录文件"""
    db = SessionLocal()
    try:
        session = db.query(NpuProfileSession).filter(
            NpuProfileSession.id == session_id).first()
        if session is None:
            raise ValueError("采集会话不存在")
        machine = db.query(NpuMachine).filter(
            NpuMachine.id == session.machine_id).first()
        data = session.to_dict()
        output_dir = session.output_dir
    finally:
        db.close()

    if refresh and machine is not None:
        try:
            files = _scan_files(machine.to_ssh_params(), output_dir)
            db = SessionLocal()
            try:
                s = db.query(NpuProfileSession).filter(
                    NpuProfileSession.id == session_id).first()
                if s:
                    s.files = json.dumps(files)
                    s.total_size = sum(f.get("size") or 0 for f in files)
                    db.commit()
                    data = s.to_dict()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"refresh profiling files failed: {e}")
    return data


def download_file(session_id: int, file_name: str) -> Dict[str, Any]:
    """取回一个 profiling 输出文件到本地临时目录（路径限定 output_dir 内）"""
    import json
    db = SessionLocal()
    try:
        session = db.query(NpuProfileSession).filter(
            NpuProfileSession.id == session_id).first()
        if session is None:
            raise ValueError("采集会话不存在")
        machine = db.query(NpuMachine).filter(
            NpuMachine.id == session.machine_id).first()
        output_dir = session.output_dir
    finally:
        db.close()
    if machine is None:
        raise ValueError("机器不存在")

    remote_path = os.path.join(output_dir, file_name)
    real = os.path.realpath(os.path.expanduser(remote_path))
    base = os.path.realpath(os.path.expanduser(output_dir))
    if not real.startswith(base + os.sep):
        raise ValueError("非法路径")

    tmp_dir = Config.BASE_DIR / "data" / "npu_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    local_path = tmp_dir / f"{session_id}_{os.path.basename(file_name)}"
    ssh.download_file(machine.to_ssh_params(), remote_path, str(local_path))
    return {"local_path": str(local_path), "filename": os.path.basename(file_name)}
