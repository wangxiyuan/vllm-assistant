"""
My Stats API - 我的贡献数据仪表盘

按 github_id 过滤，为空时返回所有用户汇总数据。
"""
import logging
from collections import Counter
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MyPR, UserIssue, _iso_utc

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def get_my_stats(
    github_id: Optional[str] = Query(None, description="GitHub ID 过滤，为空时返回所有用户汇总"),
    db: Session = Depends(get_db),
):
    """获取用户贡献统计仪表盘数据（按 github_id 过滤，为空时返回所有用户汇总）"""
    if github_id:
        my_prs = db.query(MyPR).filter(MyPR.github_id == github_id).all()
        my_issues = db.query(UserIssue).filter(UserIssue.github_id == github_id).all()
    else:
        # 不传 github_id 时返回所有用户汇总
        my_prs = db.query(MyPR).all()
        my_issues = db.query(UserIssue).all()

    merged_prs = [p for p in my_prs if p.state == "merged"]
    open_prs = [p for p in my_prs if p.state == "open"]
    open_issues = [i for i in my_issues if i.state == "open"]

    # 月度贡献趋势
    monthly_created = Counter()
    monthly_merged = Counter()
    for p in my_prs:
        dt = p.created_at or p.last_sync
        if dt:
            monthly_created[dt.strftime("%Y-%m")] += 1
    for p in merged_prs:
        dt = p.created_at or p.last_sync
        if dt:
            monthly_merged[dt.strftime("%Y-%m")] += 1

    # 补全 0 月份
    all_months = set(monthly_created.keys()) | set(monthly_merged.keys())
    if all_months:
        sorted_months = sorted(all_months)
        first_month = sorted_months[0]
        last_month = sorted_months[-1]
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
        for m in full_months:
            monthly_created.setdefault(m, 0)
            monthly_merged.setdefault(m, 0)

    monthly_created = dict(sorted(monthly_created.items()))
    monthly_merged = dict(sorted(monthly_merged.items()))

    return {
        "github_id": github_id,
        "summary": {
            "merged_prs": len(merged_prs),
            "open_prs": len(open_prs),
            "open_issues": len(open_issues),
        },
        "monthly": {
            "created": dict(sorted(monthly_created.items())),
            "merged": dict(sorted(monthly_merged.items())),
        },
    }