"""
定时调度器 - 使用APScheduler定时拉取数据更新缓存

设计文档 DESIGN.md 285-298 行：
- 优先使用缓存数据，仅在必要时调用API
- 增量拉取而非全量
"""
import json
import logging
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Config
from app.database import SessionLocal
from app.models import Item, MyPR, Area, UserIssue, User, PersonalTask, RepoCache
from app.services.github_client import GitHubClient, DEFAULT_PER_PAGE
from app.services.area_mapper import AreaMapper

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Module-level singletons（避免在 job 中反复创建）
_github_client: Optional[GitHubClient] = None
_area_mappers: dict = {}  # repo -> AreaMapper (per-repo 缓存)

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


def _get_area_mapper(repo: str) -> AreaMapper:
    """按仓库懒加载并缓存 AreaMapper（per-repo）"""
    if repo not in _area_mappers:
        _area_mappers[repo] = AreaMapper(repo)
    return _area_mappers[repo]


def _clone_url_to_full_repo(clone_url: str) -> str:
    """从 clone_url 提取完整 owner/repo（如 https://github.com/vllm-project/vllm.git -> vllm-project/vllm）"""
    url = clone_url
    if url.endswith('.git'):
        url = url[:-4]
    parts = url.rstrip('/').split('/')
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return ""


def _get_tracked_repos() -> list:
    """返回所有 tracked=True 的仓库列表，元素为 (short_name, full_repo)"""
    db = SessionLocal()
    try:
        repos = db.query(RepoCache).filter(
            RepoCache.status == "active",
            RepoCache.tracked == True,  # noqa: E712
        ).all()
        return [(r.repo, _clone_url_to_full_repo(r.clone_url)) for r in repos]
    finally:
        db.close()


def _parse_dt(s: str) -> Optional[datetime]:
    """解析 GitHub 时间字符串为 naive datetime（UTC）"""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, AttributeError):
        return None


def _map_pr_to_area(pr_number: int, github_client: GitHubClient,
                    repo: str) -> Optional[str]:
    """根据 PR 的变更文件映射领域（per-repo）。

    取所有变更文件，统计每个文件映射到的 area，返回出现次数最多的 area。
    比只看第一个文件更准确（多领域 PR 会归到变更最多的那个领域）。

    使用该仓库专属的 AreaMapper：无领域定义配置的仓库 area_map 为空，
    map_to_area 自然返回 None，不需要任何短路判定。
    """
    mapper = _get_area_mapper(repo)
    try:
        files = github_client.get_pull_files(pr_number, repo=repo)
    except Exception as e:
        logger.warning(f"Failed to fetch files for PR #{pr_number} ({repo}): {e}")
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


def _process_single_issue(db, issue: dict, mapper: AreaMapper, repo: str) -> None:
    """处理单个 issue 同步（独立可失败）"""
    if not isinstance(issue, dict):
        return
    labels = [l["name"] for l in issue.get("labels", []) if isinstance(l, dict)]
    area_id = mapper.classify_issue_by_labels(labels)

    existing = db.query(Item).filter(
        Item.repo == repo,
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
            repo=repo,
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
                            mapper: AreaMapper, repo: str) -> None:
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
        Item.repo == repo,
        Item.type == "pr",
        Item.number == pr_number,
    ).first()

    # 已存在且 area 已映射：只更新轻量字段，跳过文件 API
    if existing and existing.area:
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
    area_id = _map_pr_to_area(pr_number, github_client, repo)

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
            repo=repo,
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
    """同步领域定义（从 CODEOWNERS 解析结果写入 areas 表）

    遍历所有 tracked 仓库，按各自 AreaMapper 同步领域定义。
    无领域定义配置的仓库跳过。
    """
    if not Config.GITHUB_SYNC_ENABLED:
        return
    job_id = "sync_areas"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        tracked = _get_tracked_repos()
        db = SessionLocal()
        try:
            for short_name, full_repo in tracked:
                mapper = _get_area_mapper(full_repo)
                if not mapper.has_area_config:
                    continue
                all_areas = mapper.get_all_areas()
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
            logger.info(f"Synced areas across {len(tracked)} tracked repos")
        finally:
            db.close()
    except Exception:
        logger.exception("Error syncing areas")
    finally:
        _running_jobs.discard(job_id)


