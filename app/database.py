"""
SQLite数据库管理模块
仅负责 engine、Session、Base、get_db 工厂。
模型定义在 app/models.py（DESIGN.md 312 行要求拆分）。
"""
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.config import Config
from app.models import Base

logger = logging.getLogger(__name__)

os.makedirs(Config.DB_PATH.parent, exist_ok=True)

engine = create_engine(f"sqlite:///{Config.DB_PATH}", echo=False)

# 启用外键约束 + WAL 模式（读写并发不互锁）
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    # 并发 writer 竞争写锁时，等待最多 30s 而非立即抛 "database is locked"
    cursor.execute("PRAGMA busy_timeout=30000")
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

        # 先获取每张表的列名，用于跳过列不存在的索引
        table_columns = {}
        for table in ("items", "my_prs", "user_issues", "ai_cache",
                      "intelligence_reports", "file_change_history",
                      "ai_memory", "ai_chat_messages"):
            try:
                cols = {c["name"] for c in inspect(conn).get_columns(table)}
                table_columns[table] = cols
            except Exception:
                table_columns[table] = set()

        # 索引定义：（表名, SQL）
        index_definitions = [
            ("items", "CREATE INDEX IF NOT EXISTS idx_items_type_state ON items(type, state)"),
            ("items", "CREATE INDEX IF NOT EXISTS idx_items_area ON items(area)"),
            ("items", "CREATE INDEX IF NOT EXISTS idx_items_updated_at ON items(updated_at)"),
            ("items", "CREATE INDEX IF NOT EXISTS idx_items_repo ON items(repo)"),
            ("my_prs", "CREATE INDEX IF NOT EXISTS idx_my_prs_state ON my_prs(state)"),
            ("my_prs", "CREATE INDEX IF NOT EXISTS idx_my_prs_created_at ON my_prs(created_at)"),
            ("my_prs", "CREATE INDEX IF NOT EXISTS idx_my_prs_github_id ON my_prs(github_id)"),
            ("user_issues", "CREATE INDEX IF NOT EXISTS idx_user_issues_state ON user_issues(state)"),
            ("user_issues", "CREATE INDEX IF NOT EXISTS idx_user_issues_github_id ON user_issues(github_id)"),
            ("ai_cache", "CREATE INDEX IF NOT EXISTS idx_ai_cache_created_at ON ai_cache(created_at)"),
            ("intelligence_reports", "CREATE INDEX IF NOT EXISTS idx_intel_reports_created_at ON intelligence_reports(created_at)"),
            ("file_change_history", "CREATE INDEX IF NOT EXISTS idx_fch_repo_file ON file_change_history(repo, file_path)"),
            ("file_change_history", "CREATE INDEX IF NOT EXISTS idx_fch_pr_number ON file_change_history(pr_number)"),
            ("ai_memory", "CREATE INDEX IF NOT EXISTS idx_ai_memory_source_type ON ai_memory(source_type)"),
            ("ai_memory", "CREATE INDEX IF NOT EXISTS idx_ai_memory_source_ref ON ai_memory(source_ref)"),
            ("ai_memory", "CREATE INDEX IF NOT EXISTS idx_ai_memory_updated_at ON ai_memory(updated_at)"),
            ("ai_memory", "CREATE INDEX IF NOT EXISTS idx_ai_memory_is_stale ON ai_memory(is_stale)"),
            ("ai_chat_messages", "CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session_id ON ai_chat_messages(session_id)"),
            ("ai_chat_messages", "CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_created_at ON ai_chat_messages(created_at)"),
        ]

        for table_name, ddl in index_definitions:
            idx_name = ddl.split()[5]
            if idx_name not in existing:
                # 提取索引涉及的列名（括号内的部分）
                cols_part = ddl.split("ON")[1].split("(")[1].split(")")[0].split(",")
                cols_part = [c.strip() for c in cols_part]
                # 检查所有列是否都存在，不存在的列跳过该索引
                available = table_columns.get(table_name, set())
                missing = [c for c in cols_part if c not in available]
                if missing:
                    logger.warning(
                        f"Skipping index {idx_name} on {table_name}: "
                        f"column(s) {missing} not found in table. "
                        f"This may happen when the DB schema is outdated."
                    )
                    continue
                try:
                    conn.execute(DDL(ddl))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Failed to create index {idx_name}: {e}")

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


