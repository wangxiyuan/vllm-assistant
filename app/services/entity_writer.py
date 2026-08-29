"""
实体写入服务

供 HTTP 路由（app/api/*）与 AI agent 写类工具（app/services/tools/write_tools.py）共用的
创建/更新/删除逻辑。所有函数接收显式传入的 db Session，不自行开关会话。

规则字段校验沿用 HTTPException（路由直接透传；工具侧捕获后转成 {"error": detail}）。
"""
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    AIRule,
    AIRuleCommitMatch,
    AIRuleMatch,
    Article,
    IntelligenceReport,
    PersonalTask,
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
# 个人任务
# ======================================================================


def _parse_due_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"due_date 格式应为 YYYY-MM-DD: {value}")


def create_task(db: Session, fields: dict) -> dict:
    """fields: title(必填), description, source, priority, area, assignee_id,
    tags(list), due_date(YYYY-MM-DD), related_refs(list), parent_id, subtask_order"""
    title = (fields.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="任务标题不能为空")
    now = _utcnow()
    tags = fields.get("tags")
    related_refs = fields.get("related_refs")
    task = PersonalTask(
        title=title,
        description=fields.get("description") or "",
        source=fields.get("source") or "self",
        priority=fields.get("priority") or "P2",
        status="todo",
        area=fields.get("area") or None,
        assignee_id=fields.get("assignee_id"),
        tags=json.dumps(tags, ensure_ascii=False) if tags else None,
        due_date=_parse_due_date(fields.get("due_date")),
        related_refs=related_refs if related_refs else None,
        parent_id=fields.get("parent_id"),
        subtask_order=fields.get("subtask_order") or 0,
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task.to_dict()


def update_task(db: Session, task_id: int, fields: dict) -> dict:
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if "tags" in fields:
        value = fields["tags"]
        task.tags = json.dumps(value, ensure_ascii=False) if value else None
    if "related_refs" in fields:
        value = fields["related_refs"]
        task.related_refs = value if value else None
    if "status" in fields:
        value = fields["status"]
        if value == "done" and task.status != "done":
            task.completed_at = _utcnow()
        elif value != "done":
            task.completed_at = None
        task.status = value
    if "due_date" in fields:
        task.due_date = _parse_due_date(fields["due_date"])
    if "area" in fields:
        task.area = fields["area"] or None
    for key in ("title", "description", "priority", "assignee_id", "parent_id", "subtask_order"):
        if key in fields:
            setattr(task, key, fields[key])
    task.updated_at = _utcnow()

    db.commit()
    db.refresh(task)
    return task.to_dict()


def delete_task(db: Session, task_id: int) -> dict:
    """级联清理：子任务 + 关联的洞察报告"""
    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.query(PersonalTask).filter(PersonalTask.parent_id == task_id).delete()
    db.query(IntelligenceReport).filter(IntelligenceReport.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    return {"deleted": True, "id": task_id}


# ======================================================================
# 学习文章
# ======================================================================


def create_article(db: Session, fields: dict) -> dict:
    """fields: title(必填), content(必填), area, tags(list), status, user_id"""
    title = (fields.get("title") or "").strip()
    content = fields.get("content") or ""
    if not title:
        raise HTTPException(status_code=400, detail="文章标题不能为空")
    if not content.strip():
        raise HTTPException(status_code=400, detail="文章内容不能为空")
    tags = fields.get("tags")
    now = _utcnow()
    article = Article(
        title=title,
        content=content,
        area=fields.get("area") or None,
        tags=json.dumps(tags, ensure_ascii=False) if tags else None,
        user_id=fields.get("user_id"),
        status=fields.get("status") or "draft",
        created_at=now,
        updated_at=now,
    )
    db.add(article)
    db.commit()
    db.refresh(article)

    from app.services.code_ref_parser import CodeRefParser

    parser = CodeRefParser()
    refs_result = parser.save_article_refs(article.id, article.content, db)

    # 同步到知识库（仅 published 文章会被索引）
    if article.status == "published":
        _sync_articles_memory(article.id)

    return {
        "id": article.id,
        "title": article.title,
        "status": article.status,
        "created_at": article.created_at.isoformat(),
        "refs_count": refs_result["total_refs"],
    }


def update_article(db: Session, article_id: int, fields: dict) -> dict:
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    if fields.get("title") is not None:
        article.title = fields["title"]
    if fields.get("content") is not None:
        article.content = fields["content"]
    if fields.get("area") is not None:
        article.area = fields["area"] or None
    if fields.get("tags") is not None:
        article.tags = json.dumps(fields["tags"], ensure_ascii=False)
    if fields.get("status") is not None:
        article.status = fields["status"]
    if fields.get("user_id") is not None:
        article.user_id = fields["user_id"]

    article.updated_at = _utcnow()

    from app.services.code_ref_parser import CodeRefParser

    parser = CodeRefParser()
    parser.save_article_refs(article.id, article.content, db)

    article.rendered_html = None
    db.commit()
    db.refresh(article)

    if article.status == "published":
        _sync_articles_memory(article.id)

    return article.to_dict()


def delete_article(db: Session, article_id: int) -> dict:
    """级联删除评论和知识库内容"""
    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    from app.models import Comment
    from app.services.memory_service import MemoryService

    mem = MemoryService()
    mem.forget_by_source_ref_prefix(f"article#{article_id}", hard_delete=True)

    db.query(Comment).filter(
        Comment.target_type == "article",
        Comment.target_id == article_id,
    ).delete()

    db.delete(article)
    db.commit()
    return {"deleted": True, "id": article_id}


def _sync_articles_memory(article_id: int) -> None:
    try:
        from app.services.memory_service import MemoryService

        mem = MemoryService()
        mem._build_from_articles()
        logger.info(f"Knowledge base synced after article write: id={article_id}")
    except Exception:
        logger.exception(f"Failed to sync knowledge base after article write: id={article_id}")


# ======================================================================
# 洞察报告（触发生成，后台线程执行）
# ======================================================================


def start_intelligence_report(
    *,
    title: str = "",
    sources: Optional[list] = None,
    excluded_sources: Optional[list] = None,
    extra_prompt: str = "",
    task_id: Optional[int] = None,
    user_id: Optional[int] = None,
    report_id: Optional[int] = None,
) -> dict:
    """创建（或重置）一份 status=generating 的报告并启动后台生成线程。

    返回 {"report_id", "title", "status"}。与 /api/intelligence/reports/generate 行为一致。
    """
    if not task_id and not (title or "").strip():
        raise HTTPException(status_code=400, detail="title 不能为空（或提供 task_id）")

    from app.config import Config

    if not Config.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")

    db = None
    try:
        from app.database import SessionLocal

        db = SessionLocal()
        task_title = ""
        task_description = ""
        if task_id:
            task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
            if not task:
                raise HTTPException(status_code=404, detail="Task not found")
            task_title = task.title
            task_description = task.description or ""

        final_title = title or (f"{task_title} 相关动态洞察" if task_id else "洞察报告")

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
                task_id=task_id,
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
            args=(report.id, task_title, task_description, sources or [], excluded_sources, extra_prompt),
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