def sync_community_data():
    """同步社区数据（issues/PRs）到数据库

    遍历所有 tracked=True 的仓库，逐个同步 issue/PR。
    同步策略：
    - 翻页拉取最新 N 个 open issue（按 created desc，每页 30，翻 COMMUNITY_FETCH_PAGES 页）
    - 增量拉取最近更新的 issue（since 窗口），更新已有 issue 的状态
    - 翻页拉取最新 N 个 open PR（按 updated desc）
    """
    if not Config.GITHUB_SYNC_ENABLED:
        return
    job_id = "sync_community"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        logger.info("Starting community data sync...")
        tracked = _get_tracked_repos()
        if not tracked:
            logger.warning("No tracked repos, skipping community data sync")
            return
        for short_name, full_repo in tracked:
            _sync_single_repo_community(full_repo)
    except Exception:
        logger.exception("Error syncing community data")
    finally:
        _running_jobs.discard(job_id)


def _sync_single_repo_community(repo: str):
    """同步单个仓库的 issue/PR"""
    github_client = _get_github_client()
    mapper = _get_area_mapper(repo)
    db = SessionLocal()
    try:
        # 翻页拉最新 open issue（按 created desc），防止漏掉新 issue
        recent_issues: list = []
        for page in range(1, COMMUNITY_FETCH_PAGES + 1):
            page_items = github_client.get_issues(
                state="open", sort="created", direction="desc", page=page, repo=repo
            ) or []
            if not page_items:
                break
            recent_issues.extend(page_items)
            if len(page_items) < DEFAULT_PER_PAGE:
                break  # 不足一页，说明没有更多了

        # 增量拉取最近更新的 issue（DB 已有数据时）
        existing_count = db.query(Item).filter(Item.repo == repo).count()
        incremental_issues = []
        if existing_count > 0:
            since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=int(Config.POLLING_INTERVAL * 3))
            since_iso = since.isoformat() + "Z"
            incremental_issues = github_client.get_issues(
                state="open", sort="updated", direction="desc", since=since_iso, repo=repo
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
                state="open", sort="updated", direction="desc", page=page, repo=repo
            ) or []
            if not page_prs:
                break
            pulls.extend(page_prs)
            if len(page_prs) < DEFAULT_PER_PAGE:
                break

        # GitHub /issues 端点会同时返回 PR（PR 是 issue 的子集），
        # 必须过滤掉带 pull_request 字段的项，否则 PR 会被当成 issue 存储
        real_issues = [it for it in all_issues if not it.get("pull_request")]

        for issue in real_issues:
            try:
                _process_single_issue(db, issue, mapper, repo)
            except Exception:
                logger.exception(f"Failed to process issue {issue.get('number')} ({repo}), skipping")

        for pr in pulls:
            try:
                _process_single_pr_item(db, pr, github_client, mapper, repo)
            except Exception:
                logger.exception(f"Failed to process PR item {pr.get('number')} ({repo}), skipping")

        db.commit()
        logger.info(
            f"Synced {len(real_issues)} issues and {len(pulls)} PRs for {repo} "
            f"(filtered {len(all_issues) - len(real_issues)} PRs from issues)"
        )
    finally:
        db.close()


def _calc_ci_status(github_client: GitHubClient, sha: str, repo: str) -> str:
    """根据 check runs + commit status 推导 CI 状态"""
    if not sha:
        return "unknown"
    return github_client.get_combined_ci(sha, repo=repo).get("status", "unknown")


