"""
SQLite数据库管理模块
仅负责 engine、Session、Base、get_db 工厂。
模型定义在 app/models.py（DESIGN.md 312 行要求拆分）。
"""
import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
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
        existing |= {idx["name"] for idx in inspect(conn).get_indexes("file_change_history")}
        existing |= {idx["name"] for idx in inspect(conn).get_indexes("ai_memory")}
        existing |= {idx["name"] for idx in inspect(conn).get_indexes("ai_chat_messages")}

        new_indexes = [
            "CREATE INDEX IF NOT EXISTS idx_items_type_state ON items(type, state)",
            "CREATE INDEX IF NOT EXISTS idx_items_area ON items(area)",
            "CREATE INDEX IF NOT EXISTS idx_items_updated_at ON items(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_my_prs_state ON my_prs(state)",
            "CREATE INDEX IF NOT EXISTS idx_my_prs_created_at ON my_prs(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_my_prs_github_id ON my_prs(github_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_issues_state ON user_issues(state)",
            "CREATE INDEX IF NOT EXISTS idx_user_issues_github_id ON user_issues(github_id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_cache_created_at ON ai_cache(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_intel_reports_created_at ON intelligence_reports(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_fch_repo_file ON file_change_history(repo, file_path)",
            "CREATE INDEX IF NOT EXISTS idx_fch_pr_number ON file_change_history(pr_number)",
            "CREATE INDEX IF NOT EXISTS idx_ai_memory_source_type ON ai_memory(source_type)",
            "CREATE INDEX IF NOT EXISTS idx_ai_memory_source_ref ON ai_memory(source_ref)",
            "CREATE INDEX IF NOT EXISTS idx_ai_memory_updated_at ON ai_memory(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_ai_memory_is_stale ON ai_memory(is_stale)",
            "CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session_id ON ai_chat_messages(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_created_at ON ai_chat_messages(created_at)",
        ]

        for ddl in new_indexes:
            idx_name = ddl.split()[5]
            if idx_name not in existing:
                conn.execute(DDL(ddl))
                conn.commit()

        # 创建 FTS5 虚拟表（用于全文检索）
        # unicode61 是 FTS5 内置 tokenizer，支持中文和数字
        conn.execute(DDL("""
            CREATE VIRTUAL TABLE IF NOT EXISTS ai_memory_fts USING fts5(
                content,
                content_rowid='rowid',
                tokenize='unicode61'
            )
        """))

        # 填充已有数据到 FTS5 索引（如果 FTS5 表为空且有数据）
        existing_count = conn.execute(
            text("SELECT COUNT(*) FROM ai_memory")
        ).scalar()
        if existing_count and existing_count > 0:
            fts_count = conn.execute(
                text("SELECT COUNT(*) FROM ai_memory_fts")
            ).scalar()
            if fts_count == 0:
                logger.info(f"Rebuilding FTS5 index for {existing_count} existing records...")
                conn.execute(DDL("DELETE FROM ai_memory_fts"))
                conn.execute(DDL("""
                    INSERT INTO ai_memory_fts(rowid, content)
                    SELECT id, content FROM ai_memory WHERE content IS NOT NULL AND content != ''
                """))
                logger.info("FTS5 index rebuild complete")


def _ensure_fts_triggers():
    """确保 ai_memory 表有 FTS5 同步触发器"""
    from sqlalchemy import DDL

    triggers = [
        """
        CREATE TRIGGER IF NOT EXISTS ai_memory_ai AFTER INSERT ON ai_memory BEGIN
            INSERT INTO ai_memory_fts(rowid, content) VALUES (new.id, new.content);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS ai_memory_ad AFTER DELETE ON ai_memory BEGIN
            DELETE FROM ai_memory_fts WHERE rowid = old.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS ai_memory_au AFTER UPDATE ON ai_memory BEGIN
            DELETE FROM ai_memory_fts WHERE rowid = old.id;
            INSERT INTO ai_memory_fts(rowid, content) VALUES (new.id, new.content);
        END
        """,
    ]
    with engine.connect() as conn:
        for sql in triggers:
            conn.execute(DDL(sql))

_ensure_indexes()
_ensure_fts_triggers()


def get_db():
    """获取数据库会话（FastAPI 依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
