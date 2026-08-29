"""
AI 筛选规则 API（总览页）

规则 CRUD + 手动触发分诊 + 命中结果查询。
规则是全局的（无用户维度）；命中结果 join items 返回展示字段。
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AIRule, AIRuleCommitMatch, AIRuleMatch, Item
from app.services import entity_writer

logger = logging.getLogger(__name__)
router = APIRouter()

# 防止同一规则并发跑多个分诊（API 手动触发 vs scheduler 周期任务）
_running_rules: set = set()
_running_lock = threading.Lock()


def _commit_match_counts(db, rule_ids: list) -> dict:
    """按 rule_id 统计 commit 命中数"""
    if not rule_ids:
        return {}
    rows = (
        db.query(AIRuleCommitMatch.rule_id, func.count(AIRuleCommitMatch.id))
        .filter(AIRuleCommitMatch.rule_id.in_(rule_ids))
        .group_by(AIRuleCommitMatch.rule_id)
        .all()
    )
    return dict(rows)


def _match_is_new(matched_at) -> bool:
    """命中标识：首次命中时间在 24 小时内视为新命中"""
    if not matched_at:
        return False
    if matched_at.tzinfo is None:
        matched_at = matched_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - matched_at) < timedelta(hours=24)


@router.get("")
async def list_rules(db: Session = Depends(get_db)):
    """规则列表（带各自命中数：条目 + commit），按 sort_order 排序"""
    rules = (
        db.query(AIRule)
        .order_by(AIRule.sort_order, AIRule.id)
        .all()
    )
    item_counts = dict(
        db.query(AIRuleMatch.rule_id, func.count(AIRuleMatch.id))
        .group_by(AIRuleMatch.rule_id)
        .all()
    )
    commit_counts = _commit_match_counts(db, [r.id for r in rules])
    return {
        "rules": [
            rule.to_dict(match_count=(item_counts.get(rule.id, 0) + commit_counts.get(rule.id, 0)))
            for rule in rules
        ]
    }


@router.post("")
async def create_rule(payload: dict, db: Session = Depends(get_db)):
    return entity_writer.create_rule(db, payload)


@router.put("/{rule_id}")
async def update_rule(rule_id: int, payload: dict, db: Session = Depends(get_db)):
    return entity_writer.update_rule(db, rule_id, payload)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    return entity_writer.delete_rule(db, rule_id)


@router.post("/{rule_id}/run")
async def run_rule(rule_id: int, rerun: bool = False, db: Session = Depends(get_db)):
    """后台触发一次分诊（不阻塞请求）。

    rerun=true：清空该规则旧命中并把水位线回拨 N 天，重新评估近期条目。
    """
    rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")

    with _running_lock:
        if rule_id in _running_rules:
            return {"triggered": False, "reason": "already running", "rule_id": rule_id}
        _running_rules.add(rule_id)

    def _worker():
        try:
            from app.services.ai_triage import run_triage
            result = run_triage(rule_id, rerun=rerun)
            logger.info("Manual triage for rule %s: %s", rule_id, result)
        except Exception:
            logger.exception("Manual triage for rule %s failed", rule_id)
        finally:
            with _running_lock:
                _running_rules.discard(rule_id)

    threading.Thread(target=_worker, daemon=True, name=f"rule-run-{rule_id}").start()
    return {"triggered": True, "rerun": rerun, "rule_id": rule_id}


@router.get("/{rule_id}/matches")
async def get_rule_matches(
    rule_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """规则的命中条目列表（join items 取展示字段；条目已被清理时返回占位信息）"""
    rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")

    from app.api.community import _item_to_response_dict

    rows = (
        db.query(AIRuleMatch, Item)
        .outerjoin(
            Item,
            (Item.repo == AIRuleMatch.repo)
            & (Item.type == AIRuleMatch.item_type)
            & (Item.number == AIRuleMatch.number),
        )
        .filter(AIRuleMatch.rule_id == rule_id)
        .order_by(AIRuleMatch.matched_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for match, item in rows:
        if item is not None:
            d = _item_to_response_dict(item)
        else:
            # 条目已被数据清理任务删除，保留最小占位信息
            d = {
                "repo": match.repo, "type": match.item_type, "number": match.number,
                "title": None, "state": None, "labels": [], "area": None,
                "is_new": False,
            }
        d["rule_id"] = rule_id
        d["reason"] = match.reason or ""
        d["is_new"] = _match_is_new(match.matched_at)
        d["matched_at"] = match.matched_at.isoformat() + "Z" if match.matched_at else None
        items.append(d)

    # commit 命中（无 number/sha 无法 join items，冗余字段直接从命中表返回）
    commit_rows = (
        db.query(AIRuleCommitMatch)
        .filter(AIRuleCommitMatch.rule_id == rule_id)
        .order_by(AIRuleCommitMatch.matched_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    for match in commit_rows:
        items.append({
            "repo": match.repo,
            "type": "commit",
            "number": 0,
            "sha": match.sha,
            "short_sha": match.short_sha or (match.sha[:7] if match.sha else ""),
            "title": match.title,
            "state": "merged",
            "author": match.author,
            "committed_at": match.committed_at.isoformat() + "Z" if match.committed_at else None,
            "created_at": match.committed_at.isoformat() + "Z" if match.committed_at else None,
            "labels": [], "area": None, "comments": 0,
            "is_new": _match_is_new(match.matched_at),
            "rule_id": rule_id,
            "reason": match.reason or "",
            "matched_at": match.matched_at.isoformat() + "Z" if match.matched_at else None,
        })
    return {"items": items}
