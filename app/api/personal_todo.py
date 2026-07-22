"""
Personal TODO API - 个人任务管理
对应 DESIGN-PERSONAL-TODO.md 3.1 / 3.2

提供任务的 CRUD 以及去重检查接口。洞察报告生成接口见 app/api/intelligence.py。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import Config
from app.database import get_db
from app.models import PersonalTask, TaskDedupCache, IntelligenceReport, _iso_utc
from app.schemas import (
    PersonalTaskCreate,
    PersonalTaskUpdate,
    DedupCheckRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_STATUSES = ("all", "todo", "in_progress", "done", "cancelled")
VALID_PRIORITIES = ("all", "P0", "P1", "P2", "P3")
SORT_FIELDS = {
    "created": PersonalTask.created_at,
    "updated": PersonalTask.updated_at,
    "priority": PersonalTask.priority,
    "due_date": PersonalTask.due_date,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _task_list_dict(task: PersonalTask, db: Session, insight_task_ids: set = None) -> dict:
    """列表场景下返回的精简 dict（含 has_dedup_check / has_ai_insight 标记）

    insight_task_ids: 已有 completed 报告的 task_id 集合（批量预查，避免 N+1）
    """
    d = task.to_dict()
    d["has_dedup_check"] = bool(task.dedup_check_result)
    if insight_task_ids is not None:
        d["has_ai_insight"] = task.id in insight_task_ids
    else:
        insight_count = (
            db.query(IntelligenceReport)
            .filter(
                IntelligenceReport.task_id == task.id,
                IntelligenceReport.status == "completed",
            )
            .count()
        )
        d["has_ai_insight"] = insight_count > 0
    return d


def _build_stats(db: Session) -> dict:
    """聚合统计：按状态/优先级分组计数"""
    by_status = {"todo": 0, "in_progress": 0, "done": 0, "cancelled": 0}
    by_priority = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    rows = db.query(PersonalTask.status, PersonalTask.priority, func.count(PersonalTask.id)).group_by(
        PersonalTask.status, PersonalTask.priority
    ).all()
    for status, priority, cnt in rows:
        if status in by_status:
            by_status[status] += cnt
        if priority in by_priority:
            by_priority[priority] += cnt
    return {"by_status": by_status, "by_priority": by_priority}


@router.get("/tasks")
async def list_tasks(
    status: str = Query("all"),
    priority: str = Query("all"),
    area: Optional[str] = Query(None),
    sort_by: str = Query("created"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """获取任务列表，支持筛选/排序/分页（DESIGN-PERSONAL-TODO.md 3.1 GET）"""
    if status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of: {VALID_STATUSES}")
    if priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"priority must be one of: {VALID_PRIORITIES}")
    if sort_by not in SORT_FIELDS:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of: {list(SORT_FIELDS.keys())}")
    if sort_order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")

    q = db.query(PersonalTask)
    if status != "all":
        q = q.filter(PersonalTask.status == status)
    if priority != "all":
        q = q.filter(PersonalTask.priority == priority)
    if area:
        q = q.filter(PersonalTask.area == area)

    sort_col = SORT_FIELDS[sort_by]
    if sort_order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    total = q.count()
    tasks = q.offset((page - 1) * per_page).limit(per_page).all()
    # 批量预查哪些 task 有已完成的洞察报告（避免 N+1）
    task_ids = [t.id for t in tasks]
    insight_task_ids = set()
    if task_ids:
        rows = (
            db.query(IntelligenceReport.task_id)
            .filter(
                IntelligenceReport.task_id.in_(task_ids),
                IntelligenceReport.status == "completed",
            )
            .distinct()
            .all()
        )
        insight_task_ids = {r[0] for r in rows}
    return {
        "tasks": [_task_list_dict(t, db, insight_task_ids) for t in tasks],
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_more": (page * per_page) < total,
        "stats": _build_stats(db),
    }


@router.post("/tasks")
async def create_task(req: PersonalTaskCreate, db: Session = Depends(get_db)):
    """创建新任务（DESIGN-PERSONAL-TODO.md 3.1 POST）

    trigger_dedup_check=true 时立即执行去重检查（同步），结果写入 dedup_check_result。
    """
    now = _utcnow()
    task = PersonalTask(
        title=req.title,
        description=req.description,
        source=req.source,
        priority=req.priority,
        status="todo",
        area=req.area or None,
        tags=json.dumps(req.tags, ensure_ascii=False) if req.tags else None,
        due_date=req.due_date,
        related_issue_number=req.related_issue_number,
        related_pr_number=req.related_pr_number,
        related_url=req.related_url or None,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    result = task.to_dict()

    if req.trigger_dedup_check:
        try:
            repos = Config.DEFAULT_DEDUP_REPOS
            dedup_result = _run_dedup_check(task, repos, "hybrid", db)
            result["dedup_check_result"] = dedup_result
        except Exception:
            logger.exception("dedup check failed on task create")
            result["dedup_check_result"] = {"checked": False, "error": "dedup check failed"}

    return result


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, req: PersonalTaskUpdate, db: Session = Depends(get_db)):
    """更新任务（DESIGN-PERSONAL-TODO.md 3.1 PUT）"""
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "tags":
            task.tags = json.dumps(value, ensure_ascii=False) if value else None
        elif key == "status":
            if value == "done" and task.status != "done":
                task.completed_at = _utcnow()
            elif value != "done":
                task.completed_at = None
            task.status = value
        elif key in ("area", "related_url", "due_date"):
            # 空字符串归一为 None，与 create 逻辑一致
            setattr(task, key, value if value else None)
        else:
            setattr(task, key, value)
    task.updated_at = _utcnow()

    db.commit()
    db.refresh(task)
    return task.to_dict()


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: Session = Depends(get_db)):
    """删除任务（DESIGN-PERSONAL-TODO.md 3.1 DELETE）

    级联清理：去重缓存 + 关联的洞察报告
    """
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # 级联清理去重缓存
    db.query(TaskDedupCache).filter(TaskDedupCache.task_id == task_id).delete()
    # 级联清理关联的洞察报告
    db.query(IntelligenceReport).filter(IntelligenceReport.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    return {"deleted": True}


@router.get("/tasks/{task_id}")
async def get_task(task_id: int, db: Session = Depends(get_db)):
    """获取单个任务详情"""
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_list_dict(task, db)


@router.post("/tasks/{task_id}/dedup-check")
def dedup_check(task_id: int, req: DedupCheckRequest, db: Session = Depends(get_db)):
    """对指定任务执行去重检查（DESIGN-PERSONAL-TODO.md 3.2）

    用 def（非 async）避免同步 GitHub/AI 调用阻塞事件循环。
    """
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    repos = req.repos or Config.DEFAULT_DEDUP_REPOS
    try:
        result = _run_dedup_check(task, repos, req.check_type, db)
        return {
            "task_id": task.id,
            "checked_at": _iso_utc(_utcnow()),
            "results": result.get("matches", []),
        }
    except Exception:
        logger.exception("dedup check failed")
        raise HTTPException(status_code=500, detail="Dedup check failed")


def _run_dedup_check(task: PersonalTask, repos: list, check_type: str, db: Session) -> dict:
    """执行去重检查并持久化结果。

    被 create_task 和 dedup_check 复用。返回 {"checked": bool, "matches": [...]}。
    """
    from app.services.task_dedup import TaskDedupChecker

    checker = TaskDedupChecker()
    matches = checker.check_duplicates(
        title=task.title or "",
        description=task.description or "",
        repos=repos,
        check_type=check_type,
    )

    result = {"checked": True, "matches": matches}

    # 持久化到 task
    task.dedup_check_result = json.dumps(result, ensure_ascii=False)
    task.updated_at = _utcnow()
    # 持久化到缓存表
    cache_row = TaskDedupCache(
        task_id=task.id,
        check_type=check_type,
        matched_items=json.dumps(matches, ensure_ascii=False),
        checked_at=_utcnow(),
    )
    db.add(cache_row)
    db.commit()
    db.refresh(task)
    return result