def sync_user_prs():
    """同步所有已录入用户的 PR + Issue 数据

    遍历 users 表中所有有 github_id 的用户，
    为每个用户在每个 tracked 仓库独立拉取其 PR 和 Issue 并写入 my_prs / user_issues 表。
    没有 tracked 仓库时兜底同步 Config 默认仓库。
    """
    if not Config.GITHUB_SYNC_ENABLED:
        return
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

        # 确定要同步的仓库列表
        tracked = _get_tracked_repos()
        if not tracked:
            logger.warning("No tracked repos, skipping user PR sync")
            return

        for user in users:
            for _short_name, full_repo in tracked:
                try:
                    _sync_single_user(user.github_id, full_repo)
                except Exception:
                    logger.exception(f"Sync failed for user {user.github_id} in repo {full_repo}")

        # 清理已删除用户的旧数据
        _cleanup_orphaned_data()
    except Exception:
        logger.exception("user PR sync failed")
    finally:
        _running_jobs.discard(job_id)


def _sync_single_user(github_id: str, repo: str):
    """同步单个用户在指定仓库的 PR 和 Issue 数据"""
    logger.info(f"Starting sync for user {github_id} in {repo}...")
    github_client = _get_github_client()
    mapper = _get_area_mapper(repo)
    db = SessionLocal()
    try:
        # 增量策略：首次全量拉，后续只拉 open + 最近更新的 PR
        existing_count = db.query(MyPR).filter(MyPR.github_id == github_id, MyPR.repo == repo).count()
        is_first_sync = existing_count == 0

        if is_first_sync:
            user_prs = github_client.get_user_pulls(github_id, state="all", repo=repo) or []
        else:
            user_prs = github_client.get_user_pulls(github_id, state="open", repo=repo) or []
            closed_prs = github_client.get_user_pulls(github_id, state="closed", repo=repo) or []
            user_prs.extend(closed_prs[:20])

        def _fetch_one(pr):
            if not isinstance(pr, dict):
                return None
            pr_number = pr.get("number")
            if pr_number is None:
                return None
            try:
                return (pr_number, _fetch_user_pr_detail(pr, pr_number, github_client, mapper, repo))
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
                _upsert_user_pr(db, detail, github_client, repo, github_id)
            except Exception:
                logger.exception(f"Failed to upsert user PR #{pr_number} for {github_id}, skipping")

        # 同步用户创建的 Issue
        existing_issue_count = db.query(UserIssue).filter(UserIssue.github_id == github_id).count()
        is_first_issue_sync = existing_issue_count == 0
        issue_state = "all" if is_first_issue_sync else "open"

        user_issues = github_client.get_user_issues_with_body(github_id, state=issue_state, repo=repo) or []
        if not is_first_issue_sync:
            closed_issues = github_client.get_user_issues(github_id, state="closed", repo=repo) or []
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
                          github_client: GitHubClient, mapper: "AreaMapper",
                          repo: str) -> Optional[dict]:
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
        fetched = github_client.get_pull(pr_number, repo=repo)
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
        ci_status = _calc_ci_status(github_client, head_sha, repo)
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
        compare = github_client.compare_branches(base_ref, head_sha, repo=repo) or {}
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
                    repo: str, github_id: str = "") -> None:
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
    existing = db.query(MyPR).filter(
        MyPR.repo == repo, MyPR.pr_number == pr_number, MyPR.github_id == github_id
    ).first()
    area_id = detail.get("area_id")
    if existing:
        item = db.query(Item).filter(Item.repo == repo, Item.type == "pr", Item.number == pr_number).first()
        area_id = item.area if item else None
    if not area_id:
        area_id = _map_pr_to_area(pr_number, github_client, repo)
        if area_id:
            item = db.query(Item).filter(Item.repo == repo, Item.type == "pr", Item.number == pr_number).first()
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
            repo=repo,
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
            # 预加载 RepoCache 短名 -> 完整 owner/repo 映射
            repo_map = {}
            try:
                for rc in db.query(RepoCache).filter(RepoCache.status == "active").all():
                    repo_map[rc.repo] = _clone_url_to_full_repo(rc.clone_url)
            except Exception:
                pass
            for ref in refs:
                if ref.get("state") or not ref.get("number"):
                    continue
                number = ref["number"]
                repo_short = ref.get('repo', '')
                repo_path = repo_map.get(repo_short, '')
                if not repo_path:
                    continue
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


