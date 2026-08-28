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
from app.models import AIRule, AIRuleMatch, Item
from app.services.llm import LLMClient
from app.services.prompt_utils import render_prompt

logger = logging.getLogger(__name__)

# 单条 prompt 里条目正文的截断长度
_ITEM_BODY_LIMIT = 500
# 单次 LLM 输出上限（每条命中一段 reason，对 100 条候选足够）
_TRIAGE_MAX_TOKENS = 4096

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


def _build_prompt(rule_name: str, rule_prompt: str, candidates: list) -> str:
    entries = []
    for i, c in enumerate(candidates, start=1):
        try:
            labels = ", ".join(json.loads(c["labels"])) if c["labels"] else "无"
        except (ValueError, TypeError):
            labels = c["labels"] or "无"
        entries.append({
            "index": i,
            "repo": c["repo"],
            "number": c["number"],
            "type": c["type"],
            "state": c["state"] or "unknown",
            "title": c["title"],
            "labels": labels,
            "area": c["area"] or "无",
            "body": (c["body"] or "（无正文）")[:_ITEM_BODY_LIMIT],
        })
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


def _persist_result(rule_id: int, cand_keys: list, matched_keys: set,
                    matches: dict, run_at: datetime):
    """把一轮分诊结果写入/清理 matches，并推进水位线（独立短事务）"""
    db = SessionLocal()
    try:
        rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
        if not rule:
            return
        cand_set = set(cand_keys)
        # 本轮候选中曾经命中、这轮重新评估后不再命中的旧 match 要清掉
        for row in db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule_id).all():
            key = (row.repo, row.item_type, row.number)
            if key in cand_set and key not in matched_keys:
                db.delete(row)
        for key, reason in matches.items():
            repo, item_type, number = key
            row = db.query(AIRuleMatch).filter_by(
                rule_id=rule_id, repo=repo, item_type=item_type, number=number
            ).first()
            if row:
                row.reason = reason
                row.matched_at = run_at
            else:
                db.add(AIRuleMatch(
                    rule_id=rule_id, repo=repo, item_type=item_type,
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
    finally:
        db.close()

    if not candidates:
        # 空跑也推进水位线，下轮从当前时间起算
        now = _utcnow()
        _update_rule_meta(rule_id, run_at=now, advance_watermark_to=now)
        return {"ok": True, "candidates": 0, "matched": 0}

    run_at = _utcnow()

    # 2) LLM 调用（不持有 DB session）
    try:
        prompt = _build_prompt(rule_name, rule_prompt, candidates)
        content = _get_llm_client().chat_sync(
            prompt, max_tokens=_TRIAGE_MAX_TOKENS, temperature=0.2,
        )
        data = LLMClient.safe_json(content, default=None)
        if not isinstance(data, dict):
            raise ValueError(f"LLM 返回内容无法解析为 JSON: {(content or '')[:200]}")
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
        key = (cand["repo"], cand["type"], cand["number"])
        matches[key] = (m.get("reason") or "").strip()[:500]

    cand_keys = [(c["repo"], c["type"], c["number"]) for c in candidates]
    _persist_result(rule_id, cand_keys, set(matches), matches, run_at)
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