def _ensure_repo_caches_schema():
    """确保 repo_caches 表包含 status, created_at, updated_at, tracked 列（向后兼容迁移）"""
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            existing_cols = {c["name"] for c in inspect(conn).get_columns("repo_caches")}
        except Exception:
            # 表可能还不存在，create_all 会处理
            return

        migrations = {
            "status": "ALTER TABLE repo_caches ADD COLUMN status VARCHAR(20) DEFAULT 'active'",
            "created_at": "ALTER TABLE repo_caches ADD COLUMN created_at TIMESTAMP",
            "updated_at": "ALTER TABLE repo_caches ADD COLUMN updated_at TIMESTAMP",
            "tracked": "ALTER TABLE repo_caches ADD COLUMN tracked BOOLEAN NOT NULL DEFAULT 0",
        }

        for col_name, ddl in migrations.items():
            if col_name not in existing_cols:
                try:
                    conn.execute(DDL(ddl))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Failed to add column {col_name} to repo_caches: {e}")

        # 为已有记录设置默认值（status 和 created_at）
        cols_after = {c["name"] for c in inspect(conn).get_columns("repo_caches")}
        if "status" in cols_after:
            conn.execute(text("UPDATE repo_caches SET status = 'active' WHERE status IS NULL"))
            conn.commit()


def _ensure_items_repo_column():
    """给 items 表加 repo 列并重建唯一约束。

    SQLite 不支持 DROP CONSTRAINT，需重建表。
    现有数据 repo 回填为 Config 默认仓库。

    安全性：整个重建在一个事务中执行，中途失败会回滚，不会丢数据。
    """
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            cols = {c["name"] for c in inspect(conn).get_columns("items")}
        except Exception:
            return  # 表不存在，create_all 处理

        if "repo" in cols:
            return  # 已有列，跳过

        # 清理可能残留的旧迁移临时表（上次迁移中途失败留下）
        try:
            conn.execute(DDL("DROP TABLE IF EXISTS items_new"))
            conn.commit()
        except Exception:
            pass

        default_repo = "vllm-project/vllm"
        try:
            conn.execute(DDL("""
                CREATE TABLE items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo VARCHAR(100) NOT NULL DEFAULT 'vllm-project/vllm',
                    type VARCHAR(10) NOT NULL,
                    number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT,
                    state VARCHAR(20) NOT NULL,
                    labels TEXT,
                    area VARCHAR(50),
                    author VARCHAR(100),
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    comments INTEGER DEFAULT 0,
                    url VARCHAR(500),
                    base_sha VARCHAR(40),
                    head_sha VARCHAR(40),
                    additions INTEGER DEFAULT 0,
                    deletions INTEGER DEFAULT 0,
                    changed_files INTEGER DEFAULT 0,
                    last_sync TIMESTAMP,
                    UNIQUE(repo, type, number)
                )
            """))
            conn.execute(DDL(f"""
                INSERT INTO items_new SELECT
                    id, '{default_repo}' AS repo, type, number, title, body,
                    state, labels, area, author, created_at, updated_at,
                    comments, url, base_sha, head_sha, additions, deletions,
                    changed_files, last_sync
                FROM items
            """))
            conn.execute(DDL("DROP TABLE items"))
            conn.execute(DDL("ALTER TABLE items_new RENAME TO items"))
            conn.commit()
            logger.info("items 表已迁移：新增 repo 列，重建唯一约束")
        except Exception as e:
            conn.rollback()
            # 清理临时表
            try:
                conn.execute(DDL("DROP TABLE IF EXISTS items_new"))
                conn.commit()
            except Exception:
                pass
            logger.exception(f"items 表迁移失败，已回滚: {e}")
            raise


