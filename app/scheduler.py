"""
定时调度器 - 使用APScheduler定时拉取数据更新缓存

设计文档 DESIGN.md 285-298 行：
- 优先使用缓存数据，仅在必要时调用API
- 增量拉取而非全量
"""
import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Config
from app.database import SessionLocal
from app.models import Item, MyPR, Area, UserIssue, User, PersonalTask
from app.services.github_client import GitHubClient, DEFAULT_PER_PAGE
from app.services.area_mapper import AreaMapper

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Module-level singletons（避免在 job 中反复创建）
_github_client: Optional[GitHubClient] = None
_area_mapper: Optional[AreaMapper] = None

# 防止 trigger_refresh 并发触发多个同类型 job
_running_jobs: set = set()

# 用户 PR 详情并发拉取的线程数（GitHub 并发友好值，配合 GitHubClient 退避重试）
USER_PR_FETCH_WORKERS = 5
# 社区同步翻页数（issues/pulls 各翻 N 页，每页 DEFAULT_PER_PAGE=30）
COMMUNITY_FETCH_PAGES = 5


def _get_github_client() -> GitHubClient:
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client


def _get_area_mapper() -> AreaMapper:
    global _area_mapper
    if _area_mapper is None:
        _area_mapper = AreaMapper()
    return _area_mapper


def _parse_dt(s: str) -> Optional[datetime]:
    """解析 GitHub 时间字符串为 naive datetime（UTC）"""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, AttributeError):
        return None


def _map_pr_to_area(pr_number: int, github_client: GitHubClient, mapper: AreaMapper) -> Optional[str]:
    """根据 PR 的变更文件映射领域

    取所有变更文件，统计每个文件映射到的 area，返回出现次数最多的 area。
    比只看第一个文件更准确（多领域 PR 会归到变更最多的那个领域）。
    """
    try:
        files = github_client.get_pull_files(pr_number)
    except Exception as e:
        logger.warning(f"Failed to fetch files for PR #{pr_number}: {e}")
        return None
    if not files:
        return None

    area_counts = Counter()
    for f in files:
        path = f.get("filename") if isinstance(f, dict) else None
        if not path:
            continue
        area_id = mapper.map_to_area(path)
        if area_id:
            area_counts[area_id] += 1

    if area_counts:
        return area_counts.most_common(1)[0][0]
    return None


def _process_single_issue(db, issue: dict, mapper: AreaMapper, area_filter) -> None:
    """处理单个 issue 同步（独立可失败）"""
    if not isinstance(issue, dict):
        return
    labels = [l["name"] for l in issue.get("labels", []) if isinstance(l, dict)]
    area_id = mapper.classify_issue_by_labels(labels)

    if area_filter and area_id not in area_filter:
        return

    existing = db.query(Item).filter(
        Item.type == "issue",
        Item.number == issue["number"],
    ).first()

    if existing:
        existing.title = issue.get("title", existing.title)
        existing.state = issue.get("state", existing.state)
        existing.updated_at = _parse_dt(issue.get("updated_at"))
        existing.comments = issue.get("comments", existing.comments)
        existing.labels = json.dumps(labels)
        existing.area = area_id
        existing.body = issue.get("body") or existing.body  # body 可能很长，省一次 update
        existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(Item(
            type="issue",
            number=issue["number"],
            title=issue.get("title", ""),
            body=issue.get("body"),
            state=issue.get("state", "open"),
            labels=json.dumps(labels),
            area=area_id,
            author=(issue.get("user") or {}).get("login"),
            created_at=_parse_dt(issue.get("created_at")),
            updated_at=_parse_dt(issue.get("updated_at")),
            comments=issue.get("comments", 0),
            url=issue.get("html_url"),
        ))


