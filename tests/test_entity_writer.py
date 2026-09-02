"""
entity_writer 与写类工具的单元测试

不依赖真实数据库：用内存 SQLite 建 Base.metadata，直接测 service 函数；
工具 handler 通过 monkeypatch app.database.SessionLocal 注入内存会话工厂。
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base  # noqa: E402
from app.models import AIRule  # noqa: E402
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

    entity_writer.create_rule(db_session, {"name": "检索我", "prompt": "p"})
    out = asyncio.run(write_tools.handle_list_entities({"entity_type": "rule", "query": "检索"}))
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
