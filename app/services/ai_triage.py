"""
AI 分诊服务（总览页）：按用户自定义规则对社区条目（items）做增量语义筛选。

- 每条规则维护一个 last_triage_at 水位线，只对 items.last_sync 晚于水位线的条目调用 LLM
- 命中结果写 ai_triage_matches，展示时按 (repo, item_type, number) join items
- LLM 调用期间不持有 SQLite session（沿用 scheduler 的经验，避免长事务占库）
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import Config
from app.database import SessionLocal
from app.models import AIRule, AIRuleCommitMatch, AIRuleMatch, Item
from app.services.llm import LLMClient
from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)

# 单条 prompt 里条目正文的截断长度
_ITEM_BODY_LIMIT = 500
# 单仓库参与分诊的 commit 候选上限
_COMMIT_PER_REPO_LIMIT = 100# 单次 LLM 输出上限（每条命中一段 reason，候选多、命中多时 JSON 很长，需留足余量避免截断）
_TRIAGE_MAX_TOKENS = Config.AI_TRIAGE_MAX_TOKENS

_llm_client: Optional[LLMClient] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def _load_rule_filters(rule: AIRule) -> tuple[list, list]:
    try:
        repos = json.loads(rule.repos) if rule.repos else []
    except (ValueError, TypeError):
        repos = []
    try:
        areas = json.loads(rule.areas) if rule.areas else []
    except (ValueError, TypeError):
        areas = []
    return repos, areas


def _candidate_items(db, rule: AIRule, watermark: Optional[datetime]) -> list:
    """按规则预过滤 + 水位线取候选条目（created_at 倒序，上限 AI_TRIAGE_CANDIDATE_LIMIT）"""
    q = db.query(Item)
    if rule.item_type in ("pr", "issue"):
        q = q.filter(Item.type == rule.item_type)
    repos, areas = _load_rule_filters(rule)
    if repos:
        q = q.filter(Item.repo.in_(repos))
    if areas:
        q = q.filter(Item.area.in_(areas))
    if watermark:
        q = q.filter(Item.last_sync > watermark)
    else:
        # 首跑无水位线：只回看 N 天新增，避免对全量历史做分诊
        q = q.filter(Item.created_at > _utcnow() - timedelta(days=Config.AI_TRIAGE_RERUN_WINDOW_DAYS))
    return q.order_by(Item.created_at.desc()).limit(Config.AI_TRIAGE_CANDIDATE_LIMIT).all()


def _parse_commit_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _candidate_commits(db, rule: AIRule, watermark: Optional[datetime]) -> list:
    """从本地缓存 git 仓库取最近 commit 作为候选（committed_at 倒序，总量受 AI_TRIAGE_CANDIDATE_LIMIT 限制）"""
    if rule.include_commits is False:
        return []
    from app.services.repo_manager import RepoManager

    repos, _areas = _load_rule_filters(rule)
    short_to_full = RepoManager().short_to_full_map(db)
    if repos:
        target = {s: f for s, f in short_to_full.items() if f in repos}
    else:
        target = short_to_full
    if not target:
        return []

    candidates = []
    for short, full in target.items():
        commits = RepoManager().get_recent_commits(
            short, since_days=Config.AI_TRIAGE_RERUN_WINDOW_DAYS,
            limit=_COMMIT_PER_REPO_LIMIT,
        )
        for c in commits:
            committed = _parse_commit_datetime(c.get("committed_at"))
            if watermark and (committed is None or committed <= watermark):
                continue
            candidates.append({
                "repo": full, "type": "commit", "number": 0,
                "sha": c["sha"], "short_sha": c["short_sha"],
                "author": c["author"], "committed_at": c["committed_at"],
                "title": c["subject"], "body": "",
            })
    candidates.sort(key=lambda c: c.get("committed_at") or "", reverse=True)
    return candidates[:Config.AI_TRIAGE_CANDIDATE_LIMIT]


def _build_prompt(rule_name: str, rule_prompt: str, candidates: list) -> str:
    entries = []
    for i, c in enumerate(candidates, start=1):
        entry = {
            "index": i,
            "repo": c["repo"],
            "type": c["type"],
            "title": c["title"],
            "body": (c.get("body") or "（无正文）")[:_ITEM_BODY_LIMIT],
        }
        if c["type"] == "commit":
            entry.update({
                "number": 0,
                "short_sha": c["short_sha"],
                "author": c["author"],
                "committed_at": c["committed_at"],
                "state": "", "labels": "", "area": "",
            })
        else:
            try:
                labels = ", ".join(json.loads(c["labels"])) if c["labels"] else "无"
            except (ValueError, TypeError):
                labels = c["labels"] or "无"
            entry.update({
                "number": c["number"],
                "state": c["state"] or "unknown",
                "labels": labels,
                "area": c["area"] or "无",
                "short_sha": "", "author": "", "committed_at": "",
            })
        entries.append(entry)
    return render_prompt("triage", "triage.j2", rule_name=rule_name, rule_prompt=rule_prompt, items=entries)


def _update_rule_meta(rule_id: int, run_at: Optional[datetime] = None,
                      advance_watermark_to: Optional[datetime] = None,
                      error: Optional[str] = None):
    """更新规则的运行元信息（短事务）。error=None 表示清空错误。"""
    db = SessionLocal()
    try:
        rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
        if not rule:
            return
        if run_at is not None:
            rule.last_run_at = run_at
        if advance_watermark_to is not None:
            rule.last_triage_at = advance_watermark_to
        rule.last_error = error
        db.commit()
    finally:
        db.close()


def _persist_result(rule_id: int, candidates: list, matches: dict, run_at: datetime):
    """把一轮分诊结果写入/清理 matches（items 与 commit 两张表），并推进水位线（独立短事务）

    matches 的 key：普通条目为 (item_type, repo, number)，commit 为 ("commit", repo, sha)。
    """
    db = SessionLocal()
    try:
        rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
        if not rule:
            return
        item_cand_keys = {(c["repo"], c["type"], c["number"]) for c in candidates if c["type"] != "commit"}
        commit_cand_keys = {(c["repo"], c["sha"]) for c in candidates if c["type"] == "commit"}
        matched_item_keys = {k for k in matches if k[0] != "commit"}
        matched_commit_keys = {(k[1], k[2]) for k in matches if k[0] == "commit"}

        # 本轮候选中曾经命中、这轮重新评估后不再命中的旧 match 要清掉
        for row in db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule_id).all():
            key = (row.repo, row.item_type, row.number)
            if key in item_cand_keys and key not in matched_item_keys:
                db.delete(row)
        for row in db.query(AIRuleCommitMatch).filter(AIRuleCommitMatch.rule_id == rule_id).all():
            key = (row.repo, row.sha)
            if key in commit_cand_keys and key not in matched_commit_keys:
                db.delete(row)

        for key, reason in matches.items():
            match_type, repo, ident = key
            if match_type == "commit":
                cand = next(c for c in candidates if c["type"] == "commit" and c["repo"] == repo and c["sha"] == ident)
                row = db.query(AIRuleCommitMatch).filter_by(
                    rule_id=rule_id, repo=repo, sha=ident
                ).first()
                if row:
                    row.reason = reason
                    row.matched_at = run_at
                else:
                    db.add(AIRuleCommitMatch(
                        rule_id=rule_id, repo=repo, sha=ident,
                        short_sha=cand["short_sha"], title=cand["title"],
                        author=cand["author"],
                        committed_at=_parse_commit_datetime(cand["committed_at"]),
                        reason=reason, matched_at=run_at,
                    ))
            else:
                number = ident
                row = db.query(AIRuleMatch).filter_by(
                    rule_id=rule_id, repo=repo, item_type=match_type, number=number
                ).first()
                if row:
                    row.reason = reason
                    row.matched_at = run_at
                else:
                    db.add(AIRuleMatch(
                        rule_id=rule_id, repo=repo, item_type=match_type,
                        number=number, reason=reason, matched_at=run_at,
                    ))
        rule.last_triage_at = run_at
        rule.last_run_at = run_at
        rule.last_error = None
        db.commit()
    finally:
        db.close()


def run_triage(rule_id: int, rerun: bool = False) -> dict:
    """对单条规则执行一轮分诊。

    返回 {"ok": True, "candidates": n, "matched": m} 或 {"ok": False, "error": ...}。
    """
    # 1) 短事务：读规则与候选，转成纯数据后立刻释放连接
    db = SessionLocal()
    try:
        rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
        if not rule:
            return {"ok": False, "error": "rule not found"}
        if rerun:
            # 手动重跑：清空旧命中，水位线回拨 N 天覆盖近期条目
            db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule_id).delete()
            db.query(AIRuleCommitMatch).filter(AIRuleCommitMatch.rule_id == rule_id).delete()
            rule.last_triage_at = _utcnow() - timedelta(days=Config.AI_TRIAGE_RERUN_WINDOW_DAYS)
            rule.last_error = None
            db.commit()
            db.refresh(rule)
        rule_name = rule.name
        rule_prompt = rule.prompt
        candidates = [
            {
                "repo": it.repo, "type": it.type, "number": it.number,
                "state": it.state, "title": it.title or "",
                "labels": it.labels or "", "area": it.area or "",
                "body": it.body or "",
            }
            for it in _candidate_items(db, rule, rule.last_triage_at)
        ]
        candidates += _candidate_commits(db, rule, rule.last_triage_at)
    finally:
        db.close()

    if not candidates:
        # 空跑也推进水位线，下轮从当前时间起算
        now = _utcnow()
        _update_rule_meta(rule_id, run_at=now, advance_watermark_to=now)
        return {"ok": True, "candidates": 0, "matched": 0}

    run_at = _utcnow()

    # 2) LLM 调用（不持有 DB session）；空输出/不可解析时重试并反馈，避免一次失败丢整轮
    try:
        prompt = _build_prompt(rule_name, rule_prompt, candidates)
        data = None
        content = ""
        last_err = "empty content"
        for attempt in range(3):
            content = _get_llm_client().chat_sync(
                prompt, max_tokens=_TRIAGE_MAX_TOKENS, temperature=0.2,
            )
            data = LLMClient.safe_json(content, default=None)
            if isinstance(data, dict) and "matches" in data:
                break
            if not content:
                last_err = "AI 返回了空内容"
            else:
                last_err = f"LLM 返回内容无法解析为 JSON: {(content or '')[:200]}"
            if attempt < 2:
                logger.warning(
                    "AI triage parse failed for rule %s (attempt %d/3): %s — 重试",
                    rule_id, attempt + 1, last_err,
                )
                prompt = (
                    f"{prompt}\n\n上一个回答不符合要求的 JSON 格式"
                    f"（你回答的是：{(content or '')[:200]}）。"
                    f"请只输出 JSON，不要输出任何其他文字或问题。"
                )
        if not isinstance(data, dict):
            raise ValueError(last_err)
        raw_matches = data.get("matches") or []
        if not isinstance(raw_matches, list):
            raw_matches = []
    except Exception as e:
        logger.exception("AI triage failed for rule %s", rule_id)
        _update_rule_meta(rule_id, run_at=run_at, error=str(e))
        return {"ok": False, "error": str(e)}

    # 3) 按序号映射回条目，短事务落库
    index_map = {i + 1: c for i, c in enumerate(candidates)}
    matches: dict = {}
    for m in raw_matches:
        if not isinstance(m, dict):
            continue
        try:
            idx = int(m.get("index"))
        except (TypeError, ValueError):
            continue
        cand = index_map.get(idx)
        if not cand:
            continue
        if cand["type"] == "commit":
            key = ("commit", cand["repo"], cand["sha"])
        else:
            key = (cand["type"], cand["repo"], cand["number"])
        matches[key] = (m.get("reason") or "").strip()[:500]

    _persist_result(rule_id, candidates, matches, run_at)
    return {"ok": True, "candidates": len(candidates), "matched": len(matches)}


def run_all_rules() -> dict:
    """遍历全部 enabled 规则逐条分诊；单条失败不影响其他规则。"""
    db = SessionLocal()
    try:
        rule_ids = [
            r.id for r in db.query(AIRule)
            .filter(AIRule.enabled == True)  # noqa: E712
            .order_by(AIRule.sort_order, AIRule.id).all()
        ]
    finally:
        db.close()
    results = {}
    for rid in rule_ids:
        try:
            results[str(rid)] = run_triage(rid)
        except Exception as e:
            logger.exception("AI triage crashed for rule %s", rid)
            results[str(rid)] = {"ok": False, "error": str(e)}
    return results
