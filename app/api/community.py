"""
Community Pulse API - 社区动态感知
读 SQLite 缓存（scheduler 异步填充），符合 DESIGN.md 296-298 行"优先缓存"策略。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Item, Area
from app.scheduler import trigger_refresh
from app.services.area_mapper import AreaMapper

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_recent(created_at) -> bool:
    """DESIGN.md 67 行：创建于 2 小时内标记为新 item"""
    if not created_at:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at) < timedelta(hours=2)


def _item_to_response_dict(item: Item) -> dict:
    d = item.to_dict()
    d["is_new"] = _is_recent(item.created_at)
    return d


@router.get("/items", response_model=None)
async def get_community_items(
    type: str = Query("all", pattern="^(issue|pr|all)$"),
    area: Optional[str] = None,
    limit: int = Query(30, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("created", pattern="^(created|updated|comments)$"),
    force_refresh: bool = False,
    db: Session = Depends(get_db),
):
    """从缓存读取 community items（issues/prs）。

    支持 offset 分页：limit=20&offset=20 获取第二页。
    `force_refresh=true` 触发后台同步，立即返回当前缓存（不阻塞）。
    返回 dict：``{"items": [...], "refresh_triggered": bool}``（force_refresh=false 时无 refresh_triggered）
    """
    refresh_triggered = False
    if force_refresh:
        try:
            result = trigger_refresh()
            refresh_triggered = result.get("triggered", False)
        except Exception:
            logger.exception("force_refresh trigger failed")

    q = db.query(Item)
    if type in ("issue", "pr"):
        q = q.filter(Item.type == type)
    if area:
        q = q.filter(Item.area == area)

    sort_key = {
        "created": Item.created_at,
        "updated": Item.updated_at,
        "comments": Item.comments,
    }[sort_by]
    items = q.order_by(sort_key.desc()).offset(offset).limit(limit).all()

    payload = {"items": [_item_to_response_dict(it) for it in items]}
    if force_refresh:
        payload["refresh_triggered"] = refresh_triggered
    return payload


@router.get("/areas")
async def get_areas(db: Session = Depends(get_db)):
    """从缓存读取领域列表"""
    try:
        areas = db.query(Area).all()
        if areas:
            return [a.to_dict() for a in areas]
        # 缓存未填充（scheduler 还没跑）时回退到 area_mapper 的内存数据
        return AreaMapper().get_all_areas()
    except Exception:
        logger.exception("Error in get_areas")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_community_stats(db: Session = Depends(get_db)):
    """从缓存聚合社区统计（使用 SQL 聚合查询，避免全表扫描）"""
    try:
        from sqlalchemy import func

        # 按 type 分组统计总数
        type_counts = db.query(
            Item.type, func.count(Item.id)
        ).group_by(Item.type).all()
        type_count_map = dict(type_counts)

        # 按 area + type 分组统计
        area_rows = db.query(
            Item.area, Item.type, func.count(Item.id)
        ).filter(Item.area.isnot(None)).group_by(Item.area, Item.type).all()

        area_stats: dict = {}
        for area_id, type_, _count in area_rows:
            area_stats.setdefault(area_id, {"issues": 0, "prs": 0})
            if type_ == "issue":
                area_stats[area_id]["issues"] += _count
            elif type_ == "pr":
                area_stats[area_id]["prs"] += _count

        return {
            "total_issues": type_count_map.get("issue", 0),
            "total_prs": type_count_map.get("pr", 0),
            "area_breakdown": area_stats,
        }
    except Exception:
        logger.exception("Error in get_community_stats")
        raise HTTPException(status_code=500, detail="Internal server error")