def _ensure_watchlist_repo_column():
    """给 watchlist 表加 repo 列并重建唯一约束。

    安全性：整个重建在一个事务中执行，中途失败会回滚。
    """
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            cols = {c["name"] for c in inspect(conn).get_columns("watchlist")}
        except Exception:
            return

        if "repo" in cols:
            return

        try:
            conn.execute(DDL("DROP TABLE IF EXISTS watchlist_new"))
            conn.commit()
        except Exception:
            pass

        default_repo = "vllm-project/vllm"
        try:
            conn.execute(DDL("""
                CREATE TABLE watchlist_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo VARCHAR(100) DEFAULT 'vllm-project/vllm',
                    number INTEGER NOT NULL,
                    item_type VARCHAR(10) NOT NULL,
                    title TEXT,
                    url VARCHAR(500),
                    area VARCHAR(50),
                    issue_type VARCHAR(30),
                    state VARCHAR(20),
                    note TEXT,
                    assignee_id INTEGER REFERENCES users(id),
                    added_at TIMESTAMP,
                    UNIQUE(repo, number, item_type)
                )
            """))
            conn.execute(DDL(f"""
                INSERT INTO watchlist_new SELECT
                    id, '{default_repo}' AS repo, number, item_type, title, url,
                    area, issue_type, state, note, assignee_id, added_at
                FROM watchlist
            """))
            conn.execute(DDL("DROP TABLE watchlist"))
            conn.execute(DDL("ALTER TABLE watchlist_new RENAME TO watchlist"))
            conn.commit()
            logger.info("watchlist 表已迁移：新增 repo 列，重建唯一约束")
        except Exception as e:
            conn.rollback()
            try:
                conn.execute(DDL("DROP TABLE IF EXISTS watchlist_new"))
                conn.commit()
            except Exception:
                pass
            logger.exception(f"watchlist 表迁移失败，已回滚: {e}")
            raise


def _ensure_my_prs_repo_column():
    """给 my_prs 表加 repo 列并重建主键约束。

    安全性：整个重建在一个事务中执行，中途失败会回滚。
    """
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            cols = {c["name"] for c in inspect(conn).get_columns("my_prs")}
        except Exception:
            return

        if "repo" in cols:
            return

        try:
            conn.execute(DDL("DROP TABLE IF EXISTS my_prs_new"))
            conn.commit()
        except Exception:
            pass

        default_repo = "vllm-project/vllm"
        try:
            conn.execute(DDL("""
                CREATE TABLE my_prs_new (
                    repo VARCHAR(100) NOT NULL DEFAULT 'vllm-project/vllm',
                    pr_number INTEGER NOT NULL,
                    github_id VARCHAR(100) DEFAULT '',
                    title TEXT,
                    state VARCHAR(20),
                    branch VARCHAR(200),
                    base_sha VARCHAR(40),
                    head_sha VARCHAR(40),
                    ci_status VARCHAR(20),
                    conflict_detected BOOLEAN DEFAULT 0,
                    conflict_commits INTEGER DEFAULT 0,
                    additions INTEGER DEFAULT 0,
                    deletions INTEGER DEFAULT 0,
                    changed_files INTEGER DEFAULT 0,
                    created_at TIMESTAMP,
                    last_sync TIMESTAMP,
                    PRIMARY KEY(repo, pr_number, github_id)
                )
            """))
            conn.execute(DDL(f"""
                INSERT INTO my_prs_new SELECT
                    '{default_repo}' AS repo, pr_number, github_id, title, state,
                    branch, base_sha, head_sha, ci_status, conflict_detected,
                    conflict_commits, additions, deletions, changed_files,
                    created_at, last_sync
                FROM my_prs
            """))
            conn.execute(DDL("DROP TABLE my_prs"))
            conn.execute(DDL("ALTER TABLE my_prs_new RENAME TO my_prs"))
            conn.commit()
            logger.info("my_prs 表已迁移：新增 repo 列，重建主键约束")
        except Exception as e:
            conn.rollback()
            try:
                conn.execute(DDL("DROP TABLE IF EXISTS my_prs_new"))
                conn.commit()
            except Exception:
                pass
            logger.exception(f"my_prs 表迁移失败，已回滚: {e}")
            raise