def _process_single_pr_item(db, pr: dict, github_client: GitHubClient,
                            mapper: AreaMapper, area_filter) -> None:
    """处理单个 PR item 同步（独立可失败）

    性能策略：merged/closed PR 是稳态，仅刷新 last_sync；area 已有不重算
    """
    if not isinstance(pr, dict):
        return
    pr_number = pr.get("number")
    if pr_number is None:
        return

    pr_state = pr.get("state", "open")
    existing = db.query(Item).filter(
        Item.type == "pr",
        Item.number == pr_number,
    ).first()

    # 已存在且 area 已映射：只更新轻量字段，跳过文件 API
    if existing and existing.area:
        if area_filter and existing.area not in area_filter:
            return
        existing.title = pr.get("title", existing.title)
        existing.state = pr_state
        existing.updated_at = _parse_dt(pr.get("updated_at"))
        existing.comments = pr.get("comments", existing.comments)
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        existing.head_sha = head.get("sha", existing.head_sha)
        existing.base_sha = base.get("sha", existing.base_sha)
        existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
        return

    # 新 PR 或 area 缺失：需要调 files 映射
    area_id = _map_pr_to_area(pr_number, github_client, mapper)

    if area_filter and area_id not in area_filter:
        return

    head = pr.get("head") or {}
    base = pr.get("base") or {}

    if existing:
        existing.title = pr.get("title", existing.title)
        existing.body = pr.get("body") or existing.body
        existing.state = pr_state
        existing.updated_at = _parse_dt(pr.get("updated_at"))
        existing.comments = pr.get("comments", existing.comments)
        existing.head_sha = head.get("sha", existing.head_sha)
        existing.base_sha = base.get("sha", existing.base_sha)
        existing.area = area_id
        existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(Item(
            type="pr",
            number=pr_number,
            title=pr.get("title", ""),
            body=pr.get("body") or "",
            state=pr_state,
            labels=json.dumps([l["name"] for l in pr.get("labels", []) if isinstance(l, dict)]),
            area=area_id,
            author=(pr.get("user") or {}).get("login"),
            created_at=_parse_dt(pr.get("created_at")),
            updated_at=_parse_dt(pr.get("updated_at")),
            comments=pr.get("comments", 0),
            url=pr.get("html_url"),
            base_sha=base.get("sha"),
            head_sha=head.get("sha"),
        ))


def sync_areas():
    """同步领域定义（从 CODEOWNERS 解析结果写入 areas 表）"""
    job_id = "sync_areas"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        mapper = _get_area_mapper()
        all_areas = mapper.get_all_areas()
        db = SessionLocal()
        try:
            for area in all_areas:
                existing = db.query(Area).filter(Area.id == area["id"]).first()
                if existing:
                    existing.name = area.get("name", existing.name)
                    existing.paths = json.dumps(area.get("paths", []))
                    existing.description = area.get("description")
                    existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
                else:
                    db.add(Area(
                        id=area["id"],
                        name=area.get("name", area["id"]),
                        paths=json.dumps(area.get("paths", [])),
                        description=area.get("description"),
                        last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
                    ))
            db.commit()
            logger.info(f"Synced {len(all_areas)} areas")
        finally:
            db.close()
    except Exception:
        logger.exception("Error syncing areas")
    finally:
        _running_jobs.discard(job_id)


def sync_community_data():
    """同步社区数据（issues/PRs）到数据库

    同步策略：
    - 翻页拉取最新 N 个 open issue（按 created desc，每页 30，翻 COMMUNITY_FETCH_PAGES 页）
    - 增量拉取最近更新的 issue（since 窗口），更新已有 issue 的状态
    - 翻页拉取最新 N 个 open PR（按 updated desc）
    """
    job_id = "sync_community"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        logger.info("Starting community data sync...")

        github_client = _get_github_client()
        mapper = _get_area_mapper()
        db = SessionLocal()
        try:
            # 翻页拉最新 open issue（按 created desc），防止漏掉新 issue
            recent_issues: list = []
            for page in range(1, COMMUNITY_FETCH_PAGES + 1):
                page_items = github_client.get_issues(
                    state="open", sort="created", direction="desc", page=page
                ) or []
                if not page_items:
                    break
                recent_issues.extend(page_items)
                if len(page_items) < DEFAULT_PER_PAGE:
                    break  # 不足一页，说明没有更多了

            # 增量拉取最近更新的 issue（DB 已有数据时）
            existing_count = db.query(Item).count()
            incremental_issues = []
            if existing_count > 0:
                since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=int(Config.POLLING_INTERVAL * 3))
                since_iso = since.isoformat() + "Z"
                incremental_issues = github_client.get_issues(
                    state="open", sort="updated", direction="desc", since=since_iso
                ) or []

            # 合并去重（recent + incremental）
            seen_numbers = set()
            all_issues = []
            for it in recent_issues + incremental_issues:
                if not isinstance(it, dict):
                    continue
                num = it.get("number")
                if num and num not in seen_numbers:
                    seen_numbers.add(num)
                    all_issues.append(it)

            # 翻页拉最新 open PR（按 updated desc）
            pulls: list = []
            for page in range(1, COMMUNITY_FETCH_PAGES + 1):
                page_prs = github_client.get_pulls(
                    state="open", sort="updated", direction="desc", page=page
                ) or []
                if not page_prs:
                    break
                pulls.extend(page_prs)
                if len(page_prs) < DEFAULT_PER_PAGE:
                    break

            area_filter = Config.POLLING_AREAS or []
            if not area_filter:
                area_filter = None

            # GitHub /issues 端点会同时返回 PR（PR 是 issue 的子集），
            # 必须过滤掉带 pull_request 字段的项，否则 PR 会被当成 issue 存储
            real_issues = [it for it in all_issues if not it.get("pull_request")]

            for issue in real_issues:
                try:
                    _process_single_issue(db, issue, mapper, area_filter)
                except Exception:
                    logger.exception(f"Failed to process issue {issue.get('number')}, skipping")

            for pr in pulls:
                try:
                    _process_single_pr_item(db, pr, github_client, mapper, area_filter)
                except Exception:
                    logger.exception(f"Failed to process PR item {pr.get('number')}, skipping")

            db.commit()
            logger.info(
                f"Synced {len(real_issues)} issues and {len(pulls)} PRs "
                f"(filtered {len(all_issues) - len(real_issues)} PRs from issues)"
            )
        finally:
            db.close()

    except Exception:
        logger.exception("Error syncing community data")
    finally:
        _running_jobs.discard(job_id)


