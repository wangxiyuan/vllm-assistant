"""
写类工具（write category）

让 AI agent 可以创建/更新/删除本项目的实体：筛选规则、个人任务、学习文章、
模型拆解（YAML 导入）、洞察报告。业务逻辑全部委托给 app/services/entity_writer.py
与 app/api/model_anatomy.py:run_yaml_import，本模块只做参数适配与会话管理。

安全约定：
- delete_* 工具在 confirm != true 时只返回待删对象详情，不执行删除；
  system prompt 要求 AI 先向用户复述并征得明确同意后才允许 confirm=true。
- 文章默认创建为 draft，发布需显式传 status="published"。
"""
import logging

from fastapi import HTTPException

from app.services.tools.registry import register_tool

logger = logging.getLogger(__name__)


def _run_db(fn, *args, **kwargs) -> dict:
    """开一个短会话执行 entity_writer 操作，统一异常转 error dict。"""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = fn(db, *args, **kwargs)
        db.close()
        return result
    except HTTPException as e:
        db.close()
        return {"error": e.detail}
    except Exception as e:
        db.close()
        logger.exception("write tool failed")
        return {"error": str(e)}


def _derive_item_types(args: dict) -> dict:
    """把 watch_pr/watch_issue/watch_commit 三开关推导为 item_type + include_commits。

    与前端 stores/rules.ts:deriveItemTypes 语义一致：
    PR/Issue 都不选 = 仅 Commit 规则。
    """
    pr = bool(args.get("watch_pr", False))
    issue = bool(args.get("watch_issue", False))
    commit = bool(args.get("watch_commit", False))
    if not pr and not issue:
        return {"item_type": "commit", "include_commits": True}
    return {
        "item_type": "both" if (pr and issue) else ("pr" if pr else "issue"),
        "include_commits": commit,
    }


def _rule_payload(args: dict, partial: bool) -> dict:
    payload = {}
    if not partial or "name" in args:
        if args.get("name"):
            payload["name"] = args["name"]
    if not partial or "prompt" in args:
        if args.get("prompt"):
            payload["prompt"] = args["prompt"]
    if any(k in args for k in ("watch_pr", "watch_issue", "watch_commit")):
        payload.update(_derive_item_types(args))
    for key in ("repos", "areas"):
        if key in args and isinstance(args[key], list):
            payload[key] = args[key]
    if "enabled" in args:
        payload["enabled"] = bool(args["enabled"])
    return payload


# ======================================================================
# 筛选规则
# ======================================================================

CREATE_RULE = {
    "type": "function",
    "function": {
        "name": "create_rule",
        "description": "创建一条 AI 筛选规则（总览页）。规则用自然语言 prompt 描述筛选要求，定时任务会对社区 PR/Issue/Commit 做分诊并记录命中。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "规则名称，简短，如 'KV Cache 性能优化'"},
                "prompt": {"type": "string", "description": "筛选要求（自然语言），说明什么样的 PR/Issue/Commit 算命中，例如 '涉及 KV Cache 分配或复用机制的性能优化，且包含基准测试数据'"},
                "watch_pr": {"type": "boolean", "description": "是否筛 PR，默认 true"},
                "watch_issue": {"type": "boolean", "description": "是否筛 Issue，默认 true"},
                "watch_commit": {"type": "boolean", "description": "是否筛 Commit，默认 false"},
                "repos": {"type": "array", "items": {"type": "string"}, "description": "生效仓库列表（owner/repo 或仓库短名）。空 = 全部已配置仓库"},
                "areas": {"type": "array", "items": {"type": "string"}, "description": "所属领域标签，如 ['attention', 'performance']"},
                "enabled": {"type": "boolean", "description": "是否启用，默认 true"},
            },
            "required": ["name", "prompt"],
        },
    },
}


