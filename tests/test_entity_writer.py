"""
entity_writer 与写类工具的单元测试

不依赖真实数据库：用内存 SQLite 建 Base.metadata，直接测 service 函数；
工具 handler 通过 monkeypatch app.database.SessionLocal 注入内存会话工厂。
"""
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    AIRule,
    Article,
    PersonalTask,
)
import app.database as database_module  # noqa: E402
from app.services import entity_writer  # noqa: E402


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    # 工具 handler 内部 from app.database import SessionLocal → 指向测试工厂
    orig = database_module.SessionLocal
    database_module.SessionLocal = TestingSession
    yield session
    database_module.SessionLocal = orig
    session.close()
    engine.dispose()


# ======================================================================
# 规则
# ======================================================================


def test_create_and_update_rule(db_session):
    rule = entity_writer.create_rule(db_session, {
        "name": "KV Cache",
        "prompt": "涉及 KV Cache 性能优化的 PR",
        "item_type": "pr",
        "repos": ["vllm-project/vllm"],
        "enabled": True,
    })
    assert rule["id"] > 0 and rule["name"] == "KV Cache"

    updated = entity_writer.update_rule(db_session, rule["id"], {"prompt": "新的筛选要求"})
    assert updated["prompt"] == "新的筛选要求"

    rows = db_session.query(AIRule).all()
    assert len(rows) == 1 and rows[0].prompt == "新的筛选要求"


def test_create_rule_validation(db_session):
    import fastapi

    with pytest.raises(fastapi.HTTPException):
        entity_writer.create_rule(db_session, {"name": "  ", "prompt": "x"})
    with pytest.raises(fastapi.HTTPException):
        entity_writer.create_rule(db_session, {"name": "a", "prompt": "x", "item_type": "bad"})


def test_delete_rule_cascades_matches(db_session):
    from app.models import AIRuleMatch

    rule = entity_writer.create_rule(db_session, {"name": "r", "prompt": "p"})
    db_session.add(AIRuleMatch(
        rule_id=rule["id"], repo="vllm-project/vllm", item_type="pr",
        number=1, reason="test",
    ))
    db_session.commit()

    result = entity_writer.delete_rule(db_session, rule["id"])
    assert result["deleted"] == rule["id"]
    assert db_session.query(AIRuleMatch).count() == 0


# ======================================================================
# 任务
# ======================================================================


def test_create_task_defaults_and_due_date(db_session):
    task = entity_writer.create_task(db_session, {
        "title": "调研 MLA",
        "due_date": "2026-09-01",
        "tags": ["vllm"],
        "source": "ai",
    })
    assert task["title"] == "调研 MLA"
    assert task["status"] == "todo"
    stored = db_session.query(PersonalTask).first()
    assert stored.tags == json.dumps(["vllm"], ensure_ascii=False)
    assert stored.due_date is not None and stored.due_date.isoformat() == "2026-09-01"


def test_create_task_empty_title_rejected(db_session):
    import fastapi

    with pytest.raises(fastapi.HTTPException):
        entity_writer.create_task(db_session, {"title": ""})


def test_update_task_status_sets_completed_at(db_session):
    task = entity_writer.create_task(db_session, {"title": "t"})
    assert task["completed_at"] is None
    updated = entity_writer.update_task(db_session, task["id"], {"status": "done"})
    assert updated["status"] == "done" and updated["completed_at"]
    back = entity_writer.update_task(db_session, task["id"], {"status": "todo"})
    assert back["completed_at"] is None


def test_delete_task_cascades(db_session):
    from app.models import IntelligenceReport

    parent = entity_writer.create_task(db_session, {"title": "父"})
    child = entity_writer.create_task(db_session, {"title": "子", "parent_id": parent["id"]})
    db_session.add(IntelligenceReport(
        title="r", content="", task_id=parent["id"], sources="[]",
        created_at=entity_writer._utcnow(), status="completed",
    ))
    db_session.commit()

    entity_writer.delete_task(db_session, parent["id"])
    assert db_session.query(PersonalTask).filter(PersonalTask.id == child["id"]).count() == 0
    assert db_session.query(IntelligenceReport).filter_by(task_id=parent["id"]).count() == 0


# ======================================================================
# 文章
# ======================================================================


