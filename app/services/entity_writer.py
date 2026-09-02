"""
实体写入服务

供 HTTP 路由（app/api/*）与 AI agent 写类工具（app/services/tools/write_tools.py）共用的
创建/更新/删除逻辑。所有函数接收显式传入的 db Session，不自行开关会话。

规则字段校验沿用 HTTPException（路由直接透传；工具侧捕获后转成 {"error": detail}）。
"""
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    AIRule,
    AIRuleCommitMatch,
    AIRuleMatch,
    IntelligenceReport,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ======================================================================
# AI 筛选规则
# ======================================================================


def _parse_str_list(value) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def clean_rule_fields(payload: dict, partial: bool = False) -> dict:
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
        if item_type not in ("pr", "issue", "both", "commit"):
            raise HTTPException(status_code=400, detail="item_type 必须是 pr/issue/both/commit")
        fields["item_type"] = item_type
    if has("include_commits"):
        fields["include_commits"] = bool(payload.get("include_commits", True))
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


def create_rule(db: Session, payload: dict) -> dict:
    fields = clean_rule_fields(payload)
    rule = AIRule(**fields)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule.to_dict(match_count=0)


def update_rule(db: Session, rule_id: int, payload: dict) -> dict:
    rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    for key, value in clean_rule_fields(payload, partial=True).items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    count = (
        db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule_id).count()
        + db.query(AIRuleCommitMatch).filter(AIRuleCommitMatch.rule_id == rule_id).count()
    )
    return rule.to_dict(match_count=count)


def delete_rule(db: Session, rule_id: int) -> dict:
    rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    db.query(AIRuleMatch).filter(AIRuleMatch.rule_id == rule_id).delete()
    db.query(AIRuleCommitMatch).filter(AIRuleCommitMatch.rule_id == rule_id).delete()
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


# ======================================================================
# 洞察报告（触发生成，后台线程执行）
# ======================================================================


def start_intelligence_report(
    *,
    title: str = "",
    sources: Optional[list] = None,
    excluded_sources: Optional[list] = None,
    extra_prompt: str = "",
    user_id: Optional[int] = None,
    report_id: Optional[int] = None,
) -> dict:
    """创建（或重置）一份 status=generating 的报告并启动后台生成线程。

    返回 {"report_id", "title", "status"}。与 /api/intelligence/reports/generate 行为一致。
    """
    if not (title or "").strip():
        raise HTTPException(status_code=400, detail="title 不能为空")

    from app.config import Config

    if not Config.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")

    db = None
    try:
        from app.database import SessionLocal

        db = SessionLocal()
        final_title = title.strip()

        if report_id:
            report = db.query(IntelligenceReport).filter(IntelligenceReport.id == report_id).first()
            if not report:
                raise HTTPException(status_code=404, detail="Report not found")
            report.title = final_title
            report.content = ""
            report.sources = json.dumps(sources or [], ensure_ascii=False)
            report.excluded_sources = (
                json.dumps(excluded_sources, ensure_ascii=False) if excluded_sources else None
            )
            report.extra_prompt = extra_prompt or None
            report.status = "generating"
            report.error_message = None
            report.created_at = _utcnow()
            db.commit()
            db.refresh(report)
        else:
            report = IntelligenceReport(
                title=final_title,
                content="",
                user_id=user_id,
                sources=json.dumps(sources or [], ensure_ascii=False),
                excluded_sources=(
                    json.dumps(excluded_sources, ensure_ascii=False) if excluded_sources else None
                ),
                extra_prompt=extra_prompt or None,
                created_at=_utcnow(),
                status="generating",
            )
            db.add(report)
            db.commit()
            db.refresh(report)

        # 延迟导入避免循环依赖（api.intelligence 不在模块级引用本模块）
        from app.api.intelligence import _generate_report_background

        threading.Thread(
            target=_generate_report_background,
            args=(report.id, final_title, extra_prompt, sources or [], excluded_sources),
            daemon=True,
        ).start()

        return {"report_id": report.id, "title": final_title, "status": "generating"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to start intelligence report")
        raise HTTPException(status_code=500, detail="Failed to generate report")
    finally:
        if db is not None:
            db.close()