def _calc_ci_status(github_client: GitHubClient, sha: str) -> str:
    """根据 check runs + commit status 推导 CI 状态"""
    if not sha:
        return "unknown"
    return github_client.get_combined_ci(sha).get("status", "unknown")


def sync_user_prs():
    """同步所有已录入用户的 PR + Issue 数据

    遍历 users 表中所有有 github_id 的用户，
    为每个用户独立拉取其 PR 和 Issue 并写入 my_prs / user_issues 表。
    """
    job_id = "sync_user_prs"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        db = SessionLocal()
        try:
            users = db.query(User).filter(User.github_id.isnot(None), User.github_id != "").all()
        finally:
            db.close()

        if not users:
            logger.info("No users with github_id found, skipping user PR sync")
            return

        for user in users:
            _sync_single_user(user.github_id)

        # 清理已删除用户的旧数据
        _cleanup_orphaned_data()
    except Exception:
        logger.exception("user PR sync failed")
    finally:
        _running_jobs.discard(job_id)


def _sync_single_user(github_id: str):
    """同步单个用户的 PR 和 Issue 数据"""
    logger.info(f"Starting sync for user {github_id}...")
    github_client = _get_github_client()
    mapper = _get_area_mapper()
    db = SessionLocal()
    try:
        # 增量策略：首次全量拉，后续只拉 open + 最近更新的 PR
        existing_count = db.query(MyPR).filter(MyPR.github_id == github_id).count()
        is_first_sync = existing_count == 0

        if is_first_sync:
            user_prs = github_client.get_user_pulls(github_id, state="all") or []
        else:
            user_prs = github_client.get_user_pulls(github_id, state="open") or []
            closed_prs = github_client.get_user_pulls(github_id, state="closed") or []
            user_prs.extend(closed_prs[:20])

        def _fetch_one(pr):
            if not isinstance(pr, dict):
                return None
            pr_number = pr.get("number")
            if pr_number is None:
                return None
            try:
                return (pr_number, _fetch_user_pr_detail(pr, pr_number, github_client, mapper))
            except Exception:
                logger.exception(f"Failed to fetch user PR #{pr_number} for {github_id}, skipping")
                return None

        with ThreadPoolExecutor(max_workers=USER_PR_FETCH_WORKERS) as pool:
            results = list(pool.map(_fetch_one, user_prs))

        for item in results:
            if item is None:
                continue
            pr_number, detail = item
            if detail is None:
                continue
            try:
                _upsert_user_pr(db, detail, github_client, mapper, github_id)
            except Exception:
                logger.exception(f"Failed to upsert user PR #{pr_number} for {github_id}, skipping")

        # 同步用户创建的 Issue
        existing_issue_count = db.query(UserIssue).filter(UserIssue.github_id == github_id).count()
        is_first_issue_sync = existing_issue_count == 0
        issue_state = "all" if is_first_issue_sync else "open"

        user_issues = github_client.get_user_issues_with_body(github_id, state=issue_state) or []
        if not is_first_issue_sync:
            closed_issues = github_client.get_user_issues(github_id, state="closed") or []
            user_issues.extend(closed_issues[:20])

        issue_count = 0
        for issue in user_issues:
            if not isinstance(issue, dict):
                continue
            try:
                _process_single_user_issue(db, issue, mapper, github_id)
                issue_count += 1
            except Exception:
                logger.exception(f"Failed to process user issue #{issue.get('number')} for {github_id}, skipping")

        db.commit()
        logger.info(f"Synced {len(results)} PRs and {issue_count} issues for user {github_id}")
    except Exception:
        logger.exception(f"Sync failed for user {github_id}")
    finally:
        db.close()


