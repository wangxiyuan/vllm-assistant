"""
SQLite数据库管理模块
仅负责 engine、Session、Base、get_db 工厂。
模型定义在 app/models.py（DESIGN.md 312 行要求拆分）。
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import Config
from app.models import Base

os.makedirs(Config.DB_PATH.parent, exist_ok=True)

engine = create_engine(f"sqlite:///{Config.DB_PATH}", echo=False)

# 启用外键约束 + WAL 模式（读写并发不互锁）
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)

# 补建索引（SQLite 不支持 ALTER TABLE ADD INDEX，且 create_all 不修改已有表）
def _ensure_indexes():
    """确保所有定义在 __table_args__ 中的索引已创建"""
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        existing = {idx["name"] for idx in inspect(conn).get_indexes("items")}
        existing |= {idx["name"] for idx in inspect(conn).get_indexes("my_prs")}
        existing |= {idx["name"] for idx in inspect(conn).get_indexes("user_issues")}
        existing |= {idx["name"] for idx in inspect(conn).get_indexes("ai_cache")}
        existing |= {idx["name"] for idx in inspect(conn).get_indexes("intelligence_reports")}

        # 定义需要创建的新索引
        new_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_items_type_state ON items(type, state)",
            "CREATE INDEX IF NOT EXISTS idx_items_area ON items(area)",
            "CREATE INDEX IF NOT EXISTS idx_items_updated_at ON items(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_my_prs_state ON my_prs(state)",
            "CREATE INDEX IF NOT EXISTS idx_my_prs_created_at ON my_prs(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_user_issues_state ON user_issues(state)",
            "CREATE INDEX IF NOT EXISTS idx_ai_cache_created_at ON ai_cache(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_intel_reports_created_at ON intelligence_reports(created_at)",
        ]

        for ddl in new_indexes:
            idx_name = ddl.split()[5]
            if idx_name not in existing:
                conn.execute(DDL(ddl))
                conn.commit()

_ensure_indexes()


def get_db():
    """获取数据库会话（FastAPI 依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
