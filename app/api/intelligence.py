"""
Intelligence Reports API - 情报面板洞察报告
对应 DESIGN-PERSONAL-TODO.md 3.3

完整的报告 CRUD：列表/详情/生成/删除/每日触发
"""
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models import IntelligenceReport, PersonalTask
from app.services import entity_writer

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
    from app.schemas import IntelligenceGenerateRequest

    body = await request.json()
    req = IntelligenceGenerateRequest(**body)

    try:
        result = entity_writer.start_intelligence_report(
            title=req.title,
            sources=req.sources,
            excluded_sources=req.excluded_sources,
            extra_prompt=req.extra_prompt,
            task_id=req.task_id,
            user_id=req.user_id,
            report_id=req.report_id,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to generate report")
        raise HTTPException(status_code=500, detail="Failed to generate report")

    return {
        **result,
        "task_id": req.task_id,
        "message": "洞察报告正在生成中，AI 将多轮搜索 GitHub 并分析，预计需要 2-5 分钟",
    }


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
            report_id=report_id,
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
    """获取最新一份 vLLM 每日社区报告"""
    today_start = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d 00:00:00")
    report = db.query(IntelligenceReport).filter(
        IntelligenceReport.category == "daily",
        IntelligenceReport.status == "completed",
        IntelligenceReport.created_at >= today_start,
    ).order_by(IntelligenceReport.created_at.desc()).first()
    if not report:
        return {"report": None}
    return {"report": report.to_dict(include_content=True)}


@router.get("/reports/{report_id}/trace")
async def get_report_trace(report_id: int):
    """获取报告生成过程痕迹（提示词/工具调用/用量），按阶段升序。"""
    db = SessionLocal()
    try:
        report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")

        from app.models import IntelligenceReportTrace
        traces = db.query(IntelligenceReportTrace).filter(
            IntelligenceReportTrace.report_id == report_id,
        ).order_by(IntelligenceReportTrace.stage_index.asc(), IntelligenceReportTrace.id.asc()).all()

        total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        total_duration_ms = 0
        trace_list = []
        for tr in traces:
            d = tr.to_dict()
            u = d.get("usage") or {}
            total_usage["input_tokens"] += u.get("input_tokens", 0) or 0
            total_usage["output_tokens"] += u.get("output_tokens", 0) or 0
            total_usage["total_tokens"] += u.get("total_tokens", 0) or 0
            total_duration_ms += d.get("duration_ms") or 0
            trace_list.append(d)

        return {
            "report_id": report_id,
            "title": report.title,
            "status": report.status,
            "traces": trace_list,
            "total_usage": total_usage,
            "total_duration_ms": total_duration_ms,
        }
    finally:
        db.close()


@router.get("/reports/{report_id}/progress")
async def get_report_progress(report_id: int):
    """获取报告生成进度（阶段 / 工具列表 / 百分比）。"""
    from app.services.report_progress import get_report_progress

    rec = get_report_progress(report_id)
    if not rec:
        # 无内存进度：回退到 DB 里的粗粒度状态
        db = SessionLocal()
        try:
            report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")
            return {
                "report_id": report_id,
                "status": report.status,
                "stage": None,
                "tools": [],
                "progress": 1.0 if report.status == "completed" else 0.0,
                "stages": ["搜索情报", "深入分析", "撰写报告"],
                "updated_at": None,
            }
        finally:
            db.close()
    rec["status_label"] = rec["status"]
    return rec


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
    """删除洞察报告（同步清理知识库和评论）"""
    report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    from app.models import Comment, IntelligenceReportTrace
    db.query(IntelligenceReportTrace).filter(
        IntelligenceReportTrace.report_id == report_id
    ).delete()

    from app.services.memory_service import MemoryService
    mem = MemoryService()
    mem.forget_by_source_ref_prefix(f"intelligence_report#{report_id}", hard_delete=True, db=db)

    db.query(Comment).filter(
        Comment.target_type == "report",
        Comment.target_id == report_id,
    ).delete()

    db.delete(report)
    db.commit()
    return {"deleted": True}


@router.post("/reports/daily/trigger")
async def trigger_daily_report():
    """手动触发每日社区报告生成"""
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
            IntelligenceReport.status.in_(["completed", "generating"]),
            IntelligenceReport.created_at >= today_start,
        ).first()
        if existing:
            return {"status": "skipped", "message": "今日每日报告已存在或生成中，请稍候"}
    finally:
        db.close()

    thread = threading.Thread(target=generate_daily_vllm_report, daemon=True)
    thread.start()
    return {"status": "triggered", "message": "每日报告正在生成中，预计需要 2-10 分钟"}
