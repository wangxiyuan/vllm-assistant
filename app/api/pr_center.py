"""
PR Command Center API - PR指挥中心
从 SQLite 缓存读取（scheduler 异步同步），符合 DESIGN.md 296-298 行"优先缓存"策略。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MyPR, Item, _iso_utc
from app.services._shared import get_github_client as _get_github_client
from app.schemas import MyPRResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# 缓存有效时间窗口（5 分钟内认为缓存可用）
CACHE_TTL = timedelta(minutes=5)


@router.get("/my-prs", response_model=List[MyPRResponse])
async def get_my_prs(
    state: str = Query("open", pattern="^(open|merged|closed|all)$"),
    filter_conflicts: bool = False,
    filter_ci_fail: bool = False,
    db: Session = Depends(get_db),
):
    """从 my_prs 缓存读取用户的 PR 列表"""
    from app.config import Config
    if not Config.USERNAME:
        raise HTTPException(status_code=400, detail="GITHUB_USERNAME not configured")

    q = db.query(MyPR)
    if state == "open":
        q = q.filter(MyPR.state == "open")
    elif state == "merged":
        q = q.filter(MyPR.state == "merged")
    elif state == "closed":
        q = q.filter(MyPR.state == "closed")

    if filter_conflicts:
        q = q.filter(MyPR.conflict_detected.is_(True))
    if filter_ci_fail:
        q = q.filter(MyPR.ci_status == "fail")

    my_prs = q.order_by(MyPR.created_at.desc()).all()
    return [pr.to_dict() for pr in my_prs]


@router.get("/my-prs/{pr_number}/details")
def get_pr_details(pr_number: int, db: Session = Depends(get_db)):
    """获取单个 PR 的详细信息
    - 基础信息：优先 item 缓存（更全），fallback 到 my_prs 缓存
    - files：实时拉取

    用 def（非 async）避免同步 GitHub API 调用阻塞事件循环。
    """
    client = _get_github_client()
    item = db.query(Item).filter(Item.type == "pr", Item.number == pr_number).first()
    cached = db.query(MyPR).filter(MyPR.pr_number == pr_number).first()

    try:
        files = client.get_pull_files(pr_number) or []
    except Exception:
        logger.exception(f"get_pull_files failed for PR#{pr_number}")
        files = []

    # 合并：item 优先（包含更多字段），再用 my_prs 补 conflict/ci 状态
    if item:
        pr_payload = item.to_dict()
    elif cached:
        pr_payload = cached.to_dict()
    else:
        pr_payload = None

    if pr_payload and cached:
        # 补充 my_prs 独有的字段
        for k in ("branch", "ci_status",
                  "conflict_detected", "conflict_commits"):
            if getattr(cached, k, None) is not None and not pr_payload.get(k):
                pr_payload[k] = getattr(cached, k)

    return {
        "pr": pr_payload,
        "files": files,
    }


@router.get("/my-prs/{pr_number}/conflicts")
def check_pr_conflicts(pr_number: int, db: Session = Depends(get_db)):
    """检测 PR 是否有冲突
    - 缓存策略：last_sync 在 CACHE_TTL 内直接用缓存
    - 否则实时调 Compare API
    """
    from app.services.conflict_detector import ConflictDetector

    cached = db.query(MyPR).filter(MyPR.pr_number == pr_number).first()

    if cached and cached.last_sync:
        age = datetime.now(timezone.utc).replace(tzinfo=None) - cached.last_sync
        if age < CACHE_TTL:
            return {
                "has_conflict": bool(cached.conflict_detected),
                "behind_count": cached.conflict_commits or 0,
                "ahead_count": 0,
                "can_fast_forward": not cached.conflict_detected,
                "last_sync_time": _iso_utc(cached.last_sync),
                "source": "cache",
                "cache_age_seconds": int(age.total_seconds()),
            }

    # 缓存缺失或过期：实时检测
    try:
        detector = ConflictDetector(_get_github_client())
        result = detector.detect_conflicts(pr_number)
        result["source"] = "live"
        return result
    except Exception:
        logger.exception(f"Live conflict detection failed for PR#{pr_number}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/issue/{issue_number}/body")
def get_issue_body(issue_number: int):
    """获取 Issue 正文（实时从 GitHub 拉取，用于弹窗显示）"""
    try:
        issue = _get_github_client().get_issue(issue_number)
        if not issue:
            raise HTTPException(status_code=404, detail="Issue not found")
        return {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "body": issue.get("body") or "",
            "state": issue.get("state"),
            "author": (issue.get("user") or {}).get("login"),
            "labels": [l.get("name") for l in issue.get("labels", []) if isinstance(l, dict)],
            "comments": issue.get("comments", 0),
            "created_at": issue.get("created_at"),
            "updated_at": issue.get("updated_at"),
            "url": issue.get("html_url"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"get_issue_body failed for #{issue_number}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/my-prs/{pr_number}/body")
def get_pr_body(pr_number: int):
    """获取 PR 正文和元信息（实时从 GitHub 拉取）"""
    try:
        pr = _get_github_client().get_pull(pr_number)
        if not pr:
            raise HTTPException(status_code=404, detail="PR not found")
        return {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "body": pr.get("body") or "",
            "state": pr.get("state"),
            "merged": bool(pr.get("merged")),
            "author": (pr.get("user") or {}).get("login"),
            "branch": (pr.get("head") or {}).get("ref"),
            "base_branch": (pr.get("base") or {}).get("ref"),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "changed_files": pr.get("changed_files", 0),
            "labels": [l.get("name") for l in pr.get("labels", []) if isinstance(l, dict)],
            "created_at": pr.get("created_at"),
            "updated_at": pr.get("updated_at"),
            "url": pr.get("html_url"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"get_pr_body failed for PR#{pr_number}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/my-prs/{pr_number}/diff")
def get_pr_diff(pr_number: int, db: Session = Depends(get_db)):
    """获取 PR 的 diff 内容（实时）"""
    try:
        diff = _get_github_client().get_pull_diff(pr_number)
        if not diff:
            raise HTTPException(status_code=404, detail="Diff not available")
        return {"diff": diff}
    except HTTPException:
        raise
    except Exception:
        logger.exception(f"get_pr_diff failed for PR#{pr_number}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/my-issues")
async def get_my_issues(
    state: str = Query("open", pattern="^(open|closed|all)$"),
    db: Session = Depends(get_db),
):
    """获取用户创建的 Issue 列表（从 SQLite 缓存读取，由 scheduler 同步）"""
    from app.models import UserIssue
    from app.config import Config
    if not Config.USERNAME:
        raise HTTPException(status_code=400, detail="GITHUB_USERNAME not configured")

    q = db.query(UserIssue)
    if state == "open":
        q = q.filter(UserIssue.state == "open")
    elif state == "closed":
        q = q.filter(UserIssue.state == "closed")

    issues = q.order_by(UserIssue.created_at.desc()).all()
    return [it.to_dict() for it in issues]