async def handle_create_rule(args: dict) -> dict:
    from app.services import entity_writer

    payload = _rule_payload(args, partial=False)
    payload.setdefault("enabled", True)
    result = _run_db(entity_writer.create_rule, payload)
    if "error" not in result:
        result["entity"] = "rule"
        result["page"] = "/overview"
    return result


UPDATE_RULE = {
    "type": "function",
    "function": {
        "name": "update_rule",
        "description": "更新一条 AI 筛选规则。先用 list_entities 找到 rule_id。",
        "parameters": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer", "description": "规则 ID"},
                "name": {"type": "string"},
                "prompt": {"type": "string", "description": "筛选要求全文（整体替换）"},
                "watch_pr": {"type": "boolean"},
                "watch_issue": {"type": "boolean"},
                "watch_commit": {"type": "boolean"},
                "repos": {"type": "array", "items": {"type": "string"}},
                "areas": {"type": "array", "items": {"type": "string"}},
                "enabled": {"type": "boolean"},
            },
            "required": ["rule_id"],
        },
    },
}


async def handle_update_rule(args: dict) -> dict:
    from app.services import entity_writer

    rule_id = args.pop("rule_id", None)
    if not rule_id:
        return {"error": "rule_id is required"}
    payload = _rule_payload(args, partial=True)
    if not payload:
        return {"error": "没有提供任何要更新的字段"}
    result = _run_db(entity_writer.update_rule, rule_id, payload)
    if "error" not in result:
        result["entity"] = "rule"
        result["page"] = "/overview"
    return result


DELETE_RULE = {
    "type": "function",
    "function": {
        "name": "delete_rule",
        "description": "删除一条 AI 筛选规则（连同其命中记录）。必须先向用户复述规则名称并征得明确同意后，才能以 confirm=true 调用；否则仅返回待删对象详情。",
        "parameters": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "integer"},
                "confirm": {"type": "boolean", "description": "用户明确同意删除后传 true"},
            },
            "required": ["rule_id"],
        },
    },
}


async def handle_delete_rule(args: dict) -> dict:
    from app.services import entity_writer

    rule_id = args.get("rule_id")
    if not rule_id:
        return {"error": "rule_id is required"}
    if not args.get("confirm"):
        detail = _run_db(_get_rule_detail, rule_id)
        return {
            "status": "needs_confirmation",
            "message": "请向用户复述以下规则并征得明确同意后，再次调用本工具并传 confirm=true",
            "target": detail,
        }
    result = _run_db(entity_writer.delete_rule, rule_id)
    if "error" not in result:
        result["entity"] = "rule"
        result["page"] = "/overview"
    return result


def _get_rule_detail(db, rule_id: int) -> dict:
    from app.models import AIRule

    rule = db.query(AIRule).filter(AIRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="rule not found")
    d = rule.to_dict(match_count=0)
    return {"id": d["id"], "name": d["name"], "prompt": d["prompt"], "enabled": d["enabled"]}


# ======================================================================
# 个人任务
# ======================================================================

CREATE_TASK = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "创建一条个人任务（任务面板）。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "任务标题"},
                "description": {"type": "string", "description": "任务描述/目标，支持 Markdown"},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "description": "优先级，默认 P2"},
                "area": {"type": "string", "description": "所属领域，如 'attention'"},
                "due_date": {"type": "string", "description": "截止日期 YYYY-MM-DD"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "related_refs": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "关联的社区条目，如 [{\"type\": \"pr\", \"number\": 123, \"repo\": \"vllm\", \"title\": \"...\", \"url\": \"...\"}]；type 为 pr 或 issue",
                },
                "parent_id": {"type": "integer", "description": "父任务 ID（创建子任务时）"},
            },
            "required": ["title"],
        },
    },
}


async def handle_create_task(args: dict) -> dict:
    from app.services import entity_writer

    fields = {k: v for k, v in args.items() if k in (
        "title", "description", "priority", "area", "due_date", "tags", "related_refs", "parent_id",
    )}
    fields["source"] = "ai"
    result = _run_db(entity_writer.create_task, fields)
    if "error" not in result:
        result["entity"] = "task"
        result["page"] = "/personal-todo"
    return result


