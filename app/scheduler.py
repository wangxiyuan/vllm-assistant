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
from app.models import Item, MyPR, Area, UserIssue
from app.services.github_client import GitHubClient, DEFAULT_PER_PAGE
from app.services.area_mapper import AreaMapper

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Module-level singletons（避免在 job 中反复创建）
_github_client: Optional[GitHubClient] = None
_area_mapper: Optional[AreaMapper] = None

# 用户 PR 详情并发拉取的线程数（GitHub 并发友好值，配合 GitHubClient 退避重试）
USER_PR_FETCH_WORKERS = 5
# 社区同步翻页数（issues/pulls 各翻 N 页，每页 DEFAULT_PER_PAGE=30）
COMMUNITY_FETCH_PAGES = 2


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


def sync_community_data():
    """同步社区数据（issues/PRs）到数据库

    同步策略：
    - 翻页拉取最新 N 个 open issue（按 created desc，每页 30，翻 COMMUNITY_FETCH_PAGES 页）
    - 增量拉取最近更新的 issue（since 窗口），更新已有 issue 的状态
    - 翻页拉取最新 N 个 open PR（按 updated desc）
    """
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


def _calc_ci_status(github_client: GitHubClient, sha: str) -> str:
    """根据 check runs + commit status 推导 CI 状态"""
    if not sha:
        return "unknown"
    return github_client.get_combined_ci(sha).get("status", "unknown")


def sync_user_prs():
    """同步用户的 PR + Issue 数据

    - PR：写入 my_prs（带 CI/review/conflict 状态）
    - Issue：写入 items（type=issue），供我的数据/我的贡献的 Issue 视图使用
    """
    try:
        if not Config.USERNAME:
            logger.warning("GITHUB_USERNAME not configured, skipping user PR sync")
            return

        logger.info("Starting user PR sync...")
        github_client = _get_github_client()
        mapper = _get_area_mapper()
        db = SessionLocal()
        try:
            # 同步 PR：先并发拉取每个 open PR 的详情，再串行 upsert（DB 非线程安全）
            user_prs = github_client.get_user_pulls(Config.USERNAME, state="all") or []

            # 阶段一：并发拉取（merged/closed PR 不调额外 API，直接构造 detail）
            def _fetch_one(pr):
                if not isinstance(pr, dict):
                    return None
                pr_number = pr.get("number")
                if pr_number is None:
                    return None
                try:
                    return (pr_number, _fetch_user_pr_detail(pr, pr_number, github_client, mapper))
                except Exception:
                    logger.exception(f"Failed to fetch user PR #{pr_number}, skipping")
                    return None

            with ThreadPoolExecutor(max_workers=USER_PR_FETCH_WORKERS) as pool:
                results = list(pool.map(_fetch_one, user_prs))

            # 阶段二：串行 upsert（过滤掉拉取失败的 detail）
            for item in results:
                if item is None:
                    continue
                pr_number, detail = item
                if detail is None:
                    continue
                try:
                    _upsert_user_pr(db, detail, github_client, mapper)
                except Exception:
                    logger.exception(f"Failed to upsert user PR #{pr_number}, skipping")

            # 同步用户创建的 Issue 到 user_issues 表
            # 用 get_user_issues_with_body 拉取含 body 的完整数据（弹窗需要正文）
            user_issues = github_client.get_user_issues_with_body(Config.USERNAME, state="all") or []
            issue_count = 0
            for issue in user_issues:
                if not isinstance(issue, dict):
                    continue
                try:
                    _process_single_user_issue(db, issue, mapper)
                    issue_count += 1
                except Exception:
                    logger.exception(f"Failed to process user issue #{issue.get('number')}, skipping")

            db.commit()
            logger.info(f"Synced {len(user_prs)} user PRs and {issue_count} user issues")
        finally:
            db.close()

    except Exception:
        logger.exception("Error syncing user PRs")


