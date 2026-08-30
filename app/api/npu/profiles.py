"""Profiling 采集会话 API

会话列表/详情（可刷新文件清单）、停止采集、单文件下载
（SFTP 取回到临时目录后流式返回，路径限定 output_dir 内防目录穿越）。
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NpuProfileSession, NpuServiceInstance
from app.services.npu import profiler

logger = logging.getLogger(__name__)
router = APIRouter()

# MindStudio Insight 分析提示（前端展示）
ANALYSIS_HINT = (
    "性能文件（ascend_pytorch_profiler_*.db / trace JSON）下载后可用 "
    "MindStudio Insight 打开做算子级分析（https://www.hiascend.com/software/mindstudio）。"
)


@router.get("")
def list_sessions(service_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(NpuProfileSession)
    if service_id is not None:
        q = q.filter(NpuProfileSession.service_id == service_id)
    rows = q.order_by(NpuProfileSession.id.desc()).limit(200).all()
    return [s.to_dict() for s in rows]


@router.post("/{session_id}/stop")
def stop_session(session_id: int, db: Session = Depends(get_db)):
    try:
        return profiler.stop_collection(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}")
def get_session(session_id: int, refresh: bool = Query(False),
                db: Session = Depends(get_db)):
    try:
        data = profiler.get_session_detail(session_id, refresh=refresh)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    data["analysis_hint"] = ANALYSIS_HINT
    return data


@router.get("/{session_id}/download")
def download(session_id: int, path: str = Query(..., description="output_dir 内的文件名或相对路径"),
             db: Session = Depends(get_db)):
    try:
        result = profiler.download_file(session_id, path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"文件取回失败: {e}")
    local_path = result["local_path"]
    filename = result["filename"]
    return FileResponse(local_path, filename=filename,
                        background=BackgroundTask(os.remove, local_path))


# services.py 里的 /{id}/profile/start 依赖此模块的 start_collection，
# 由 services.py 直接 import profiler 调用，避免循环路由依赖。
