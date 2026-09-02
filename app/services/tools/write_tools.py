"""
写类工具（write category）

让 AI agent 可以创建/更新/删除本项目的实体：筛选规则、模型拆解（YAML 导入）、洞察报告。
业务逻辑全部委托给 app/services/entity_writer.py 与 app/api/model_anatomy.py:run_yaml_import，
本模块只做参数适配与会话管理。

安全约定：
- delete_* 工具在 confirm != true 时只返回待删对象详情，不执行删除；
  system prompt 要求 AI 先向用户复述并征得明确同意后才允许 confirm=true。
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
                "title": {"type": "string", "description": "报告主题/标题"},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "情报来源列表（仓库名/academic/news）。空 = 全部可用来源"},
                "extra_prompt": {"type": "string", "description": "额外关注点/要求"},
            },
            "required": ["title"],
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
        "description": "列出规则/报告的 id 与摘要，用于更新或删除前定位目标。支持关键词过滤。",
        "parameters": {
            "type": "object",
            "properties": {
                "entity_type": {"type": "string", "enum": ["rule", "report"]},
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
            return {"error": "entity_type 必须是 rule/report"}
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
register_tool("import_anatomy_yaml", IMPORT_ANATOMY_YAML, handle_import_anatomy_yaml)
register_tool("generate_intelligence_report", GENERATE_INTELLIGENCE_REPORT, handle_generate_intelligence_report)
register_tool("list_entities", LIST_ENTITIES, handle_list_entities)