UPDATE_TASK = {
    "type": "function",
    "function": {
        "name": "update_task",
        "description": "更新一条个人任务（标题/描述/优先级/状态/截止日期等）。先用 list_entities 找到 task_id。",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {"type": "string", "enum": ["todo", "in_progress", "done", "cancelled"]},
                "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]},
                "area": {"type": "string"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD，传空字符串清除"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task_id"],
        },
    },
}


async def handle_update_task(args: dict) -> dict:
    from app.services import entity_writer

    task_id = args.pop("task_id", None)
    if not task_id:
        return {"error": "task_id is required"}
    fields = {k: v for k, v in args.items() if k in (
        "title", "description", "status", "priority", "area", "due_date", "tags",
    )}
    if not fields:
        return {"error": "没有提供任何要更新的字段"}
    result = _run_db(entity_writer.update_task, task_id, fields)
    if "error" not in result:
        result["entity"] = "task"
        result["page"] = "/personal-todo"
    return result


DELETE_TASK = {
    "type": "function",
    "function": {
        "name": "delete_task",
        "description": "删除一条个人任务（级联删除子任务和关联洞察报告）。必须先向用户复述任务标题并征得明确同意后，才能以 confirm=true 调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "confirm": {"type": "boolean", "description": "用户明确同意删除后传 true"},
            },
            "required": ["task_id"],
        },
    },
}


async def handle_delete_task(args: dict) -> dict:
    from app.services import entity_writer

    task_id = args.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}
    if not args.get("confirm"):
        detail = _run_db(_get_task_detail, task_id)
        return {
            "status": "needs_confirmation",
            "message": "请向用户复述以下任务并征得明确同意后，再次调用本工具并传 confirm=true",
            "target": detail,
        }
    result = _run_db(entity_writer.delete_task, task_id)
    if "error" not in result:
        result["entity"] = "task"
        result["page"] = "/personal-todo"
    return result


def _get_task_detail(db, task_id: int) -> dict:
    from app.models import PersonalTask

    task = db.query(PersonalTask).filter(PersonalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    d = task.to_dict()
    return {"id": d["id"], "title": d["title"], "status": d["status"], "priority": d["priority"]}


# ======================================================================
# 学习文章
# ======================================================================

CREATE_ARTICLE = {
    "type": "function",
    "function": {
        "name": "create_article",
        "description": "创建一篇技术博客/学习文章（文章页），Markdown 正文。默认保存为草稿。正文中可用 `owner/repo/file_path:start-end` 语法引用代码片段（需在本地代码缓存中存在）。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string", "description": "Markdown 正文"},
                "area": {"type": "string", "description": "所属领域，如 'attention'"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["draft", "published"], "description": "默认 draft；published 会同步进知识库"},
            },
            "required": ["title", "content"],
        },
    },
}


async def handle_create_article(args: dict) -> dict:
    from app.services import entity_writer

    fields = {k: v for k, v in args.items() if k in ("title", "content", "area", "tags", "status")}
    fields.setdefault("status", "draft")
    result = _run_db(entity_writer.create_article, fields)
    if "error" not in result:
        result["entity"] = "article"
        result["page"] = "/articles"
    return result


UPDATE_ARTICLE = {
    "type": "function",
    "function": {
        "name": "update_article",
        "description": "更新一篇文章的标题/正文/标签/状态。content 为整篇替换；先用 list_entities 找到 article_id，长文修改前建议先取回内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "article_id": {"type": "integer"},
                "title": {"type": "string"},
                "content": {"type": "string", "description": "Markdown 正文（整篇替换）"},
                "area": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": ["draft", "published", "archived"]},
            },
            "required": ["article_id"],
        },
    },
}