def test_create_article_draft_default_and_refs(db_session):
    result = entity_writer.create_article(db_session, {
        "title": "学习笔记",
        "content": "# 笔记\n\n没有代码引用的内容。",
    })
    assert result["status"] == "draft" and result["refs_count"] == 0
    stored = db_session.query(Article).filter_by(id=result["id"]).first()
    assert stored is not None and stored.status == "draft"


def test_article_validation(db_session):
    import fastapi

    with pytest.raises(fastapi.HTTPException):
        entity_writer.create_article(db_session, {"title": "t", "content": "   "})


def test_update_article_rewrites_refs(db_session):
    created = entity_writer.create_article(db_session, {"title": "a", "content": "v1"})
    updated = entity_writer.update_article(db_session, created["id"], {"content": "v2\n"})
    assert updated["content"] == "v2\n"


def test_delete_article(db_session):
    created = entity_writer.create_article(db_session, {"title": "a", "content": "x"})
    result = entity_writer.delete_article(db_session, created["id"])
    assert result["deleted"] is True
    assert db_session.query(Article).count() == 0


# ======================================================================
# 工具层（write_tools）
# ======================================================================


def test_tool_create_and_delete_rule_guard(db_session):
    from app.services.tools import write_tools
    import asyncio

    created = asyncio.run(write_tools.handle_create_rule({
        "name": "MoE 路由",
        "prompt": "MoE 路由相关",
        "watch_pr": True, "watch_issue": False, "watch_commit": False,
    }))
    assert "error" not in created
    assert created["entity"] == "rule"

    rule = db_session.query(AIRule).filter_by(name="MoE 路由").first()
    assert rule.item_type == "pr" and rule.include_commits is False

    # 未确认 → 只返回详情，不删除
    guard = asyncio.run(write_tools.handle_delete_rule({"rule_id": rule.id}))
    assert guard["status"] == "needs_confirmation"
    assert db_session.query(AIRule).filter_by(id=rule.id).count() == 1

    # 确认后删除
    deleted = asyncio.run(write_tools.handle_delete_rule({"rule_id": rule.id, "confirm": True}))
    assert "error" not in deleted
    assert db_session.query(AIRule).filter_by(id=rule.id).count() == 0


def test_tool_derive_item_types(db_session):
    # 与前端 deriveItemTypes 一致：PR/Issue 都不选 = 仅 Commit 规则
    assert write_tools_derive({"watch_pr": True, "watch_issue": True}) == {
        "item_type": "both", "include_commits": False}
    assert write_tools_derive({}) == {"item_type": "commit", "include_commits": True}
    assert write_tools_derive({"watch_commit": True}) == {"item_type": "commit", "include_commits": True}


def write_tools_derive(args):
    from app.services.tools.write_tools import _derive_item_types
    return _derive_item_types(args)


def test_tool_list_entities(db_session):
    import asyncio
    from app.services.tools import write_tools

    entity_writer.create_task(db_session, {"title": "检索我"})
    out = asyncio.run(write_tools.handle_list_entities({"entity_type": "task", "query": "检索"}))
    assert out["total"] == 1 and out["items"][0]["title"] == "检索我"

    bad = asyncio.run(write_tools.handle_list_entities({"entity_type": "nope"}))
    assert "error" in bad


# ======================================================================
# 模型拆解 YAML 导入
# ======================================================================


MINIMAL_YAML = """
- kind: atomic
  name: TestRMSNorm
  category: normalization
  description: 测试用 RMSNorm。
  ports:
    inputs:
      - { id: x, type: tensor, shape: "[B, H]" }
    outputs:
      - { id: y, type: tensor, shape: "[B, H]" }
"""


def test_run_yaml_import_idempotent(db_session):
    from app.api.model_anatomy import run_yaml_import

    first = run_yaml_import(db_session, MINIMAL_YAML)
    assert first.imported_blocks == 1 and not first.errors

    second = run_yaml_import(db_session, MINIMAL_YAML)
    assert second.imported_blocks == 0 and second.skipped == 1


def test_run_yaml_import_bad_yaml(db_session):
    from app.api.model_anatomy import run_yaml_import

    result = run_yaml_import(db_session, "- kind: atomic\n  name: [unclosed")
    assert result.errors