def generate_daily_vllm_report():
    """每天早上8点生成 vLLM 每日全景报告（指导贡献者新一天的贡献方向）"""
    job_id = "daily_vllm_report"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        db = None
        today_start = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d")
        from app.services.intelligence_report import IntelligenceReportGenerator
        from app.models import IntelligenceReport

        db = SessionLocal()
        # 从 RepoCache 动态构建 sources 列表
        active_repos = db.query(RepoCache).filter(
            RepoCache.status == "active"
        ).all()
        repo_sources = [r.repo for r in active_repos]
        sources = list(repo_sources)

        # 检查今天是否已经生成过成功报告
        today_start_dt = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d 00:00:00")
        existing = db.query(IntelligenceReport).filter(
            IntelligenceReport.category == "daily",
            IntelligenceReport.status == "completed",
            IntelligenceReport.created_at >= today_start_dt,
        ).first()
        if existing:
            logger.info(f"Daily report already exists for {today_start}, skipping")
            return

        title = f"vLLM 每日全景报告 - {today_start}"

        # 生成报告前释放 DB session（Agent 循环可能耗时 1-5 分钟，避免长时间占用 SQLite）
        # 但 IntelligenceReportGenerator 需要 db 来构建 source_config，从 session 中提取所需数据后关闭
        repo_clone_urls = {r.repo: r.clone_url for r in active_repos}

        # 在关闭 DB 前，从知识库召回相关记忆，注入到 extra_prompt 中
        memory_context = _build_daily_report_memory_context(db)
        db.close()
        db = None

        generator = IntelligenceReportGenerator()
        # 注入仓库信息到 generator，避免其自行查询 DB
        generator._cached_source_config = {
            r: {
                "display_name": r,
                "repos": [IntelligenceReportGenerator._parse_repo_url(repo_clone_urls[r])],
                "type": "github",
            }
            for r in repo_sources
            if repo_clone_urls.get(r)
        }
        REPORT_GENERATION_TIMEOUT = 600  # 10 分钟超时
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            generator.generate_report,
            task_title=title,
            task_description=(
                "请全面调研 vLLM 项目在过去24小时内发生的最新动态，"
                "为vLLM贡献者提供一份全面的全景报告，包含以下内容：\n\n"
                "## 核心内容要求\n"
                "1. **昨日新增的 Issue/PR**：重点分析新提交的 issue 和 PR，"
                "标注哪些是bug报告、哪些是feature request、哪些是WIP PR\n"
                "2. **昨日新增 Commit 的 Bug 分析**：读取昨日合并的 PR 的 diff，"
                "分析新提交的代码本身是否存在以下问题：\n"
                "   - 逻辑缺陷（边界条件遗漏、错误处理缺失、并发安全问题）\n"
                "   - 性能隐患（不必要的拷贝、O(n²) 复杂度、显存泄漏）\n"
                "   - 设计问题（抽象不当、接口不兼容、未来扩展困难）\n"
                "   - 测试不足（关键路径无覆盖、边界值未测试）\n"
                "3. **最新代码质量评估**：关注昨日提交的代码本身的质量，包括：\n"
                "   - 代码规范问题（命名、注释、类型标注）\n"
                "   - 与现有架构的契合度（是否引入重复逻辑、是否破坏模块边界）\n"
                "   - 向后兼容性（API 变更是否影响下游）\n"
                "4. **SGLang 对比分析**：检查 SGLang 近期是否有新功能或改进，"
                "评估 vLLM 是否缺失对应功能，是否需要补齐\n"
                "5. **贡献机会推荐**：包括：\n"
                "   - 初级：good first issue / help wanted（适合入门）\n"
                "   - **专业：需要深入理解 vLLM 架构的改进方向**（如注意力机制优化、"
                "调度策略改进、新硬件后端适配、显存管理优化、推理引擎重构）\n"
                "   - **研究型：需要原型验证的前沿方向**（如新的投机解码策略、"
                "量化方案适配、多模态扩展）\n"
                "6. **架构变更提醒**：如果有重要架构变更的 PR，提醒贡献者关注\n\n"
                "## 数据源和时间范围\n"
                "- 主要搜索 vllm 主仓库最近24小时到48小时的 issue/PR\n"
                "- 同时搜索 sglang 仓库最近24小时的新动态用于对比\n"
                "- 获取各仓库的最新 release\n\n"
                "## 报告风格\n"
                "报告面向 vLLM 贡献者，使用中文，语言简洁务实。"
                "每个 issue/PR 都要包含编号和链接，方便直接跳转。"
                "对复杂问题给出简要技术分析，帮助读者快速理解。"
            ),
            sources=sources,
            extra_prompt=(
                "特别注意：\n"
                "- 优先关注过去24小时内创建的 issue/PR，标记为【昨日新增】\n"
                "- 对每个 issue/PR 简要说明其技术价值或影响范围\n"
                "- **Commit Bug 分析要求**：首先用 search_issues(state=merged) 搜索最近24-48小时内合并的 PR，"
                "然后用 get_pr_diff 读取这些 PR 的 diff，"
                "从代码层面分析：\n"
                "  1) 逻辑缺陷（错误处理、并发安全、边界条件）\n"
                "  2) 性能隐患（不必要的拷贝、显存泄漏、复杂度）\n"
                "  3) 设计问题（抽象不当、接口兼容性、扩展性）\n"
                "  4) 测试覆盖（关键路径是否测试、边界值覆盖）\n"
                "- 对昨日新增的 bug report，分析：影响范围、复现难度、修复方向\n"
                "- 贡献机会要分三级：初级（good first issue）、"
                "专业（架构改进、新后端适配、性能优化）、"
                "研究型（新算法原型、新硬件探索）\n"
                "- 如果发现 SGLang 有 vLLM 未实现的功能，单独列出并建议优先级\n"
                "- 最后给出「今日贡献指南」：按难度和价值排序，今天做什么最有贡献"
                f"{memory_context}"
            ),
        )
        try:
            result = future.result(timeout=REPORT_GENERATION_TIMEOUT)
        except TimeoutError:
            future.cancel()
            logger.error("Daily report generation timed out after 10 minutes")
            raise
        finally:
            executor.shutdown(wait=False)

        report = IntelligenceReport(
            title=title,
            content=result["content"],
            sources=json.dumps(result["sources"]),
            status="completed",
            category="daily",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db = SessionLocal()
        db.add(report)
        db.commit()
        logger.info(f"Daily vLLM report generated: {title}")
    except Exception:
        logger.exception("Failed to generate daily vLLM report")
        # 异常发生时 db 可能处于异常状态，重新获取 session
        try:
            if db is not None:
                db.close()
        except Exception:
            pass
        db = None
        try:
            db = SessionLocal()
            failed_sources = json.dumps(locals().get("sources", ["academic", "news"]))
            failed_report = IntelligenceReport(
                title=f"vLLM 每日全景报告 - {today_start}（生成失败）",
                content="",
                sources=failed_sources,
                status="failed",
                category="daily",
                error_message=traceback.format_exc(),
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(failed_report)
            db.commit()
        except Exception:
            logger.exception("Failed to write failed daily report status")
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
        _running_jobs.discard(job_id)


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

    # 学习文章 - 代码仓库同步（只要有活跃仓库就启用）
    from app.database import SessionLocal
    from app.models import RepoCache
    db = SessionLocal()
    try:
        has_active_repos = db.query(RepoCache).filter(RepoCache.status == "active").count() > 0
    finally:
        db.close()

    if has_active_repos:
        scheduler.add_job(
            sync_all_repos_job,
            trigger=IntervalTrigger(minutes=Config.POLLING_INTERVAL),
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

    # vLLM 每日全景报告（每天早上 8 点北京时间）
    scheduler.add_job(
        generate_daily_vllm_report,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Shanghai"),
        id="daily_vllm_report",
        name="Daily vLLM Panorama Report",
        replace_existing=True,
        misfire_grace_time=3600,  # 允许 1 小时内错过的触发
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
            from app.database import SessionLocal
            from app.models import RepoCache
            db = SessionLocal()
            try:
                has_repos = db.query(RepoCache).filter(RepoCache.status == "active").count() > 0
            finally:
                db.close()
            if has_repos:
                sync_all_repos_job()
            _refresh_personal_task_refs()
        except Exception:
            logger.exception("Initial sync failed (will retry on schedule)")
    threading.Thread(target=_initial_sync, daemon=True, name="initial-sync").start()
    logger.info("Initial sync scheduled in background thread")


def trigger_sync_for_repo(repo: str):
    """异步触发单个仓库的社区同步（供 toggle 追踪时调用，不阻塞）"""
    if not scheduler.running:
        return {"triggered": False, "reason": "scheduler not running"}
    # 用 (repo, "community") 作为 job_id，避免与全局 sync_community 冲突
    job_id = f"sync_repo_{repo}"
    if job_id in _running_jobs:
        return {"triggered": False, "reason": "already running", "repo": repo}
    import threading
    def _run():
        _sync_single_repo_community(repo)
    threading.Thread(target=_run, daemon=True, name=job_id).start()
    return {"triggered": True, "repo": repo}


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
    if not Config.GITHUB_SYNC_ENABLED:
        return
    job_id = "sync_all_repos"
    if job_id in _running_jobs:
        logger.debug(f"{job_id} already running, skipping")
        return
    _running_jobs.add(job_id)
    try:
        from app.database import SessionLocal
        from app.models import RepoCache
        from app.services.repo_manager import RepoManager

        db = SessionLocal()
        try:
            active_repos = db.query(RepoCache).filter(RepoCache.status == "active").all()
        finally:
            db.close()

        if not active_repos:
            logger.warning("No active repos in DB, skipping code sync")
            return

        manager = RepoManager()
        has_changes = False
        for repo_record in active_repos:
            try:
                result = manager.pull_and_sync(repo_record.repo)
                logger.info(f"Repo {repo_record.repo} synced: {result}")
                if result.get("created", 0) > 0 or result.get("updated", 0) > 0:
                    has_changes = True
            except Exception:
                logger.exception(f"Error syncing repo {repo_record.repo}")

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
    if not Config.GITHUB_SYNC_ENABLED:
        return
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
                    pr_repo = pr.repo
                    if not pr_repo:
                        continue
                    files = client.get_pull_files(pr.pr_number, repo=pr_repo)
                    if not files:
                        continue

                    # 清除该 PR 的旧记录，重新写入
                    db.query(FileChangeHistory).filter(
                        FileChangeHistory.pr_number == pr.pr_number,
                        FileChangeHistory.repo == pr_repo,
                    ).delete()
                    db.flush()

                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    for f in files:
                        fname = f.get("filename") if isinstance(f, dict) else None
                        if not fname:
                            continue
                        db.add(FileChangeHistory(
                            repo=pr_repo,
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


def _build_daily_report_memory_context(db) -> str:
    """从知识库召回与日报相关的记忆，返回格式化文本注入到 extra_prompt"""
    from app.services.memory_service import MemoryService

    mem = MemoryService()
    parts = []

    # 1. 召回近期高频 issue/PR（了解社区热点和常见问题）
    try:
        issues = mem.recall(
            query="vLLM bug issue PR 性能 功能",
            top_k=8,
            source_types=["issue", "pr"],
            exclude_stale=True,
        )
        if issues:
            lines = ["### 近期社区热点 Issue/PR"]
            for item in issues:
                title = (item.get("content") or "").split("\n")[0][:100]
                ref = item.get("source_ref", "")
                tags = ", ".join(item.get("tags", [])[:4])
                lines.append(f"- {title} ({ref}) [{tags}]")
            parts.append("\n".join(lines))
    except Exception:
        logger.warning("Failed to recall issues for daily report", exc_info=True)

    # 2. 召回近期 Bug 报告和代码变更（为 commit diff 分析提供上下文）
    try:
        bugs = mem.recall(
            query="bug 错误 异常 崩溃 失败 regression 回归 缺陷",
            top_k=10,
            source_types=["issue"],
            tags=["bug", "regression", "critical"],
            exclude_stale=True,
        )
        if bugs:
            lines = ["### 当前待解决的 Bug"]
            for item in bugs[:6]:
                content = item.get("content") or ""
                title = content.split("\n")[0][:120]
                ref = item.get("source_ref", "")
                tags = ", ".join(item.get("tags", [])[:4])
                lines.append(f"- {title} ({ref}) [{tags}]")
            lines.append("")
            lines.append("> 提示：分析这些 bug 时，重点关注其根因是否在近期的 commit 中引入，"
                         "评估修复时是否会影响现有代码结构。")
            parts.append("\n".join(lines))
    except Exception:
        logger.warning("Failed to recall bugs for daily report", exc_info=True)

    # 3. 召回最近的 intelligence report（参考之前报告的风格和内容）
    try:
        reports = mem.recall(
            query="vLLM 每日全景报告 洞察报告 动态",
            top_k=3,
            source_types=["report"],
            exclude_stale=True,
        )
        if reports:
            lines = ["### 历史报告参考"]
            for item in reports:
                summary = (item.get("content") or "")[:200]
                ref = item.get("source_ref", "")
                lines.append(f"- {ref}: {summary}")
            parts.append("\n".join(lines))
    except Exception:
        logger.warning("Failed to recall past reports", exc_info=True)

    # 4. 召回架构相关知识（帮助 AI 理解代码上下文）
    try:
        arch = mem.recall(
            query="vLLM 架构 模块 设计 attention scheduler 推理 引擎",
            top_k=5,
            source_types=["code_structure"],
            tags=["code", "vllm"],
            exclude_stale=True,
        )
        if arch:
            lines = ["### 架构知识参考"]
            for item in arch:
                content = (item.get("content") or "")[:200]
                ref = item.get("source_ref", "")
                lines.append(f"- {ref}: {content}")
            parts.append("\n".join(lines))
    except Exception:
        logger.warning("Failed to recall architecture knowledge", exc_info=True)

    if not parts:
        return ""

    return "\n\n## 知识库参考信息\n" + "\n\n".join(parts)


def cleanup_old_data():
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

        # 4. 清理 intelligence_reports 表：删除 stale 报告
        #    - failed/daily 报告保留 30 天
        #    - manual 非 daily 报告保留 retention_days
        failed_cutoff = now - timedelta(days=30)
        # 删除 failed 状态超过 30 天的
        deleted_failed = db.query(IntelligenceReport).filter(
            IntelligenceReport.status == "failed",
            IntelligenceReport.created_at < failed_cutoff,
        ).delete(synchronize_session=False)
        if deleted_failed:
            logger.info(f"Cleaned {deleted_failed} failed intelligence_reports")
        # 删除 manual 非 daily 且超过 retention_days 的 completed 报告
        manual_cutoff = now - timedelta(days=retention_days)
        deleted_manual = db.query(IntelligenceReport).filter(
            IntelligenceReport.status == "completed",
            db.or_(
                IntelligenceReport.category == "manual",
                IntelligenceReport.category.is_(None),
            ),
            IntelligenceReport.created_at < manual_cutoff,
        ).delete(synchronize_session=False)
        if deleted_manual:
            logger.info(f"Cleaned {deleted_manual} manual intelligence_reports older than {retention_days}d")

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
                     f"{deleted_cache} ai_cache, {deleted_failed} failed_reports, {deleted_manual} manual_reports")
    except Exception:
        logger.exception("Error during data cleanup")
        db.rollback()
    finally:
        db.close()