def _cleanup_orphaned_data():
    """清理已从 users 表删除的用户的遗留数据"""
    db = SessionLocal()
    try:
        valid_github_ids = {u.github_id for u in db.query(User).filter(
            User.github_id.isnot(None), User.github_id != ""
        ).all()}

        orphaned_prs = db.query(MyPR).filter(
            MyPR.github_id.isnot(None), MyPR.github_id != "",
            ~MyPR.github_id.in_(valid_github_ids)
        ).all()
        for pr in orphaned_prs:
            db.delete(pr)

        orphaned_issues = db.query(UserIssue).filter(
            UserIssue.github_id.isnot(None), UserIssue.github_id != "",
            ~UserIssue.github_id.in_(valid_github_ids)
        ).all()
        for issue in orphaned_issues:
            db.delete(issue)

        db.commit()
        if orphaned_prs or orphaned_issues:
            logger.info(f"Cleaned up {len(orphaned_prs)} orphaned PRs and {len(orphaned_issues)} issues")
    except Exception:
        logger.exception("Failed to cleanup orphaned data")
    finally:
        db.close()


def _process_single_user_issue(db, issue: dict, mapper: AreaMapper, github_id: str = "") -> None:
    """把用户创建的 Issue 写入 user_issues 表"""
    issue_number = issue.get("number")
    if issue_number is None:
        return

    labels = [l["name"] for l in issue.get("labels", []) if isinstance(l, dict)]
    area_id = mapper.classify_issue_by_labels(labels)
    body = issue.get("body") or ""
    title = issue.get("title", "")

    existing = db.query(UserIssue).filter(UserIssue.number == issue_number, UserIssue.github_id == github_id).first()

    if existing:
        existing.title = title
        existing.state = issue.get("state", existing.state)
        existing.updated_at = _parse_dt(issue.get("updated_at"))
        existing.comments = issue.get("comments", existing.comments)
        existing.labels = json.dumps(labels)
        existing.body = body
        existing.area = area_id
        existing.github_id = github_id
        existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(UserIssue(
            number=issue_number,
            github_id=github_id,
            title=title,
            body=body,
            state=issue.get("state", "open"),
            author=(issue.get("user") or {}).get("login"),
            labels=json.dumps(labels),
            area=area_id,
            comments=issue.get("comments", 0),
            created_at=_parse_dt(issue.get("created_at")),
            updated_at=_parse_dt(issue.get("updated_at")),
            url=issue.get("html_url"),
        ))


