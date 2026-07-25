"""
Intelligence Reports API - 情报面板洞察报告
对应 DESIGN-PERSONAL-TODO.md 3.3

异步生成模式：
- POST /generate 立即返回 report_id + status=generating
- 后台线程执行生成
- 前端轮询 GET /reports/{id} 获取状态
- 完成后 status=completed / failed
"""
import json
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Config
from app.database import SessionLocal, get_db
from app.models import IntelligenceReport, PersonalTask
from app.schemas import IntelligenceGenerateRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _require_api_key() -> None:
    if not Config.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")


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


@router.post("/generate")
async def generate_report(req: IntelligenceGenerateRequest, db: Session = Depends(get_db)):
    """触发生成洞察报告（异步，DESIGN-PERSONAL-TODO.md 3.3 POST）

    立即创建 status=generating 的报告记录，后台线程执行生成。
    """
    _require_api_key()

    # 校验任务存在
    task = db.query(PersonalTask).filter(PersonalTask.id == req.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 自动生成标题
    title = req.title or f"{task.title} 相关动态洞察"

    # 创建 generating 状态的报告
    report = IntelligenceReport(
        title=title,
        content="",
        task_id=req.task_id,
        user_id=req.user_id,
        sources=json.dumps(req.sources, ensure_ascii=False),
        excluded_sources=json.dumps(req.excluded_sources, ensure_ascii=False) if req.excluded_sources else None,
        extra_prompt=req.extra_prompt or None,
        created_at=_utcnow(),
        status="generating",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # 启动后台线程生成
    thread = threading.Thread(
        target=_generate_report_background,
        args=(report.id, task.title, task.description or "", req.sources, req.excluded_sources, req.extra_prompt),
        daemon=True,
    )
    thread.start()

    return {
        "report_id": report.id,
        "task_id": req.task_id,
        "title": title,
        "status": "generating",
        "message": "洞察报告正在生成中，AI 将多轮搜索 GitHub 并分析，预计需要 2-5 分钟",
    }


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


def _generate_report_background(
    report_id: int,
    task_title: str,
    task_description: str,
    sources: list,
    excluded_sources: list,
    extra_prompt: str,
):
    """后台线程执行报告生成

    用独立 DB session（线程隔离）。
    """
    from app.services.intelligence_report import IntelligenceReportGenerator

    db = SessionLocal()
    try:
        generator = IntelligenceReportGenerator()
        result = generator.generate_report(
            task_title=task_title,
            task_description=task_description,
            sources=sources,
            excluded_sources=excluded_sources if excluded_sources else None,
            extra_prompt=extra_prompt or "",
        )

        report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
        if not report:
            logger.error(f"report {report_id} not found after generation")
            return

        report.content = result["content"]
        report.status = "completed"
        report.error_message = None
        db.commit()
        logger.info(f"intelligence report {report_id} generated successfully")
    except Exception as e:
        logger.exception(f"intelligence report {report_id} generation failed")
        try:
            report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
            if report:
                report.status = "failed"
                report.error_message = str(e)[:500]
                db.commit()
        except Exception:
            logger.exception("failed to mark report as failed")
    finally:
        db.close()
