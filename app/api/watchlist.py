"""
Watchlist API - 特别关注列表
用户手动收藏的 issue/PR，持久化到 SQLite。
"""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Watchlist
from app.services.github_client import GitHubClient
from app.services.area_mapper import AreaMapper

logger = logging.getLogger(__name__)
router = APIRouter()


class WatchlistAddRequest(BaseModel):
    number: int
    item_type: str  # 'issue' or 'pr'
    title: str = ""
    url: str = ""
    area: str = ""  # 领域 ID
    issue_type: str = ""  # issue 分类（bug/rfc/...），PR 可为空
    state: str = ""  # 'open' / 'closed' / 'merged'
    note: str = ""  # 用户备注
    assignee_id: Optional[int] = None  # 责任人
    repo: str = ""  # 完整 owner/repo，必填

    @field_validator("item_type")
    @classmethod
    def validate_item_type(cls, v):
        if v not in ("issue", "pr"):
            raise ValueError("item_type must be 'issue' or 'pr'")
        return v


class AddByNumberRequest(BaseModel):
    """通过 issue/PR 编号手动添加到特别关注

    item_type 可选（不传则自动从 GitHub 推断是 issue 还是 PR）。
    repo 必填，指定仓库名称（如 vllm、sglang），从 RepoCache 中查找。
    """
    number: int
    item_type: str = ""  # 'issue' or 'pr'，留空自动推断
    note: str = ""  # 用户备注
    assignee_id: Optional[int] = None  # 责任人
    repo: str  # 仓库名称（如 vllm、sglang），必填

    @model_validator(mode="after")
    def validate_number(self):
        if self.number <= 0:
            raise ValueError("number must be positive")
        return self


def _classify_issue_type(title: str) -> Optional[str]:
    """从 issue title 前缀推断分类（与前端 issueType 逻辑一致）"""
    if not title:
        return None
    m = re.match(r"^\[([^\]]+)\]", title.strip(), re.I)
    if not m:
        return "other"
    raw = m.group(1).lower()
    mapping = {
        "bug": "bug", "bug报告": "bug", "缺陷": "bug",
        "rfc": "rfc", "proposal": "rfc", "提案": "rfc",
        "feature": "feature", "feature request": "feature", "新功能": "feature", "需求": "feature",
        "usage": "usage", "question": "usage", "help wanted": "usage", "问答": "usage", "求助": "usage",
        "installation": "installation", "install": "installation", "安装": "installation",
        "performance": "performance", "perf": "performance",
        "doc": "doc", "docs": "doc", "documentation": "doc", "文档": "doc",
        "ci": "ci", "build": "ci",
        "refactor": "refactor", "cleanup": "refactor",
    }
    return mapping.get(raw, raw)


@router.get("")
async def list_watchlist(db: Session = Depends(get_db)):
    """获取特别关注列表（按添加时间倒序），含关联任务信息"""
    from app.models import PersonalTask

    items = db.query(Watchlist).order_by(Watchlist.added_at.desc()).all()
    result = []
    for w in items:
        d = w.to_dict()
        # 查询关联的任务
        number = w.number
        item_type = w.item_type  # 'issue' or 'pr'
        repo_short = (w.repo or "").split("/")[-1] if w.repo else ""
        # 在 personal_tasks 的 related_refs JSON 中查找匹配
        tasks = db.query(PersonalTask).filter(
            PersonalTask.related_refs.isnot(None),
        ).all()
        linked_tasks = []
        for t in tasks:
            refs = t.related_refs or []
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                if ref.get("number") != number or ref.get("type") != item_type:
                    continue
                # repo 维度匹配：related_refs 存短名，Watchlist 存完整 owner/repo
                ref_repo = ref.get("repo", "")
                if ref_repo and repo_short and ref_repo != repo_short:
                    continue
                linked_tasks.append({
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "priority": t.priority,
                    "parent_id": t.parent_id,
                })
                break
        if linked_tasks:
            d["linked_tasks"] = linked_tasks
        result.append(d)
    return result