def _fetch_user_pr_detail(pr: dict, pr_number: int,
                          github_client: GitHubClient, mapper: "AreaMapper") -> Optional[dict]:
    """纯拉取单个 user PR 的详情数据（不含 DB 访问，可在线程池并发调用）。

    性能策略：
    - open PR：完整刷新 CI/review/conflict 状态，需调 get_pull 拿 sha + mergeable
    - closed PR：从 Search API 的 pull_request.merged_at 判断 merged，不调额外 API
    - merged PR：稳态，同 closed 但 state 标记为 merged

    Returns:
        ``None`` 表示拉取失败（调用方应跳过，保留缓存原值）；否则返回 detail dict。
    """
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    pr_state = pr.get("state", "open")
    is_active = pr_state == "open"

    # Search API 返回的 PR 对象不含 head/base.sha、mergeable 字段。
    # 但 pull_request.merged_at 可以判断 merged 状态，不需要额外调 get_pull。
    # 只有 open PR 需要调 get_pull 拿 sha + mergeable 做冲突检测。
    full_pr = pr
    if is_active:
        fetched = github_client.get_pull(pr_number)
        if isinstance(fetched, dict):
            full_pr = fetched
            head = full_pr.get("head") or {}
            base = full_pr.get("base") or {}
        # fetched 为 None（rate-limit 耗尽/404）：用 Search API 的 pr 兜底，
        # sha/mergeable 会缺，冲突检测会跳过，但 title/state 仍可写。
    else:
        # closed PR：从 Search API 的 pull_request.merged_at 判断是否 merged
        pr_obj = pr.get("pull_request") or {}
        if pr_obj.get("merged_at"):
            pr_state = "merged"

    head_sha = head.get("sha") or ""
    base_ref = base.get("ref") or "main"

    # 仅对 open PR 调 status API（merged/closed 是稳态，省 rate limit）
    if is_active:
        ci_status = _calc_ci_status(github_client, head_sha)
    else:
        ci_status = "pass"  # merged/closed PR 默认 CI 通过

    # 冲突检测：
    # - behind_count 用 Compare API（base_ref...head_sha）
    # - mergeable 用 PR 对象的字段（Compare API 响应里没有 mergeable）
    conflict_commits = 0
    conflict_detected = False
    if is_active and head_sha:
        # 用 base ref（如 main）而非 base sha：base sha 是 PR 创建时的快照，
        # 比对不到后续 main 的推进，behind_by 会一直为 0。
        compare = github_client.compare_branches(base_ref, head_sha) or {}
        if isinstance(compare, dict):
            conflict_commits = int(compare.get("behind_by") or 0)
        else:
            conflict_commits = 0
        # mergeable / mergeable_state 只存在于 PR 对象
        mergeable = full_pr.get("mergeable")
        mergeable_state = full_pr.get("mergeable_state")
        # behind>0 且明确不可合并才算冲突；
        # mergeable=None 表示 GitHub 还在算，不当作冲突
        if conflict_commits > 0 and mergeable is False:
            conflict_detected = True
        # dirty 状态也是冲突信号（即使 behind 未报）
        if mergeable_state == "dirty":
            conflict_detected = True

    return {
        "pr_number": pr_number,
        "pr": pr,
        "full_pr": full_pr,
        "pr_state": pr_state,
        "head": head,
        "base": base,
        "ci_status": ci_status,
        "conflict_commits": conflict_commits,
        "conflict_detected": conflict_detected,
        "area_id": None,  # 占位；写库阶段若 Item 缺 area 才补算
    }


def _upsert_user_pr(db, detail: dict, github_client: GitHubClient,
                    mapper: "AreaMapper", github_id: str = "") -> None:
    """把 _fetch_user_pr_detail 的结果写入 my_prs（串行，DB 非线程安全）。

    领域映射在此阶段做：先查 Item 缓存，缺失才调 _map_pr_to_area（会打 files API，
    此处是串行的单次调用，不并发，避免 SQLite session 跨线程问题）。
    """
    pr_number = detail["pr_number"]
    pr = detail["pr"]
    full_pr = detail["full_pr"]
    pr_state = detail["pr_state"]
    head = detail["head"]
    ci_status = detail["ci_status"]
    conflict_commits = detail["conflict_commits"]
    conflict_detected = detail["conflict_detected"]

    # 领域映射（首次或缺失时）
    existing = db.query(MyPR).filter(MyPR.pr_number == pr_number, MyPR.github_id == github_id).first()
    area_id = detail.get("area_id")
    if existing:
        item = db.query(Item).filter(Item.type == "pr", Item.number == pr_number).first()
        area_id = item.area if item else None
    if not area_id:
        area_id = _map_pr_to_area(pr_number, github_client, mapper)
        if area_id:
            item = db.query(Item).filter(Item.type == "pr", Item.number == pr_number).first()
            if item:
                item.area = area_id
                item.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)

    if existing:
        existing.title = pr.get("title", existing.title)
        existing.state = pr_state
        existing.branch = head.get("ref", existing.branch)
        existing.base_sha = (detail.get("base") or {}).get("sha", existing.base_sha)
        existing.head_sha = head.get("sha", existing.head_sha)
        existing.ci_status = ci_status
        existing.conflict_detected = conflict_detected
        existing.conflict_commits = conflict_commits
        existing.github_id = github_id
        if not existing.created_at:
            existing.created_at = _parse_dt(pr.get("created_at"))
        existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(MyPR(
            pr_number=pr_number,
            github_id=github_id,
            title=pr.get("title"),
            state=pr_state,
            branch=head.get("ref"),
            base_sha=(detail.get("base") or {}).get("sha"),
            head_sha=head.get("sha"),
            ci_status=ci_status,
            conflict_detected=conflict_detected,
            conflict_commits=conflict_commits,
            created_at=_parse_dt(pr.get("created_at")),
            last_sync=datetime.now(timezone.utc).replace(tzinfo=None),
        ))