async def handle_update_article(args: dict) -> dict:
    from app.services import entity_writer

    article_id = args.pop("article_id", None)
    if not article_id:
        return {"error": "article_id is required"}
    fields = {k: v for k, v in args.items() if k in ("title", "content", "area", "tags", "status")}
    if not fields:
        return {"error": "没有提供任何要更新的字段"}
    result = _run_db(entity_writer.update_article, article_id, fields)
    if "error" not in result:
        result["entity"] = "article"
        result["page"] = "/articles"
    return result


DELETE_ARTICLE = {
    "type": "function",
    "function": {
        "name": "delete_article",
        "description": "删除一篇文章（级联删除代码引用、评论和知识库内容）。必须先向用户复述文章标题并征得明确同意后，才能以 confirm=true 调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "article_id": {"type": "integer"},
                "confirm": {"type": "boolean", "description": "用户明确同意删除后传 true"},
            },
            "required": ["article_id"],
        },
    },
}


async def handle_delete_article(args: dict) -> dict:
    from app.services import entity_writer

    article_id = args.get("article_id")
    if not article_id:
        return {"error": "article_id is required"}
    if not args.get("confirm"):
        detail = _run_db(_get_article_detail, article_id)
        return {
            "status": "needs_confirmation",
            "message": "请向用户复述以下文章并征得明确同意后，再次调用本工具并传 confirm=true",
            "target": detail,
        }
    result = _run_db(entity_writer.delete_article, article_id)
    if "error" not in result:
        result["entity"] = "article"
        result["page"] = "/articles"
    return result


def _get_article_detail(db, article_id: int) -> dict:
    from app.models import Article

    article = db.query(Article).filter(Article.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"id": article.id, "title": article.title, "status": article.status}


# ======================================================================
# 模型拆解（YAML 导入）
# ======================================================================

IMPORT_ANATOMY_YAML = {
    "type": "function",
    "function": {
        "name": "import_anatomy_yaml",
        "description": "把一段模型拆解 YAML 导入模型拆解模块（积木/组装）。YAML 必须遵循 docs/model-yaml-spec.md 规范（atomic/composite/assembly 三层）。校验失败会返回错误明细；已存在的 name 会被跳过（幂等）。",
        "parameters": {
            "type": "object",
            "properties": {
                "yaml_content": {"type": "string", "description": "完整的 YAML 文本（顶层为列表）"},
            },
            "required": ["yaml_content"],
        },
    },
}


async def handle_import_anatomy_yaml(args: dict) -> dict:
    yaml_text = args.get("yaml_content", "")
    if not yaml_text.strip():
        return {"error": "yaml_content is required"}

    from app.database import SessionLocal
    from app.api.model_anatomy import run_yaml_import

    db = SessionLocal()
    try:
        result = run_yaml_import(db, yaml_text)
        data = result.model_dump() if hasattr(result, "model_dump") else result.dict()
        data["entity"] = "anatomy"
        data["page"] = "/anatomy"
        return data
    except Exception as e:
        logger.exception("anatomy yaml import failed")
        return {"error": str(e)}
    finally:
        db.close()


# ======================================================================
# 洞察报告
# ======================================================================

GENERATE_INTELLIGENCE_REPORT = {
    "type": "function",
    "function": {
        "name": "generate_intelligence_report",
        "description": "触发一份洞察报告的后台生成（洞察面板）。创建 status=generating 的报告并立即返回 report_id，生成约需 2-5 分钟，用户可在洞察页看到进度。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "报告标题（有关联任务时可省略）"},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "情报来源列表（仓库名/academic/news）。空 = 全部可用来源"},
                "extra_prompt": {"type": "string", "description": "额外关注点/要求"},
                "task_id": {"type": "integer", "description": "关联任务 ID（可选）"},
            },
        },
    },
}


async def handle_generate_intelligence_report(args: dict) -> dict:
    from app.services import entity_writer

    try:
        result = entity_writer.start_intelligence_report(
            title=args.get("title") or "",
            sources=args.get("sources") or [],
            excluded_sources=[],
            extra_prompt=args.get("extra_prompt") or "",
            task_id=args.get("task_id"),
        )
    except HTTPException as e:
        return {"error": e.detail}
    except Exception as e:
        return {"error": str(e)}
    result["entity"] = "report"
    result["page"] = "/intelligence"
    return result


