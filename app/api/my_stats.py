"""
My Stats API - 我的贡献数据仪表盘
从 SQLite 缓存读取（scheduler 同步），纯数据，无 AI。
"""
import logging
from datetime import datetime, timezone, timedelta
from collections import Counter
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MyPR, UserIssue, _iso_utc

logger = logging.getLogger(__name__)
router = APIRouter()


def _iso(dt):
    """Compatibility wrapper using the centralized _iso_utc"""
    return _iso_utc(dt)


@router.get("")
async def get_my_stats(db: Session = Depends(get_db)):
    """获取用户贡献统计仪表盘数据（从缓存读）"""
    from app.config import Config
    if not Config.USERNAME:
        raise HTTPException(status_code=400, detail="GITHUB_USERNAME not configured")

    username = Config.USERNAME

    # 从 my_prs 缓存读
    my_prs = db.query(MyPR).all()
    # 从 user_issues 缓存读
    my_issues = db.query(UserIssue).all()

    # PR 分类（my_prs.state 已是 open/merged/closed）
    merged_prs = [p for p in my_prs if p.state == "merged"]
    open_prs = [p for p in my_prs if p.state == "open"]
    closed_prs = [p for p in my_prs if p.state == "closed"]

    # Issue 分类
    open_issues = [i for i in my_issues if i.state == "open"]
    closed_issues = [i for i in my_issues if i.state == "closed"]

    # 贡献时长：用 PR/Issue 的 created_at（首次贡献时间）
    all_dates = []
    for p in my_prs:
        # 优先 created_at（PR 创建时间），fallback last_sync（旧数据）
        dt = p.created_at or p.last_sync
        if dt:
            all_dates.append(dt)
    for i in my_issues:
        # UserIssue 也有 created_at
        dt = i.created_at or i.last_sync
        if dt:
            all_dates.append(dt)

    first_contribution = _iso_utc(min(all_dates)) if all_dates else None

    # 贡献时长（天）：从首次贡献到现在
    days_active = None
    if all_dates:
        first_date = min(all_dates)
        if first_date.tzinfo is None:
            first_date = first_date.replace(tzinfo=timezone.utc)
        days_active = (datetime.now(timezone.utc) - first_date).days

    # 近 30 天活跃：用 last_sync 近似（不准确，但用户看到的是基于缓存的）
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent_prs = [p for p in my_prs if p.last_sync and p.last_sync.replace(tzinfo=timezone.utc) > cutoff]
    recent_issues = [i for i in my_issues if i.last_sync and i.last_sync.replace(tzinfo=timezone.utc) > cutoff]
    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)
    recent_7d_prs = [p for p in my_prs if p.last_sync and p.last_sync.replace(tzinfo=timezone.utc) > cutoff_7d]
    recent_7d_issues = [i for i in my_issues if i.last_sync and i.last_sync.replace(tzinfo=timezone.utc) > cutoff_7d]

    # 月度贡献趋势：用 PR 创建时间 created_at（而非 last_sync，否则每次同步都归到当月）
    monthly_created = Counter()
    monthly_merged = Counter()
    for p in my_prs:
        # 优先用 created_at；若缺失（旧数据）则 fallback 到 last_sync
        dt = p.created_at or p.last_sync
        if dt:
            monthly_created[dt.strftime("%Y-%m")] += 1
    for p in merged_prs:
        dt = p.created_at or p.last_sync
        if dt:
            monthly_merged[dt.strftime("%Y-%m")] += 1

    # 补全 0 月份：从有数据的最早月份到当前月份，所有月份都有值（缺则补 0）
    all_months = set(monthly_created.keys()) | set(monthly_merged.keys())
    if all_months:
        sorted_months = sorted(all_months)
        first_month = sorted_months[0]
        last_month = sorted_months[-1]
        # 生成从 first 到 last 的所有月份
        first_year, first_mon = int(first_month[:4]), int(first_month[5:7])
        last_year, last_mon = int(last_month[:4]), int(last_month[5:7])
        cur_year, cur_mon = first_year, first_mon
        full_months = []
        while (cur_year, cur_mon) <= (last_year, last_mon):
            full_months.append(f"{cur_year:04d}-{cur_mon:02d}")
            cur_mon += 1
            if cur_mon > 12:
                cur_mon = 1
                cur_year += 1
        # 补 0
        for m in full_months:
            monthly_created.setdefault(m, 0)
            monthly_merged.setdefault(m, 0)

    monthly_created = dict(sorted(monthly_created.items()))
    monthly_merged = dict(sorted(monthly_merged.items()))

    # 最近 PR（10 条）- 按创建时间倒序
    recent_pr_list = sorted(my_prs, key=lambda p: p.created_at or p.last_sync or datetime.min, reverse=True)[:10]
    recent_pr_summary = [{
        "number": p.pr_number,
        "title": p.title or "",
        "state": p.state or "open",
        "merged": p.state == "merged",
        "created_at": None,  # my_prs 没有 created_at
        "updated_at": _iso(p.last_sync),
        "url": Config.get_pulls_url(p.pr_number),
        "comments": 0,
    } for p in recent_pr_list]

    return {
        "username": username,
        "summary": {
            "total_prs": len(my_prs),
            "merged_prs": len(merged_prs),
            "open_prs": len(open_prs),
            "closed_prs": len(closed_prs),
            "merge_rate": round(len(merged_prs) / len(my_prs) * 100, 1) if my_prs else 0,
            "total_issues": len(my_issues),
            "open_issues": len(open_issues),
            "closed_issues": len(closed_issues),
            "first_contribution": first_contribution,
            "days_active": days_active,
        },
        "activity": {
            "recent_30d_prs": len(recent_prs),
            "recent_30d_issues": len(recent_issues),
            "recent_7d_prs": len(recent_7d_prs),
            "recent_7d_issues": len(recent_7d_issues),
        },
        "monthly": {
            "created": dict(sorted(monthly_created.items())),
            "merged": dict(sorted(monthly_merged.items())),
        },
        "recent_prs": recent_pr_summary,
    }
