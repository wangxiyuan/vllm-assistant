"""
Personal TODO API - 个人任务管理
对应 DESIGN-PERSONAL-TODO.md 3.1 / 3.2

提供任务的 CRUD 以及去重检查接口。洞察报告生成接口见 app/api/intelligence.py。
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, case as sa_case
from sqlalchemy.orm import Session

from app.config import Config
from app.database import get_db
from app.models import PersonalTask, TaskDedupCache, IntelligenceReport, _iso_utc
from app.schemas import (
    PersonalTaskCreate,
    PersonalTaskUpdate,
    DedupCheckRequest,
)
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_STATUSES = ("all", "todo", "in_progress", "done")
VALID_PRIORITIES = ("all", "P0", "P1", "P2", "P3")
SORT_FIELDS = {
    "created": PersonalTask.created_at,
    "updated": PersonalTask.updated_at,
    "priority": PersonalTask.priority,
    "due_date": PersonalTask.due_date,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _task_list_dict(task: PersonalTask, db: Session, insight_task_ids: set = None,
                    insight_report_ids: dict = None,
                    watchlist_set: set = None) -> dict:
    """列表场景下返回的精简 dict（含 has_dedup_check / has_ai_insight 标记）

    insight_task_ids: 已有 completed 报告的 task_id 集合（批量预查，避免 N+1）
    insight_report_ids: task_id → latest report id 映射（批量预查，避免 N+1）
    watchlist_set: {"issue:123", "pr:456"} 集合，用于标记关联 ref 是否在特别关注中
    """
    d = task.to_dict()
    d["has_dedup_check"] = bool(task.dedup_check_result)
    if insight_task_ids is not None:
        d["has_ai_insight"] = task.id in insight_task_ids
        if d["has_ai_insight"] and insight_report_ids is not None:
            d["latest_insight_report_id"] = insight_report_ids.get(task.id)
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
        if d["has_ai_insight"]:
            latest = (
                db.query(IntelligenceReport.id)
                .filter(
                    IntelligenceReport.task_id == task.id,
                    IntelligenceReport.status == "completed",
                )
                .order_by(IntelligenceReport.created_at.desc())
                .first()
            )
            d["latest_insight_report_id"] = latest[0] if latest else None

    # 标记每个 ref 是否在特别关注中
    if watchlist_set is not None:
        refs = d.get("related_refs", []) or []
        for ref in refs:
            key = f"{ref.get('type', 'issue')}:{ref.get('number')}"
            ref["in_watchlist"] = key in watchlist_set

    return d


def _merge_subtask_stats(d: dict, task_id: int, subtask_stats: dict) -> dict:
    """将批量查询的子任务统计合并到任务 dict 中"""
    if subtask_stats and task_id in subtask_stats:
        d.update(subtask_stats[task_id])
    return d


def _build_stats(db: Session) -> dict:
    """聚合统计：按状态/优先级分组计数（只统计顶层任务，排除子任务）"""
    by_status = {"todo": 0, "in_progress": 0, "done": 0}
    by_priority = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    rows = db.query(PersonalTask.status, PersonalTask.priority, func.count(PersonalTask.id)).filter(
        PersonalTask.parent_id.is_(None)
    ).group_by(
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

    # 只显示顶层任务（非子任务）
    q = q.filter(PersonalTask.parent_id.is_(None))

    sort_col = SORT_FIELDS[sort_by]
    if sort_order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    total = q.count()
    tasks = q.offset((page - 1) * per_page).limit(per_page).all()
    # 批量预查子任务统计（避免 N+1）
    task_ids = [t.id for t in tasks]
    subtask_stats = {}
    if task_ids:
        rows = (
            db.query(
                PersonalTask.parent_id,
                func.count(PersonalTask.id).label("total"),
                func.sum(sa_case((PersonalTask.status == "done", 1), else_=0)).label("done"),
            )
            .filter(PersonalTask.parent_id.in_(task_ids))
            .group_by(PersonalTask.parent_id)
            .all()
        )
        for parent_id, total, done in rows:
            subtask_stats[parent_id] = {"subtask_count": total, "subtask_done_count": done or 0}
    # 批量预查哪些 task 有已完成的洞察报告（避免 N+1）
    insight_task_ids = set()
    insight_report_ids = {}
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
        if insight_task_ids:
            # 批量查询每个 task 最新报告的 id
            from sqlalchemy import func as sa_func
            subq = (
                db.query(
                    IntelligenceReport.task_id,
                    sa_func.max(IntelligenceReport.id).label("max_id"),
                )
                .filter(
                    IntelligenceReport.task_id.in_(list(insight_task_ids)),
                    IntelligenceReport.status == "completed",
                )
                .group_by(IntelligenceReport.task_id)
                .subquery()
            )
            report_rows = (
                db.query(IntelligenceReport.id, IntelligenceReport.task_id)
                .join(subq, IntelligenceReport.id == subq.c.max_id)
                .all()
            )
            insight_report_ids = {r.task_id: r.id for r in report_rows}

    # 批量预查 watchlist（避免 N+1）
    from app.models import Watchlist
    watchlist_items = db.query(Watchlist).all()
    watchlist_set = {f"{w.item_type}:{w.number}" for w in watchlist_items}

    return {
        "tasks": [_merge_subtask_stats(_task_list_dict(t, db, insight_task_ids, insight_report_ids, watchlist_set), t.id, subtask_stats) for t in tasks],
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
        assignee_id=req.assignee_id,
        tags=json.dumps(req.tags, ensure_ascii=False) if req.tags else None,
        due_date=req.due_date,
        related_refs=req.related_refs if req.related_refs else None,
        parent_id=req.parent_id,
        subtask_order=req.subtask_order or 0,
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
        elif key == "related_refs":
            task.related_refs = value if value else None
        elif key == "status":
            if value == "done" and task.status != "done":
                task.completed_at = _utcnow()
            elif value != "done":
                task.completed_at = None
            task.status = value
        elif key in ("area", "due_date"):
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

    级联清理：子任务 + 去重缓存 + 关联的洞察报告
    """
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # 级联删除子任务
    db.query(PersonalTask).filter(PersonalTask.parent_id == task_id).delete()
    # 级联清理去重缓存
    db.query(TaskDedupCache).filter(TaskDedupCache.task_id == task_id).delete()
    # 级联清理关联的洞察报告
    db.query(IntelligenceReport).filter(IntelligenceReport.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    return {"deleted": True}


@router.get("/tasks/{task_id}/subtasks")
async def list_subtasks(task_id: int, db: Session = Depends(get_db)):
    """获取指定任务的所有子任务列表"""
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    subtasks = (
        db.query(PersonalTask)
        .filter(PersonalTask.parent_id == task_id)
        .order_by(PersonalTask.subtask_order.asc(), PersonalTask.created_at.asc())
        .all()
    )

    total = len(subtasks)
    done_count = sum(1 for s in subtasks if s.status == "done")

    # 批量查询 watchlist
    from app.models import Watchlist
    watchlist_items = db.query(Watchlist).all()
    watchlist_set = {f"{w.item_type}:{w.number}" for w in watchlist_items}

    return {
        "subtasks": [_task_list_dict(s, db, watchlist_set=watchlist_set) for s in subtasks],
        "total": total,
        "done_count": done_count,
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: int, db: Session = Depends(get_db)):
    """获取单个任务详情"""
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 批量查询 watchlist
    from app.models import Watchlist
    watchlist_items = db.query(Watchlist).all()
    watchlist_set = {f"{w.item_type}:{w.number}" for w in watchlist_items}

    return _task_list_dict(task, db, watchlist_set=watchlist_set)


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


class ResolveRefRequest(BaseModel):
    """解析关联引用的请求"""
    input: str  # 用户输入，如 "vllm#123" 或 "123"


@router.post("/resolve-ref")
def resolve_ref(req: ResolveRefRequest, db: Session = Depends(get_db)):
    """解析用户输入的关联引用，自动判断是 issue 还是 PR。

    输入格式：
    - "vllm#123" — 指定仓库 + 编号
    - "123" — 纯编号，用默认仓库 (vllm-project/vllm)
    返回：{repo, number, type, url, title} 或 404 错误。
    """
    from app.services.github_client import GitHubClient

    text = req.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="输入不能为空")

    # 解析仓库和编号
    m = re.match(r"^(vllm|vllm-ascend)\s*#\s*(\d+)$", text, re.I)
    if m:
        repo = m.group(1).lower()
        number = int(m.group(2))
    elif text.isdigit():
        repo = "vllm"
        number = int(text)
    else:
        raise HTTPException(status_code=400, detail="输入格式无效，请使用 repo#number 或纯数字")

    # 映射到 GitHub 仓库路径
    repo_map = {"vllm": "vllm-project/vllm", "vllm-ascend": "vllm-project/vllm-ascend"}
    repo_path = repo_map.get(repo, repo)

    # 用 GitHub REST API 直接查询（GitHubClient 只支持默认仓库）
    import requests
    headers = Config.get_github_headers()
    base_api_url = f"https://api.github.com/repos/{repo_path}"

    # 先查 PR
    try:
        resp = requests.get(f"{base_api_url}/pulls/{number}", headers=headers, timeout=10)
        if resp.status_code == 200:
            pr_data = resp.json()
            return {
                "repo": repo,
                "number": number,
                "type": "pr",
                "url": f"https://github.com/{repo_path}/pull/{number}",
                "title": pr_data.get("title", ""),
            }
    except Exception:
        pass

    # 再查 Issue
    try:
        resp = requests.get(f"{base_api_url}/issues/{number}", headers=headers, timeout=10)
        if resp.status_code == 200:
            issue_data = resp.json()
            return {
                "repo": repo,
                "number": number,
                "type": "issue",
                "url": f"https://github.com/{repo_path}/issues/{number}",
                "title": issue_data.get("title", ""),
            }
    except Exception:
        pass

    raise HTTPException(status_code=404, detail=f"在 {repo_path} 中未找到 #{number}")


