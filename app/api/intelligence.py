"""
Intelligence Reports API - 情报面板洞察报告
对应 DESIGN-PERSONAL-TODO.md 3.3

列表/详情/删除操作（生成功能已迁至 /api/ai-agent/reports/generate）
"""
import json
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IntelligenceReport, PersonalTask

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/reports")
async def list_reports(db: Session = Depends(get_db)):
    """获取洞察报告列表（按时间倒序，DESIGN-PERSONAL-TODO.md 3.3 GET）"""
    reports = db.query(IntelligenceReport).order_by(IntelligenceReport.created_at.desc()).all()
    result = []
    for r in reports:
        task_title = None
        if r.task_id:
            task = db.query(PersonalTask).filter(PersonalTask.id == r.task_id).first()
            if task:
                task_title = task.title
        result.append(r.to_dict(include_content=False, task_title=task_title))
    return {"reports": result}


@router.get("/reports/daily/latest")
async def get_latest_daily_report(db: Session = Depends(get_db)):
    """获取最新一份 vLLM 每日全景报告"""
    today_start = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d 00:00:00")
    report = db.query(IntelligenceReport).filter(
        IntelligenceReport.category == "daily",
        IntelligenceReport.status == "completed",
        IntelligenceReport.created_at >= today_start,
    ).order_by(IntelligenceReport.created_at.desc()).first()
    if not report:
        return {"report": None}
    return {"report": report.to_dict(include_content=True)}


@router.get("/reports/{report_id}")
async def get_report(report_id: int, db: Session = Depends(get_db)):
    """获取洞察报告详情（DESIGN-PERSONAL-TODO.md 3.3 GET 详情）"""
    report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    task_title = None
    if report.task_id:
        task = db.query(PersonalTask).filter(PersonalTask.id == report.task_id).first()
        if task:
            task_title = task.title

    return report.to_dict(include_content=True, task_title=task_title)


@router.delete("/reports/{report_id}")
async def delete_report(report_id: int, db: Session = Depends(get_db)):
    """删除洞察报告"""
    report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    db.delete(report)
    db.commit()
    return {"deleted": True}


@router.post("/reports/daily/trigger")
async def trigger_daily_report():
    """手动触发每日全景报告生成"""
    from datetime import datetime, timezone
    from app.database import SessionLocal
    from app.models import IntelligenceReport
    from app.scheduler import generate_daily_vllm_report, _running_jobs

    job_id = "daily_vllm_report"
    if job_id in _running_jobs:
        return {"status": "skipped", "message": "每日报告正在生成中，请稍候"}

    today_start = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d 00:00:00")
    db = SessionLocal()
    try:
        existing = db.query(IntelligenceReport).filter(
            IntelligenceReport.category == "daily",
            IntelligenceReport.status == "completed",
            IntelligenceReport.created_at >= today_start,
        ).first()
        if existing:
            return {"status": "skipped", "message": "今日每日报告已存在，如需重新生成请先删除旧报告"}
    finally:
        db.close()

    thread = threading.Thread(target=generate_daily_vllm_report, daemon=True)
    thread.start()
    return {"status": "triggered", "message": "每日报告正在生成中，预计需要 2-10 分钟"}