# ======================================================================
# 实体检索（供更新/删除前定位 id）
# ======================================================================

LIST_ENTITIES = {
    "type": "function",
    "function": {
        "name": "list_entities",
        "description": "列出规则/任务/文章的 id 与摘要，用于更新或删除前定位目标。支持关键词过滤。",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string", "enum": ["rule", "task", "article", "report"]},
                "query": {"type": "string", "description": "标题/名称关键词过滤（可选）"},
                "limit": {"type": "integer", "description": "返回条数，默认 20，最大 50"},
            },
            "required": ["entity_type"],
        },
    },
}


async def handle_list_entities(args: dict) -> dict:
    entity_type = args.get("entity_type", "")
    query = (args.get("query") or "").strip()
    limit = min(int(args.get("limit", 20) or 20), 50)

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        if entity_type == "rule":
            from app.models import AIRule

            q = db.query(AIRule)
            if query:
                q = q.filter(AIRule.name.like(f"%{query}%"))
            rows = q.order_by(AIRule.sort_order, AIRule.id).limit(limit).all()
            items = [
                {"id": r.id, "title": r.name, "detail": (r.prompt or "")[:120], "enabled": r.enabled}
                for r in rows
            ]
        elif entity_type == "task":
            from app.models import PersonalTask

            q = db.query(PersonalTask).filter(PersonalTask.parent_id.is_(None))
            if query:
                q = q.filter(PersonalTask.title.like(f"%{query}%"))
            rows = q.order_by(PersonalTask.updated_at.desc()).limit(limit).all()
            items = [
                {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority}
                for t in rows
            ]
        elif entity_type == "article":
            from app.models import Article

            q = db.query(Article)
            if query:
                q = q.filter(Article.title.like(f"%{query}%"))
            rows = q.order_by(Article.updated_at.desc()).limit(limit).all()
            items = [
                {"id": a.id, "title": a.title, "status": a.status, "area": a.area}
                for a in rows
            ]
        elif entity_type == "report":
            from app.models import IntelligenceReport

            q = db.query(IntelligenceReport)
            if query:
                q = q.filter(IntelligenceReport.title.like(f"%{query}%"))
            rows = q.order_by(IntelligenceReport.created_at.desc()).limit(limit).all()
            items = [
                {"id": r.id, "title": r.title, "status": r.status, "category": r.category}
                for r in rows
            ]
        else:
            return {"error": "entity_type 必须是 rule/task/article/report"}
        return {"entity_type": entity_type, "items": items, "total": len(items)}
    except Exception as e:
        logger.exception("list_entities failed")
        return {"error": str(e)}
    finally:
        db.close()


# ======================================================================
# 注册
# ======================================================================

register_tool("create_rule", CREATE_RULE, handle_create_rule)
register_tool("update_rule", UPDATE_RULE, handle_update_rule)
register_tool("delete_rule", DELETE_RULE, handle_delete_rule)
register_tool("create_task", CREATE_TASK, handle_create_task)
register_tool("update_task", UPDATE_TASK, handle_update_task)
register_tool("delete_task", DELETE_TASK, handle_delete_task)
register_tool("create_article", CREATE_ARTICLE, handle_create_article)
register_tool("update_article", UPDATE_ARTICLE, handle_update_article)
register_tool("delete_article", DELETE_ARTICLE, handle_delete_article)
register_tool("import_anatomy_yaml", IMPORT_ANATOMY_YAML, handle_import_anatomy_yaml)
register_tool("generate_intelligence_report", GENERATE_INTELLIGENCE_REPORT, handle_generate_intelligence_report)
register_tool("list_entities", LIST_ENTITIES, handle_list_entities)