class LinkToWatchlistRequest(BaseModel):
    """从 watchlist 关联到个人任务的请求"""
    watchlist_item_type: str  # 'issue' or 'pr'
    watchlist_number: int
    watchlist_title: str = ""
    task_id: Optional[int] = None  # 关联已有任务
    new_task_title: Optional[str] = None  # 或创建新任务
    new_task_description: str = ""
    new_task_source: str = "self"  # 任务类型（来源）: self/team/community/meeting


@router.post("/link-to-watchlist")
async def link_to_watchlist(req: LinkToWatchlistRequest, db: Session = Depends(get_db)):
    """从 watchlist 关联到个人任务（双向关联）

    支持两种模式：
    1. 传入 task_id → 关联到已有任务
    2. 传入 new_task_title → 创建新任务并自动关联
    """
    from app.config import Config

    now = _utcnow()
    repo_path = f"{Config.GITHUB_OWNER}/{Config.GITHUB_REPO}"
    ref = {
        "type": req.watchlist_item_type,
        "number": req.watchlist_number,
        "repo": "vllm",
        "url": f"https://github.com/{repo_path}/{ 'pull' if req.watchlist_item_type == 'pr' else 'issues' }/{req.watchlist_number}",
        "title": req.watchlist_title or "",
    }

    if req.task_id:
        # 模式 1：关联到已有任务
        task = db.query(PersonalTask).filter(PersonalTask.id == req.task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        refs = task.related_refs or []
        # 去重：已存在相同 type+number 则不重复添加
        if not any(
            r.get("type") == ref["type"] and r.get("number") == ref["number"]
            for r in refs
        ):
            refs.append(ref)
            task.related_refs = refs
            task.updated_at = now
        db.commit()
        db.refresh(task)
        return task.to_dict()
    elif req.new_task_title:
        # 模式 2：创建新任务
        task = PersonalTask(
            title=req.new_task_title.strip(),
            description=req.new_task_description or "",
            source=req.new_task_source,
            priority="P2",
            status="todo",
            related_refs=[ref],
            created_at=now,
            updated_at=now,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.to_dict()
    else:
        raise HTTPException(status_code=400, detail="Must provide task_id or new_task_title")