def _ensure_slack_configs_schema():
    """确保 slack_configs 表包含必要列（向后兼容迁移）"""
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            existing_cols = {c["name"] for c in inspect(conn).get_columns("slack_configs")}
        except Exception:
            return

        migrations = {
            "token": "ALTER TABLE slack_configs ADD COLUMN token TEXT DEFAULT ''",
            "cookie": "ALTER TABLE slack_configs ADD COLUMN cookie TEXT DEFAULT ''",
            "collect_lookback": "ALTER TABLE slack_configs ADD COLUMN collect_lookback INTEGER DEFAULT 1440",
            "last_refresh_at": "ALTER TABLE slack_configs ADD COLUMN last_refresh_at DATETIME",
        }

        for col_name, ddl in migrations.items():
            if col_name not in existing_cols:
                try:
                    conn.execute(DDL(ddl))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Failed to add column {col_name} to slack_configs: {e}")


def _ensure_anatomy_schema():
    """确保模型拆解表（building_block / model_assembly）包含 config 列（向后兼容迁移）

    config 列是新版本为了在 YAML 中携带用户提供的模型 config、并解析 `${config.x}`
    表达式而新增的。老库若已存在这两张表，会被 create_all 跳过（不改已有表），
    导致写入时报 “no column named config”，故此处幂等补列。
    """
    from sqlalchemy import inspect, DDL

    # 各表需要补的列：{列名: DDL}
    add_cols = {
        "building_block": {
            "config": "ALTER TABLE building_block ADD COLUMN config TEXT",
            "formula": "ALTER TABLE building_block ADD COLUMN formula TEXT",
        },
        "model_assembly": {
            "config": "ALTER TABLE model_assembly ADD COLUMN config TEXT",
        },
    }
    with engine.connect() as conn:
        for table, cols in add_cols.items():
            try:
                existing_cols = {c["name"] for c in inspect(conn).get_columns(table)}
            except Exception:
                continue  # 表不存在，create_all 会处理
            for col_name, ddl in cols.items():
                if col_name in existing_cols:
                    continue
                try:
                    conn.execute(DDL(ddl))
                    conn.commit()
                    logger.info(f"已为 {table} 添加 {col_name} 列")
                except Exception as e:
                    logger.warning(f"Failed to add {col_name} column to {table}: {e}")


def _ensure_intelligence_reports_category():
    """确保 intelligence_reports 表包含 category 列（向后兼容迁移）"""
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            existing_cols = {c["name"] for c in inspect(conn).get_columns("intelligence_reports")}
        except Exception:
            return

        if "category" not in existing_cols:
            try:
                conn.execute(DDL("ALTER TABLE intelligence_reports ADD COLUMN category VARCHAR(50) DEFAULT 'manual'"))
                conn.commit()
                logger.info("Added category column to intelligence_reports table")
            except Exception as e:
                logger.warning(f"Failed to add category column to intelligence_reports: {e}")


def _ensure_intelligence_report_traces():
    """确保 intelligence_report_traces 表存在（向后兼容，CREATE IF NOT EXISTS 幂等）。"""
    conn_key = "intelligence_report_traces"
    if conn_key not in Base.metadata.tables:
        logger.warning(f"{conn_key} table not defined in metadata, skipping creation")
        return
    table = Base.metadata.tables[conn_key]
    with engine.begin() as conn:
        table.create(bind=conn, checkfirst=True)
        logger.info("Ensured intelligence_report_traces table exists")


def _ensure_ai_chat_messages_proc_columns():
    """确保 ai_chat_messages 表包含 steps / usage / duration_s 列（向后兼容迁移）"""
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            existing_cols = {c["name"] for c in inspect(conn).get_columns("ai_chat_messages")}
        except Exception:
            return  # 表不存在，create_all 会处理

        migrations = {
            "steps": "ALTER TABLE ai_chat_messages ADD COLUMN steps TEXT",
            "usage": "ALTER TABLE ai_chat_messages ADD COLUMN usage TEXT",
            "duration_s": "ALTER TABLE ai_chat_messages ADD COLUMN duration_s FLOAT",
        }

        for col_name, ddl in migrations.items():
            if col_name not in existing_cols:
                try:
                    conn.execute(DDL(ddl))
                    conn.commit()
                    logger.info(f"Added column {col_name} to ai_chat_messages")
                except Exception as e:
                    logger.warning(f"Failed to add column {col_name} to ai_chat_messages: {e}")


