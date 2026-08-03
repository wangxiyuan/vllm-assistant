"""
Intelligence Reports API - 情报面板洞察报告
对应 DESIGN-PERSONAL-TODO.md 3.3

完整的报告 CRUD：列表/详情/生成/删除/每日触发
"""
import json
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import Config
from app.database import get_db, SessionLocal
from app.models import IntelligenceReport, PersonalTask

logger = logging.getLogger(__name__)
router = APIRouter()


# ======================================================================
# 报告生成（后台异步）
# ======================================================================


@router.post("/reports/generate")
async def generate_report(request: Request):
    """触发生成洞察报告（异步）

    立即创建 status=generating 的报告记录，后台线程执行生成。
    """
    if not Config.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")

    from app.schemas import IntelligenceGenerateRequest
    from datetime import datetime, timezone

    body = await request.json()
    req = IntelligenceGenerateRequest(**body)

    db = SessionLocal()
    try:
        task = db.query(PersonalTask).filter(PersonalTask.id == req.task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        title = req.title or f"{task.title} 相关动态洞察"

        if req.report_id:
            report = db.query(IntelligenceReport).filter(IntelligenceReport.id == req.report_id).first()
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")
            report.title = title
            report.content = ""
            report.sources = json.dumps(req.sources, ensure_ascii=False)
            report.excluded_sources = json.dumps(req.excluded_sources, ensure_ascii=False) if req.excluded_sources else None
            report.extra_prompt = req.extra_prompt or None
            report.status = "generating"
            report.error_message = None
            report.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            db.refresh(report)
        else:
            report = IntelligenceReport(
                title=title,
                content="",
                task_id=req.task_id,
                user_id=req.user_id,
                sources=json.dumps(req.sources, ensure_ascii=False),
                excluded_sources=json.dumps(req.excluded_sources, ensure_ascii=False) if req.excluded_sources else None,
                extra_prompt=req.extra_prompt or None,
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                status="generating",
            )
            db.add(report)
            db.commit()
            db.refresh(report)

        import threading
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
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to generate report")
        raise HTTPException(status_code=500, detail="Failed to generate report")
    finally:
        db.close()


def _generate_report_background(
    report_id: int,
    task_title: str,
    task_description: str,
    sources: list,
    excluded_sources: list,
    extra_prompt: str,
):
    """后台线程执行报告生成"""
    from app.services.intelligence_report import IntelligenceReportGenerator
    from app.services.memory_service import MemoryService
    from app.models import IntelligenceReport

    db = SessionLocal()
    try:
        generator = IntelligenceReportGenerator(db=db)
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

        try:
            mem = MemoryService()
            content = (
                f"# 洞察报告: {report.title}\n\n"
                f"{result['content']}\n\n"
                f"---\n"
                f"**关联任务**: {task_title}\n"
                f"**来源范围**: {', '.join(sources) if sources else '全部'}\n"
                f"**报告 ID**: {report_id}\n"
            )
            mem.remember(
                content=content,
                source_type="report",
                source_ref=f"intelligence_report#{report_id}",
                tags=["report", "intelligence"] + [f"source:{s}" for s in sources],
            )
            logger.info(f"intelligence report {report_id} saved to knowledge base")
        except Exception:
            logger.exception(f"failed to save report {report_id} to knowledge base")
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


# ======================================================================
# 列表/详情/删除/每日触发（原有逻辑保持不变）
# ======================================================================


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