def _refresh_personal_task_refs():
    """刷新所有 personal_tasks（含子任务）中 related_refs 的 state 字段

    历史数据中 related_refs 可能缺少 state 字段（open/closed/merged），
    此定时任务逐个查询 GitHub API 补全。
    """
    import requests
    from app.config import Config as AppConfig

    headers = AppConfig.get_github_headers()
    db = SessionLocal()
    try:
        tasks = db.query(PersonalTask).filter(
            PersonalTask.related_refs.isnot(None),
        ).all()
        updated = 0
        for task in tasks:
            refs = task.related_refs or []
            changed = False
            for ref in refs:
                if ref.get("state") or not ref.get("number"):
                    continue
                number = ref["number"]
                repo_path = f"vllm-project/{ref.get('repo', 'vllm')}"
                if ref.get("type") == "pr":
                    url = f"https://api.github.com/repos/{repo_path}/pulls/{number}"
                else:
                    url = f"https://api.github.com/repos/{repo_path}/issues/{number}"
                try:
                    resp = requests.get(url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        data = resp.json()
                        state = data.get("state", "unknown")
                        if ref["type"] == "pr" and state == "closed" and data.get("merged", False):
                            state = "merged"
                        ref["state"] = state
                        changed = True
                except Exception:
                    continue
            if changed:
                task.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                updated += 1
        db.commit()
        if updated:
            logger.info(f"Refreshed state for {updated} personal tasks' refs (including subtasks)")
    except Exception:
        logger.exception("Failed to refresh personal task refs")
    finally:
        db.close()


def start_scheduler():
    """启动定时调度器

    ⚠️ 必须单进程运行：多进程下每个进程都会启动独立的 BackgroundScheduler，
    导致多个进程同时执行同步任务，造成 SQLite 数据竞争。
    """
    if scheduler.running:
        return

    # 防御性检查：如果检测到多 worker 环境，打印告警
    # UVICORN_WORKERS 是 Dockerfile 中显式传入的，但用户也可能通过其他方式设置
    import os as _os
    _workers = _os.environ.get("UVICORN_WORKERS") or _os.environ.get("WEB_CONCURRENCY")
    if _workers and _workers != "1":
        logger.warning(
            f"Detected UVICORN_WORKERS={_workers}, but APScheduler requires single-process mode. "
            "Multiple workers will cause duplicate sync jobs and data races. "
            "Set workers=1 or use a single-replica deployment."
        )

    scheduler.add_job(
        sync_areas,
        trigger=IntervalTrigger(minutes=Config.POLLING_INTERVAL),
        id="sync_areas",
        name="Sync Areas (CODEOWNERS)",
        replace_existing=True,
    )
    scheduler.add_job(
        sync_community_data,
        trigger=IntervalTrigger(minutes=Config.POLLING_INTERVAL),
        id="sync_community",
        name="Sync Community Data",
        replace_existing=True,
    )
    scheduler.add_job(
        sync_user_prs,
        trigger=IntervalTrigger(minutes=Config.POLLING_INTERVAL),
        id="sync_user_prs",
        name="Sync User PRs",
        replace_existing=True,
    )

    # 学习文章 - 代码仓库同步（仅在配置了 REPOS 时启用）
    if Config.REPOS:
        scheduler.add_job(
            sync_all_repos_job,
            trigger=IntervalTrigger(minutes=Config.CODE_SYNC_INTERVAL),
            id="sync_all_repos",
            name="Sync All Repo Code",
            replace_existing=True,
        )

        scheduler.add_job(
            sync_file_change_history_job,
            trigger=IntervalTrigger(hours=6),  # 每 6 小时同步一次（增量同步，不浪费配额）
            id="sync_file_history",
            name="Sync File Change History",
            replace_existing=True,
        )

    # 数据清理定时任务（每天执行一次）
    cleanup_interval = int(getattr(Config, 'CLEANUP_INTERVAL', 24))
    scheduler.add_job(
        cleanup_old_data,
        trigger=IntervalTrigger(hours=cleanup_interval),
        id="cleanup_old_data",
        name="Cleanup Old Data",
        replace_existing=True,
    )

    # 个人任务关联引用状态刷新（每 6 小时一次）
    scheduler.add_job(
        _refresh_personal_task_refs,
        trigger=IntervalTrigger(hours=6),
        id="refresh_personal_task_refs",
        name="Refresh Personal Task Ref States",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(f"Scheduler started with interval {Config.POLLING_INTERVAL} minutes")

    # 启动时立即在后台线程跑一轮，让缓存快速可用
    # 不在主线程同步调用，否则会阻塞 FastAPI lifespan 导致服务无法访问
    import threading
    def _initial_sync():
        try:
            sync_areas()
            sync_community_data()
            sync_user_prs()
            if Config.REPOS:
                sync_all_repos_job()
            _refresh_personal_task_refs()
        except Exception:
            logger.exception("Initial sync failed (will retry on schedule)")
    threading.Thread(target=_initial_sync, daemon=True, name="initial-sync").start()
    logger.info("Initial sync scheduled in background thread")


def trigger_refresh() -> dict:
    """异步触发一次完整同步（不阻塞 API 请求）

    Returns:
        {"triggered": bool, "already_running": bool, "jobs": [job_ids]}
    """
    if not scheduler.running:
        return {"triggered": False, "reason": "scheduler not running", "jobs": []}

    job_ids = ["sync_areas", "sync_community", "sync_user_prs"]
    triggered = []
    for jid in job_ids:
        job = scheduler.get_job(jid)
        if job is None:
            continue
        # APScheduler 的 modify_next_run_time 把下一次触发设为立即
        try:
            job.modify(next_run_time=datetime.now(timezone.utc).replace(tzinfo=None))
            triggered.append(jid)
        except Exception as e:
            logger.warning(f"Failed to trigger job {jid}: {e}")

    return {
        "triggered": len(triggered) > 0,
        "jobs": triggered,
    }


def get_sync_status() -> dict:
    """获取 scheduler 和各 job 状态（健康检查用）"""
    if not scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return {"running": True, "jobs": jobs}


def stop_scheduler():
    """停止定时调度器"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


# ===== 学习文章定时任务 =====


def sync_all_repos_job():
    """定时任务：同步所有仓库代码到 LocalCodeCache，然后增量更新知识库"""
    job_id = "sync_all_repos"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        from app.services.repo_manager import RepoManager

        if not Config.REPOS:
            logger.warning("No REPOS configured, skipping code sync")
            return

        manager = RepoManager()
        has_changes = False
        for repo_name in Config.REPOS:
            try:
                result = manager.pull_and_sync(repo_name)
                logger.info(f"Repo {repo_name} synced: {result}")
                if result.get("created", 0) > 0 or result.get("updated", 0) > 0:
                    has_changes = True
            except Exception:
                logger.exception(f"Error syncing repo {repo_name}")

        # 对所有受影响文件做行号越界检查
        try:
            manager.validate_all_refs()
        except Exception:
            logger.exception("Error validating refs after sync")

        # 如果仓库有变更，增量更新知识库
        if has_changes:
            try:
                from app.services.memory_service import MemoryService
                mem = MemoryService()
                stats = mem.build_code_knowledge()
                logger.info(f"Knowledge base incremental build: {stats}")
            except Exception:
                logger.exception("Error updating knowledge base after repo sync")
    finally:
        _running_jobs.discard(job_id)


def sync_file_change_history_job():
    """定时任务：同步文件变更历史到 FileChangeHistory 表

    增量策略：只同步最近 6 小时内未同步过的 PR（last_sync < now - 6h），
    避免每次全量重刷所有 PR 的变更文件列表。
    """
    job_id = "sync_file_history"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        from app.models import FileChangeHistory
        from app.services.github_client import GitHubClient

        client = GitHubClient()
        db = SessionLocal()
        try:
            # 只同步最近 6 小时内未同步过的 PR（增量）
            sync_threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=6)

            open_prs = db.query(MyPR).filter(
                MyPR.state == "open",
                MyPR.last_sync < sync_threshold,
            ).all()
            # 最近合并的 PR（前 30 个，同样只同步过期的）
            merged_prs = db.query(MyPR).filter(
                MyPR.state == "merged",
                MyPR.last_sync < sync_threshold,
            ).order_by(MyPR.last_sync.asc()).limit(30).all()

            all_prs = open_prs + merged_prs
            if not all_prs:
                logger.debug("No PRs need file change history sync (all recently synced)")
                return

            synced_count = 0
            for pr in all_prs:
                try:
                    files = client.get_pull_files(pr.pr_number)
                    if not files:
                        continue

                    # 清除该 PR 的旧记录，重新写入
                    db.query(FileChangeHistory).filter(
                        FileChangeHistory.pr_number == pr.pr_number).delete()
                    db.flush()

                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    for f in files:
                        fname = f.get("filename") if isinstance(f, dict) else None
                        if not fname:
                            continue
                        db.add(FileChangeHistory(
                            repo="vllm",
                            file_path=fname,
                            pr_number=pr.pr_number,
                            pr_title=pr.title,
                            pr_state=pr.state,
                            additions=f.get("additions", 0) if isinstance(f, dict) else 0,
                            deletions=f.get("deletions", 0) if isinstance(f, dict) else 0,
                            change_status=f.get("status", "modified") if isinstance(f, dict) else "modified",
                            last_synced_at=now,
                        ))
                    synced_count += 1
                except Exception:
                    logger.exception(f"Failed to sync file changes for PR #{pr.pr_number}")
                    continue

                # 每 10 个 PR 提交一次，避免大事务
                if synced_count % 10 == 0:
                    db.commit()

            db.commit()
            logger.info(f"File change history synced for {synced_count} PRs (skipped {len(all_prs) - synced_count} with no files)")
        except Exception:
            logger.exception("Error syncing file change history")
        finally:
            db.close()
    finally:
        _running_jobs.discard(job_id)


def cleanup_old_data():
    """定时清理过期数据，防止数据库无限增长

    清理策略（由 Config 控制）：
    - items 表：删除 closed/merged 超过 DATA_RETENTION_DAYS 天的记录
    - file_change_history 表：删除超过 DATA_RETENTION_DAYS 天未更新的记录
    - ai_cache 表：保留最近 AI_CACHE_MAX_RECORDS 条，删除更早的
    - intelligence_reports 表：删除 failed 状态且超过 30 天的记录
    - 每周执行一次 VACUUM 回收磁盘空间
    """
    from app.models import FileChangeHistory, AICache, IntelligenceReport
    from sqlalchemy import text

    db = SessionLocal()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        retention_days = int(getattr(Config, 'DATA_RETENTION_DAYS', 90))
        ai_cache_max = int(getattr(Config, 'AI_CACHE_MAX_RECORDS', 1000))
        cutoff = now - timedelta(days=retention_days)

        # 1. 清理 items 表：删除 closed/merged 超过 retention_days 的记录
        deleted_items = db.query(Item).filter(
            Item.state.in_(["closed", "merged"]),
            Item.updated_at < cutoff,
        ).delete(synchronize_session=False)
        if deleted_items:
            logger.info(f"Cleaned {deleted_items} old items (state=closed/merged, older than {retention_days}d)")

        # 2. 清理 file_change_history 表：删除超过 retention_days 天未更新的记录
        deleted_fch = db.query(FileChangeHistory).filter(
            FileChangeHistory.last_synced_at < cutoff,
        ).delete(synchronize_session=False)
        if deleted_fch:
            logger.info(f"Cleaned {deleted_fch} old file_change_history records")

        # 3. 清理 ai_cache 表：保留最近 AI_CACHE_MAX_RECORDS 条
        total_cache = db.query(AICache).count()
        if total_cache > ai_cache_max:
            subq = db.query(AICache.created_at).order_by(
                AICache.created_at.desc()
            ).offset(ai_cache_max).limit(1).subquery()
            deleted_cache = db.query(AICache).filter(
                AICache.created_at < subq.c.created_at
            ).delete(synchronize_session=False)
            logger.info(f"Cleaned {deleted_cache} old ai_cache records (kept {ai_cache_max})")
        else:
            deleted_cache = 0
            logger.debug(f"ai_cache has {total_cache} records (max {ai_cache_max}), no cleanup needed")

        # 4. 清理 intelligence_reports 表：删除 failed 状态超过 30 天的
        failed_cutoff = now - timedelta(days=30)
        deleted_reports = db.query(IntelligenceReport).filter(
            IntelligenceReport.status == "failed",
            IntelligenceReport.created_at < failed_cutoff,
        ).delete(synchronize_session=False)
        if deleted_reports:
            logger.info(f"Cleaned {deleted_reports} failed intelligence_reports")

        db.commit()

        # 5. 每周执行一次 VACUUM（每天清理一次，7 天一次 VACUUM）
        _vacuum_counter = getattr(cleanup_old_data, "_vacuum_counter", 0)
        cleanup_old_data._vacuum_counter = _vacuum_counter + 1
        if cleanup_old_data._vacuum_counter >= 7:
            cleanup_old_data._vacuum_counter = 0
            logger.info("Running VACUUM to reclaim disk space...")
            db.execute(text("VACUUM"))
            logger.info("VACUUM completed")

        logger.info(f"Cleanup completed: {deleted_items} items, {deleted_fch} file_changes, "
                     f"{deleted_cache} ai_cache, {deleted_reports} reports")
    except Exception:
        logger.exception("Error during data cleanup")
        db.rollback()
    finally:
        db.close()