def _ensure_watchlist_state_change_column():
    """确保 watchlist 表包含 last_state_change_at 列（向后兼容迁移）"""
    from sqlalchemy import inspect, DDL

    with engine.connect() as conn:
        try:
            existing_cols = {c["name"] for c in inspect(conn).get_columns("watchlist")}
        except Exception:
            return

        if "last_state_change_at" not in existing_cols:
            try:
                conn.execute(DDL("ALTER TABLE watchlist ADD COLUMN last_state_change_at TIMESTAMP"))
                conn.commit()
                logger.info("Added last_state_change_at column to watchlist table")
            except Exception as e:
                logger.warning(f"Failed to add last_state_change_at column to watchlist: {e}")


def _cleanup_obsolete_schema():
    """清理已废弃的表和字段（dedup_check_result, task_dedup_cache）"""
    from sqlalchemy import inspect, DDL, text

    with engine.connect() as conn:
        # 1. 删除废弃的 task_dedup_cache 表
        try:
            conn.execute(DDL("DROP TABLE IF EXISTS task_dedup_cache"))
            conn.commit()
            logger.info("Dropped obsolete table: task_dedup_cache")
        except Exception as e:
            logger.warning(f"Failed to drop task_dedup_cache: {e}")

        # 2. 删除 personal_tasks.dedup_check_result 列
        try:
            cols = {c["name"] for c in inspect(conn).get_columns("personal_tasks")}
            if "dedup_check_result" in cols:
                # 清理可能残留的旧迁移临时表（上次迁移中途失败留下）
                try:
                    conn.execute(DDL("DROP TABLE IF EXISTS personal_tasks_new"))
                    conn.commit()
                except Exception:
                    pass
                # SQLite 不支持 DROP COLUMN，用重建方式
                # 临时禁用外键检查以允许 DROP TABLE personal_tasks
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                conn.execute(DDL("""
                    CREATE TABLE personal_tasks_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        description TEXT,
                        source VARCHAR(50) NOT NULL,
                        priority VARCHAR(10) NOT NULL DEFAULT 'P2',
                        status VARCHAR(20) NOT NULL DEFAULT 'todo',
                        related_refs JSON DEFAULT '[]',
                        area VARCHAR(50),
                        tags TEXT,
                        assignee_id INTEGER REFERENCES users(id),
                        parent_id INTEGER REFERENCES personal_tasks(id),
                        subtask_order INTEGER DEFAULT 0,
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        due_date DATE,
                        completed_at TIMESTAMP
                    )
                """))
                conn.execute(DDL("""
                    INSERT INTO personal_tasks_new SELECT
                        id, title, description, source, priority, status,
                        related_refs, area, tags, assignee_id, parent_id,
                        subtask_order, created_at, updated_at, due_date, completed_at
                    FROM personal_tasks
                """))
                conn.execute(DDL("DROP TABLE personal_tasks"))
                conn.execute(DDL("ALTER TABLE personal_tasks_new RENAME TO personal_tasks"))
                conn.commit()
                logger.info("Dropped obsolete column: personal_tasks.dedup_check_result")
        except Exception as e:
            logger.warning(f"Failed to drop dedup_check_result column: {e}")


_ensure_indexes()
_ensure_fts_triggers()
_ensure_repo_caches_schema()
_ensure_items_repo_column()
_ensure_watchlist_repo_column()
_ensure_my_prs_repo_column()
_ensure_slack_configs_schema()
_ensure_anatomy_schema()
_ensure_intelligence_reports_category()
_ensure_intelligence_report_traces()
_ensure_ai_chat_messages_proc_columns()
_ensure_watchlist_state_change_column()
_cleanup_obsolete_schema()
# 重建表会丢失索引，迁移后重新补建
_ensure_indexes()


def get_db():
    """获取数据库会话（FastAPI 依赖注入用）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