def _process_single_user_issue(db, issue: dict, mapper: AreaMapper) -> None:
    """把用户创建的 Issue 写入 user_issues 表"""
    issue_number = issue.get("number")
    if issue_number is None:
        return

    labels = [l["name"] for l in issue.get("labels", []) if isinstance(l, dict)]
    area_id = mapper.classify_issue_by_labels(labels)
    body = issue.get("body") or ""
    title = issue.get("title", "")

    existing = db.query(UserIssue).filter(UserIssue.number == issue_number).first()

    if existing:
        existing.title = title
        existing.state = issue.get("state", existing.state)
        existing.updated_at = _parse_dt(issue.get("updated_at"))
        existing.comments = issue.get("comments", existing.comments)
        existing.labels = json.dumps(labels)
        existing.body = body
        existing.area = area_id
        existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(UserIssue(
            number=issue_number,
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
                    mapper: "AreaMapper") -> None:
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
    existing = db.query(MyPR).filter(MyPR.pr_number == pr_number).first()
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
        # created_at 首次写入后不再覆盖（GitHub 的 created_at 不会变）
        if not existing.created_at:
            existing.created_at = _parse_dt(pr.get("created_at"))
        existing.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        db.add(MyPR(
            pr_number=pr_number,
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


def start_scheduler():
    """启动定时调度器"""
    if scheduler.running:
        return

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
            validate_articles_job,
            trigger=IntervalTrigger(hours=Config.ARTICLE_VALIDATE_INTERVAL),
            id="validate_articles",
            name="Validate Article Code Refs",
            replace_existing=True,
        )

        scheduler.add_job(
            sync_file_change_history_job,
            trigger=IntervalTrigger(hours=1),  # 每小时同步一次
            id="sync_file_history",
            name="Sync File Change History",
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
    """定时任务：同步所有仓库代码到 LocalCodeCache"""
    from app.services.repo_manager import RepoManager

    if not Config.REPOS:
        logger.warning("No REPOS configured, skipping code sync")
        return

    manager = RepoManager()
    for repo_name in Config.REPOS:
        try:
            result = manager.pull_and_sync(repo_name)
            logger.info(f"Repo {repo_name} synced: {result}")
        except Exception:
            logger.exception(f"Error syncing repo {repo_name}")

    # 对所有受影响文件做行号越界检查
    try:
        manager.validate_all_refs()
    except Exception:
        logger.exception("Error validating refs after sync")


def sync_file_change_history_job():
    """定时任务：同步文件变更历史到 FileChangeHistory 表

    遍历 my_prs 中已同步的 PR，获取每个 PR 的变更文件列表并记录。
    实现 O(1) 的文件 → PR 查询，替代全表扫描 + GitHub API 调用的低效方案。
    """
    from app.models import FileChangeHistory
    from app.services.github_client import GitHubClient

    client = GitHubClient()
    db = SessionLocal()
    try:
        prs = db.query(MyPR).filter(MyPR.state == "open").all()
        # 也同步最近合并的 PR（前 50 个）
        merged_prs = db.query(MyPR).filter(MyPR.state == "merged").order_by(
            MyPR.last_sync.desc()).limit(50).all()
        all_prs = prs + merged_prs

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
        logger.info(f"File change history synced for {synced_count} PRs")
    except Exception:
        logger.exception("Error syncing file change history")
    finally:
        db.close()


def validate_articles_job():
    """定时任务：深度验证所有文章中的代码引用"""
    from app.services.article_validator import ArticleValidator
    from app.services.local_code_sync import LocalCodeSyncService
    from app.database import SessionLocal

    if not Config.REPOS:
        return

    db = SessionLocal()
    try:
        cache_service = LocalCodeSyncService(db)
        validator = ArticleValidator(cache_service, db)
        result = validator.batch_validate(deep_check=True)
        logger.info(f"Article validation completed: {result}")
    except Exception:
        logger.exception("Error validating articles")
    finally:
        db.close()
