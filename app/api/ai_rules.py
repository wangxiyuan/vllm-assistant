"""
AI 筛选规则 API（总览页）

规则 CRUD + 手动触发分诊 + 命中结果查询。
规则是全局的（无用户维度）；命中结果 join items 返回展示字段。
"""
import json
import logging
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AIRule, AIRuleMatch, Item

logger = logging.getLogger(__name__)
router = APIRouter()

# 防止同一规则并发跑多个分诊（API 手动触发 vs scheduler 周期任务）
_running_rules: set = set()
_running_lock = threading.Lock()


def _parse_str_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _clean_rule_fields(payload: dict, partial: bool = False) -> dict:
    """校验并提取规则字段。partial=True 时只处理 payload 里出现的键。"""
    fields = {}

    def has(key: str) -> bool:
        return not partial or key in payload

    if has("name"):
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="规则名称不能为空")
        fields["name"] = name[:100]
    if has("prompt"):
        prompt = (payload.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="筛选要求不能为空")
        fields["prompt"] = prompt
    if has("item_type"):
        item_type = payload.get("item_type") or "both"
        if item_type not in ("pr", "issue", "both"):
            raise HTTPException(status_code=400, detail="item_type 必须是 pr/issue/both")
        fields["item_type"] = item_type
    if has("repos"):
        fields["repos"] = json.dumps(_parse_str_list(payload.get("repos")), ensure_ascii=False)
    if has("areas"):
        fields["areas"] = json.dumps(_parse_str_list(payload.get("areas")), ensure_ascii=False)
    if has("enabled"):
        fields["enabled"] = bool(payload.get("enabled", True))
    if has("sort_order"):
        try:
            fields["sort_order"] = int(payload.get("sort_order") or 0)
        except (TypeError, ValueError):
            fields["sort_order"] = 0
    return fields


@router.get("")
async def list_rules(db: Session = Depends(get_db)):
    """规则列表（带各自命中数），按 sort_order 排序"""
    rows = (
        db.query(AIRule, func.count(AIRuleMatch.id))
        .outerjoin(AIRuleMatch, AIRuleMatch.rule_id == AIRule.id)
        .group_by(AIRule.id)
        .order_by(AIRule.sort_order, AIRule.id)
        .all()
    )
    return {"rules": [rule.to_dict(match_count=count or 0) for rule, count in rows]}


@router.post("")
async def create_rule(payload: dict, db: Session = Depends(get_db)):
    fields = _clean_rule_fields(payload)
    rule = AIRule(**fields)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule.to_dict(match_count=0)


@router.put("/{rule_id}")
async def update_rule(rule_id: int, payload: dict, db: Session = Depends(get_db)):
    rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    for key, value in _clean_rule_fields(payload, partial=True).items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    count = db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule_id).count()
    return rule.to_dict(match_count=count)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule_id).delete()
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


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
        d["matched_at"] = match.matched_at.isoformat() + "Z" if match.matched_at else None
        items.append(d)
    return {"items": items}