@router.post("")
async def add_to_watchlist(req: WatchlistAddRequest, db: Session = Depends(get_db)):
    """加入特别关注（幂等：已存在则更新元信息）"""
    if req.item_type not in ("issue", "pr"):
        raise HTTPException(status_code=400, detail="item_type must be 'issue' or 'pr'")
    if not req.repo:
        raise HTTPException(status_code=400, detail="repo is required")
    full_repo = req.repo
    existing = db.query(Watchlist).filter(
        Watchlist.repo == full_repo,
        Watchlist.number == req.number,
        Watchlist.item_type == req.item_type,
    ).first()
    if existing:
        # 更新元信息（title/area/issue_type/state 可能变化）
        existing.title = req.title or existing.title
        existing.url = req.url or existing.url
        existing.area = req.area or existing.area
        existing.issue_type = req.issue_type or existing.issue_type
        existing.state = req.state or existing.state
        if req.note:
            existing.note = req.note
        if req.assignee_id is not None:
            existing.assignee_id = req.assignee_id
        db.commit()
        db.refresh(existing)
        return existing.to_dict()
    w = Watchlist(
        repo=full_repo,
        number=req.number,
        item_type=req.item_type,
        title=req.title,
        url=req.url,
        area=req.area or None,
        issue_type=req.issue_type or None,
        state=req.state or None,
        note=req.note or None,
        assignee_id=req.assignee_id,
        added_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w.to_dict()


@router.post("/add-by-number")
def add_by_number(req: AddByNumberRequest, db: Session = Depends(get_db)):
    """通过编号从 GitHub 拉取信息后加入特别关注

    自动填充 title/url/state/area/issue_type 等元信息。
    item_type 可选：不传则自动从 GitHub 推断是 issue 还是 PR。
    repo 必填，从 RepoCache 解析完整 owner/repo。
    用 def（非 async）避免同步 GitHub API 调用阻塞事件循环。
    """
    if req.number <= 0:
        raise HTTPException(status_code=400, detail="number must be positive")

    # 解析仓库的 owner/name
    # 从 RepoCache 中查找指定仓库
    from app.models import RepoCache
    repo_cache = db.query(RepoCache).filter(
        RepoCache.repo == req.repo,
        RepoCache.status == "active",
    ).first()
    if not repo_cache:
        raise HTTPException(status_code=400, detail=f"Repo '{req.repo}' not found")
    # 从 clone_url 解析 owner/name，如 https://github.com/owner/repo.git
    clone_url = repo_cache.clone_url
    if clone_url.endswith('.git'):
        clone_url = clone_url[:-4]
    # 提取 owner/repo 路径
    parts = clone_url.rstrip('/').split('/')
    if len(parts) >= 2:
        repo_owner = parts[-2]
        repo_name = parts[-1]
    else:
        raise HTTPException(status_code=500, detail=f"Cannot parse clone_url: {clone_url}")
    full_repo = f"{repo_owner}/{repo_name}"

    client = GitHubClient()

    # 生成 repo 特定的 URL
    def _repo_pulls_url(number: int) -> str:
        return f"https://github.com/{repo_owner}/{repo_name}/pull/{number}"

    def _repo_issues_url(number: int) -> str:
        return f"https://github.com/{repo_owner}/{repo_name}/issues/{number}"

    title = ""
    url = ""
    state = ""
    area = None
    issue_type = None
    item_type = req.item_type

    try:
        mapper = AreaMapper(full_repo)
        if item_type == "pr":
            # 用户明确指定 PR
            pr = client.get_pull(req.number, repo=full_repo)
            if not pr:
                raise HTTPException(status_code=404, detail=f"PR #{req.number} not found")
            title = pr.get("title", "")
            state = "merged" if pr.get("merged_at") else pr.get("state", "open")
            url = pr.get("html_url", _repo_pulls_url(req.number))
            try:
                files = client.get_pull_files(req.number, repo=full_repo) or []
                for f in files:
                    if isinstance(f, dict):
                        a = mapper.map_to_area(f.get("filename", ""))
                        if a:
                            area = a
                            break
            except Exception:
                pass
        elif item_type == "issue":
            # 用户明确指定 Issue
            issue = client.get_issue(req.number, repo=full_repo)
            if not issue:
                raise HTTPException(status_code=404, detail=f"Issue #{req.number} not found")
            title = issue.get("title", "")
            state = issue.get("state", "open")
            url = issue.get("html_url", _repo_issues_url(req.number))
            issue_type = _classify_issue_type(title) or "other"
            try:
                labels = [l.get("name", "") for l in issue.get("labels", []) if isinstance(l, dict)]
                area = mapper.classify_issue_by_labels(labels)
            except Exception:
                pass
        else:
            # 自动推断：先查 PR，再查 Issue
            pr = client.get_pull(req.number, repo=full_repo)
            if pr:
                item_type = "pr"
                title = pr.get("title", "")
                state = "merged" if pr.get("merged_at") else pr.get("state", "open")
                url = pr.get("html_url", _repo_pulls_url(req.number))
                try:
                    files = client.get_pull_files(req.number, repo=full_repo) or []
                    for f in files:
                        if isinstance(f, dict):
                            a = mapper.map_to_area(f.get("filename", ""))
                            if a:
                                area = a
                                break
                except Exception:
                    pass
            else:
                issue = client.get_issue(req.number, repo=full_repo)
                if not issue:
                    raise HTTPException(status_code=404, detail=f"#{req.number} not found as PR or Issue")
                # GitHub /issues 端点也会返回 PR（PR 是 Issue 的子类型），
                # 如果返回值含 pull_request 字段，说明这是 PR
                if issue.get("pull_request"):
                    item_type = "pr"
                    title = issue.get("title", "")
                    state = "merged" if issue.get("pull_request", {}).get("merged_at") else issue.get("state", "open")
                    url = issue.get("html_url", _repo_pulls_url(req.number))
                else:
                    item_type = "issue"
                    title = issue.get("title", "")
                    state = issue.get("state", "open")
                    url = issue.get("html_url", _repo_issues_url(req.number))
                    issue_type = _classify_issue_type(title) or "other"
                try:
                    labels = [l.get("name", "") for l in issue.get("labels", []) if isinstance(l, dict)]
                    area = mapper.classify_issue_by_labels(labels)
                except Exception:
                    pass
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching item from GitHub")
        raise HTTPException(status_code=502, detail=f"Failed to fetch from GitHub: {e}")

    # 幂等：已存在则直接返回（按 repo + number + item_type 匹配）
    existing = db.query(Watchlist).filter(
        Watchlist.repo == full_repo,
        Watchlist.number == req.number,
        Watchlist.item_type == item_type,
    ).first()
    if existing:
        return existing.to_dict()

    w = Watchlist(
        repo=full_repo,
        number=req.number,
        item_type=item_type,
        title=title,
        url=url,
        area=area,
        issue_type=issue_type,
        state=state,
        note=req.note or None,
        assignee_id=req.assignee_id,
        added_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(w)
    db.commit()
    db.refresh(w)
    return w.to_dict()


@router.delete("/{item_type}/{number}")
async def remove_from_watchlist(item_type: str, number: int,
                                repo: Optional[str] = None,
                                db: Session = Depends(get_db)):
    """从特别关注移除"""
    if item_type not in ("issue", "pr"):
        raise HTTPException(status_code=400, detail="item_type must be 'issue' or 'pr'")
    if not repo:
        raise HTTPException(status_code=400, detail="repo is required")
    full_repo = repo
    w = db.query(Watchlist).filter(
        Watchlist.repo == full_repo,
        Watchlist.number == number,
        Watchlist.item_type == item_type,
    ).first()
    if not w:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    db.delete(w)
    db.commit()
    return {"removed": True}


@router.get("/check/{item_type}/{number}")
async def check_watchlist(item_type: str, number: int,
                          repo: Optional[str] = None,
                          db: Session = Depends(get_db)):
    """检查某 item 是否在特别关注列表"""
    if not repo:
        raise HTTPException(status_code=400, detail="repo is required")
    full_repo = repo
    w = db.query(Watchlist).filter(
        Watchlist.repo == full_repo,
        Watchlist.number == number,
        Watchlist.item_type == item_type,
    ).first()
    return {"watched": w is not None}


class UpdateWatchlistItemRequest(BaseModel):
    """更新关注项信息（备注、责任人）"""
    note: str = ""
    assignee_id: Optional[int] = None


@router.put("/{item_type}/{number}/note")
async def update_watchlist_item(item_type: str, number: int, req: UpdateWatchlistItemRequest,
                                repo: Optional[str] = None,
                                db: Session = Depends(get_db)):
    """更新特别关注项的备注和责任人"""
    if item_type not in ("issue", "pr"):
        raise HTTPException(status_code=400, detail="item_type must be 'issue' or 'pr'")
    if not repo:
        raise HTTPException(status_code=400, detail="repo is required")
    full_repo = repo
    w = db.query(Watchlist).filter(
        Watchlist.repo == full_repo,
        Watchlist.number == number,
        Watchlist.item_type == item_type,
    ).first()
    if not w:
        raise HTTPException(status_code=404, detail="Not in watchlist")
    w.note = req.note or None
    if req.assignee_id is not None:
        w.assignee_id = req.assignee_id
    db.commit()
    db.refresh(w)
    return w.to_dict()
