"""
Contributions API - 贡献数据
按 GitHub ID 过滤的 PR/Issue 列表和统计（从 Item 表查询，按 author 过滤）
"""
import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Item, MyPR, _iso_utc

logger = logging.getLogger(__name__)
router = APIRouter()


def _pr_from_item(item: Item) -> dict:
    """将 Item 转为前端期望的 PR 格式，补充 MyPR 中的冲突/CI 状态"""
    result = {
        "pr_number": item.number,
        "title": item.title or "",
        "state": item.state,
        "branch": "",
        "ci_status": "unknown",
        "conflict_detected": False,
        "conflict_commits": 0,
        "additions": item.additions or 0,
        "deletions": item.deletions or 0,
        "changed_files": item.changed_files or 0,
        "created_at": _iso_utc(item.created_at),
        "last_sync": _iso_utc(item.last_sync),
        "author": item.author or "",
        "url": item.url or "",
    }
    return result


def _issue_from_item(item: Item) -> dict:
    """将 Item 转为前端期望的 Issue 格式"""
    return {
        "number": item.number,
        "title": item.title or "",
        "state": item.state,
        "author": item.author or "",
        "body": item.body or "",
        "labels": item.labels or [],
        "comments": item.comments or 0,
        "created_at": _iso_utc(item.created_at),
        "updated_at": _iso_utc(item.updated_at),
        "url": item.url or "",
    }


@router.get("/prs")
async def list_contrib_prs(
    author: str = Query(..., description="GitHub ID 过滤"),
    state: str = Query("all", description="open/merged/closed/all"),
    db: Session = Depends(get_db),
):
    """按 author(github_id) 获取贡献 PR 列表"""
    if not author.strip():
        raise HTTPException(status_code=400, detail="author is required")

    q = db.query(Item).filter(Item.type == "pr", Item.author == author.strip())
    if state == "open":
        q = q.filter(Item.state == "open")
    elif state == "merged":
        q = q.filter(Item.state == "merged")
    elif state == "closed":
        q = q.filter(Item.state == "closed")

    items = q.order_by(Item.created_at.desc()).all()

    # 补充 MyPR 中的冲突/CI 信息
    pr_numbers = [i.number for i in items]
    mypr_map = {}
    if pr_numbers:
        myprs = db.query(MyPR).filter(MyPR.pr_number.in_(pr_numbers)).all()
        for m in myprs:
            mypr_map[m.pr_number] = m

    results = []
    for item in items:
        pr = _pr_from_item(item)
        m = mypr_map.get(item.number)
        if m:
            pr["branch"] = m.branch or ""
            pr["ci_status"] = m.ci_status or "unknown"
            pr["conflict_detected"] = bool(m.conflict_detected)
            pr["conflict_commits"] = m.conflict_commits or 0
        results.append(pr)
    return results


@router.get("/issues")
async def list_contrib_issues(
    author: str = Query(..., description="GitHub ID 过滤"),
    state: str = Query("all", description="open/closed/all"),
    db: Session = Depends(get_db),
):
    """按 author(github_id) 获取贡献 Issue 列表"""
    if not author.strip():
        raise HTTPException(status_code=400, detail="author is required")

    q = db.query(Item).filter(Item.type == "issue", Item.author == author.strip())
    if state == "open":
        q = q.filter(Item.state == "open")
    elif state == "closed":
        q = q.filter(Item.state == "closed")

    items = q.order_by(Item.created_at.desc()).all()
    return [_issue_from_item(i) for i in items]


@router.get("/stats")
async def get_contrib_stats(
    author: str = Query(..., description="GitHub ID 过滤"),
    db: Session = Depends(get_db),
):
    """按 author(github_id) 获取贡献统计"""
    if not author.strip():
        raise HTTPException(status_code=400, detail="author is required")

    prs = db.query(Item).filter(Item.type == "pr", Item.author == author.strip()).all()
    issues = db.query(Item).filter(Item.type == "issue", Item.author == author.strip()).all()

    merged_prs = [p for p in prs if p.state == "merged"]
    open_prs = [p for p in prs if p.state == "open"]
    open_issues = [i for i in issues if i.state == "open"]

    # 月度贡献趋势
    monthly_created = Counter()
    monthly_merged = Counter()
    for p in prs:
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

    return {
        "author": author.strip(),
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