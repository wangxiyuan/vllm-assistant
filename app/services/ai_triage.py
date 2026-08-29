"""
AI 分诊服务（总览页）：按用户自定义规则对社区条目（items）做增量语义筛选。

- 每条规则维护一个 last_triage_at 水位线，只对 items.last_sync 晚于水位线的条目调用 LLM
- 命中结果写 ai_triage_matches，展示时按 (repo, item_type, number) join items
- LLM 调用期间不持有 SQLite session（沿用 scheduler 的经验，避免长事务占库）
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
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
                "title": c["subject"], "body": c.get("body") or "",
                "diff_stat": c.get("diff_stat") or "",
            })
    candidates.sort(key=lambda c: c.get("committed_at") or "", reverse=True)
    return candidates[:Config.AI_TRIAGE_CANDIDATE_LIMIT]


def _build_group_prompt(rule_infos: list, candidates: list) -> str:
    """联合分诊 prompt：候选块在前（多规则共享且利于 provider 前缀缓存），规则段在后。"""
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
                "diff_stat": c.get("diff_stat") or "无",
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
    return render_prompt(
        "triage", "triage.md", rules=rule_infos, items=entries,
    )


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
    matched_at 语义为"首次命中时间"：已存在的行只更新 reason，不刷新 matched_at，
    供前端"最近 24 小时新增命中"标识使用。
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
    """对单条规则执行一轮分诊（单元素分组，统一走 _run_group）。

    返回 {"ok": True, "candidates": n, "matched": m} 或 {"ok": False, "error": ...}。
    """
    db = SessionLocal()
    try:
        rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
        if not rule:
            return {"ok": False, "error": "rule not found"}
    finally:
        db.close()
    return _run_group([rule], rerun_rule_ids={rule_id} if rerun else set())


def _group_key(rule: AIRule) -> tuple:
    """规则分组键：候选集完全一致的规则才能共享一次 LLM 调用。"""
    repos, areas = _load_rule_filters(rule)
    return (
        rule.item_type or "both",
        tuple(sorted(repos)),
        tuple(sorted(areas)),
        rule.include_commits is not False,
    )


def _run_group(rules: list, rerun_rule_ids: set) -> dict:
    """对一组候选集相同的规则执行一轮联合分诊：候选只渲染/发送一次。

    LLM 一次调用按规则分组输出；agent 复核也按组去重候选后一次执行。
    返回 {str(rule_id): {"ok", "candidates", "matched"}}。
    """
    # 1) 短事务：处理 rerun 重置、读取规则信息，取组内最小水位线查一次候选
    db = SessionLocal()
    try:
        ids = [r.id for r in rules]
        db_rules = db.query(AIRule).filter(AIRule.id.in_(ids)).all()
        rule_infos = []
        for rule in db_rules:
            if rule.id in rerun_rule_ids:
                # 手动重跑：清空旧命中，水位线回拨 N 天覆盖近期条目
                db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule.id).delete()
                db.query(AIRuleCommitMatch).filter(AIRuleCommitMatch.rule_id == rule.id).delete()
                rule.last_triage_at = _utcnow() - timedelta(days=Config.AI_TRIAGE_RERUN_WINDOW_DAYS)
                rule.last_error = None
            rule_infos.append({
                "id": rule.id,
                "name": rule.name,
                "prompt": rule.prompt,
                "key": f"rule_{rule.id}",
                "watermark": rule.last_triage_at,
                "item_type": rule.item_type or "both",
                "repos": rule.repos,
                "areas": rule.areas,
                "include_commits": rule.include_commits is not False,
            })
        db.commit()
        if not rule_infos:
            return {}

        # 组内取最小水位线：水印更靠后的规则会多评一些已评过的条目，
        # 结果不变（matched_at 不刷新），代价远小于按规则分别拉取
        watermarks = [ri["watermark"] for ri in rule_infos if ri["watermark"]]
        watermark = min(watermarks) if watermarks else None
        base = SimpleNamespace(
            item_type=rule_infos[0]["item_type"],
            repos=rule_infos[0]["repos"],
            areas=rule_infos[0]["areas"],
            include_commits=rule_infos[0]["include_commits"],
        )
        candidates = [
            {
                "repo": it.repo, "type": it.type, "number": it.number,
                "state": it.state, "title": it.title or "",
                "labels": it.labels or "", "area": it.area or "",
                "body": it.body or "",
            }
            for it in _candidate_items(db, base, watermark)
        ]
        candidates += _candidate_commits(db, base, watermark)
    finally:
        db.close()

    now = _utcnow()
    if not candidates:
        # 空跑也推进水位线，下轮从当前时间起算
        results = {}
        for ri in rule_infos:
            _update_rule_meta(ri["id"], run_at=now, advance_watermark_to=now)
            results[str(ri["id"])] = {"ok": True, "candidates": 0, "matched": 0}
        return results

    run_at = _utcnow()

    # 2) LLM 联合调用（不持有 DB session）；空输出/不可解析时重试并反馈
    try:
        prompt = _build_group_prompt(rule_infos, candidates)
        data = None
        content = ""
        last_err = "empty content"

        def _valid(d) -> bool:
            if not isinstance(d, dict):
                return False
            return all(isinstance(d.get(ri["key"]), dict) for ri in rule_infos)

        for attempt in range(3):
            content = _get_llm_client().chat_sync(
                prompt, max_tokens=_TRIAGE_MAX_TOKENS, temperature=0.2,
            )
            data = LLMClient.safe_json(content, default=None)
            if _valid(data):
                break
            if not content:
                last_err = "AI 返回了空内容"
            else:
                last_err = f"LLM 返回内容无法解析为 JSON: {(content or '')[:200]}"
            if attempt < 2:
                logger.warning(
                    "AI triage parse failed for rules %s (attempt %d/3): %s — 重试",
                    [ri["id"] for ri in rule_infos], attempt + 1, last_err,
                )
                prompt = (
                    f"{prompt}\n\n上一个回答不符合要求的 JSON 格式"
                    f"（你回答的是：{(content or '')[:200]}）。"
                    f"必须为每条规则输出一个 key（{', '.join(ri['key'] for ri in rule_infos)}），"
                    f"只输出 JSON，不要输出任何其他文字或问题。"
                )
        if not _valid(data):
            raise ValueError(last_err)

        # 3) 按序号映射回条目，得到每条规则的命中 dict
        index_map = {i + 1: c for i, c in enumerate(candidates)}
        matches_per_rule: dict = {}
        for ri in rule_infos:
            matches: dict = {}
            raw_matches = (data.get(ri["key"]) or {}).get("matches") or []
            if not isinstance(raw_matches, list):
                raw_matches = []
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
            matches_per_rule[ri["id"]] = matches
    except Exception as e:
        logger.exception("AI triage failed for rules %s", [ri["id"] for ri in rule_infos])
        for ri in rule_infos:
            _update_rule_meta(ri["id"], run_at=run_at, error=str(e))
        return {str(ri["id"]): {"ok": False, "error": str(e)} for ri in rule_infos}

    # 3.5) 第二段 agent 复核：组内命中候选去重后一次复核，剔除误报
    _apply_agent_review_group(rule_infos, candidates, matches_per_rule)

    # 4) 逐规则落库（独立短事务）
    results = {}
    for ri in rule_infos:
        _persist_result(ri["id"], candidates, matches_per_rule[ri["id"]], run_at)
        results[str(ri["id"])] = {"ok": True, "candidates": len(candidates),
                                  "matched": len(matches_per_rule[ri["id"]])}
    return results


def _apply_agent_review_group(rule_infos: list, candidates: list, matches_per_rule: dict):
    """组内联合 agent 复核（matches_per_rule 各字典原地修改）。

    把各规则命中的候选按候选去重（同一条候选带"命中它的规则+粗筛理由"列表），
    一次 agent 会话完成整组复核；复核范围截断到 AI_TRIAGE_AGENT_MAX_CANDIDATES，
    范围外命中保留粗筛结论；复核失败时全部回退粗筛结果。
    """
    if not Config.AI_TRIAGE_AGENT_REVIEW or not any(matches_per_rule.values()):
        return
    from app.services.ai_triage_agent import review_group

    key_to_index = {}
    for i, c in enumerate(candidates, start=1):
        if c["type"] == "commit":
            key_to_index[("commit", c["repo"], c["sha"])] = i
        else:
            key_to_index[(c["type"], c["repo"], c["number"])] = i

    # 按候选去重：一条候选只进一次复核会话
    entries: dict = {}
    for ri in rule_infos:
        for key, reason in matches_per_rule.get(ri["id"], {}).items():
            idx = key_to_index.get(key)
            if idx is None:
                continue
            entry = entries.setdefault(idx, dict(candidates[idx - 1], index=idx, hits={}))
            entry["hits"][ri["key"]] = reason
    matched_for_review = [entries[i] for i in sorted(entries)]
    matched_for_review = matched_for_review[:Config.AI_TRIAGE_AGENT_MAX_CANDIDATES]
    if not matched_for_review:
        return

    reviewed = review_group(rule_infos, matched_for_review)
    if reviewed is None:
        return
    review_scope = {e["index"] for e in matched_for_review}
    for ri in rule_infos:
        verdict = reviewed.get(ri["key"], {})
        matches = matches_per_rule.get(ri["id"], {})
        for key in list(matches):
            idx = key_to_index.get(key)
            if idx not in review_scope:
                continue
            if idx in verdict:
                matches[key] = verdict[idx]
            else:
                del matches[key]  # agent 复核剔除
    logger.info("agent review for rules %s: %s candidates, kept %s",
                [ri["id"] for ri in rule_infos], len(matched_for_review),
                {k: len(v) for k, v in reviewed.items()})


def run_all_rules() -> dict:
    """遍历全部 enabled 规则分诊：候选集相同的规则合组共享一次 LLM 调用。

    组间互不影响；组内某环节失败只影响组内规则。
    """
    db = SessionLocal()
    try:
        rules = (
            db.query(AIRule)
            .filter(AIRule.enabled == True)  # noqa: E712
            .order_by(AIRule.sort_order, AIRule.id).all()
        )
    finally:
        db.close()

    groups: dict = {}
    for rule in rules:
        groups.setdefault(_group_key(rule), []).append(rule)

    results = {}
    for group in groups.values():
        try:
            results.update(_run_group(group, rerun_rule_ids=set()))
        except Exception as e:
            logger.exception("AI triage crashed for rule group %s", [r.id for r in group])
            for r in group:
                results[str(r.id)] = {"ok": False, "error": str(e)}
    return results
