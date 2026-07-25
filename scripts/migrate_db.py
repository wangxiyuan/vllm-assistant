#!/usr/bin/env python3
"""
数据库 Schema 迁移工具

检测 models.py 定义的 schema 与 SQLite 数据库实际 schema 的差异，
如果发现差异则自动执行：备份旧库 → 按新 schema 建库 → 迁移数据 → 清理。

用法:
    python scripts/migrate_db.py              # 检查并执行迁移
    python scripts/migrate_db.py --check       # 仅检查差异，不执行迁移
    python scripts/migrate_db.py --force       # 跳过差异检查，强制重建
    python scripts/migrate_db.py --db-path /path/to/db.db  # 指定数据库路径

原理:
    SQLite 的 ALTER TABLE 能力有限（只支持 ADD COLUMN，不支持改类型/加约束/删列），
    所以当 schema 有结构性变化时，采用"备份→重建→迁移"的策略。
"""

import argparse
import json
import logging
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ── 路径设置 ──────────────────────────────────────────────────────────────────
# 确保能找到 app 包
SCRIPT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("migrate_db")


# ═══════════════════════════════════════════════════════════════════════════════
# 第 1 步：获取代码中定义的 schema
# ═══════════════════════════════════════════════════════════════════════════════

def get_code_schema() -> Dict[str, Dict[str, Any]]:
    """从 models.py 的 SQLAlchemy 模型定义中提取完整的 schema 信息。

    返回:
        {
            "table_name": {
                "columns": {
                    "col_name": {
                        "type": str,         # 如 "VARCHAR(10)"
                        "nullable": bool,
                        "primary_key": bool,
                        "default": Any,       # None / 标量值
                        "is_fk": bool,
                        "fk_target": str,     # "table.column" 或 ""
                    }
                },
                "indexes": {                  # key = index name
                    "idx_name": {
                        "columns": list[str],
                        "unique": bool,
                    }
                },
            }
        }
    """
    # 惰性导入，避免还没设置路径就出错
    from app.models import Base

    schema = {}
    for table_name, table in Base.metadata.tables.items():
        columns = {}
        for col in table.columns:
            col_type = _normalize_type(col.type)
            default_val = _extract_default(col.default)
            fk_target = ""
            if col.foreign_keys:
                fk = next(iter(col.foreign_keys))
                fk_target = f"{fk.column.table.name}.{fk.column.name}"

            columns[col.name] = {
                "type": col_type,
                "nullable": col.nullable,
                "primary_key": col.primary_key,
                "default": default_val,
                "is_fk": bool(col.foreign_keys),
                "fk_target": fk_target,
            }

        indexes = {}
        for idx in table.indexes:
            indexes[idx.name] = {
                "columns": [c.name for c in idx.columns],
                "unique": idx.unique,
            }

        # 收集 unique 约束（不在 index 里的）
        from sqlalchemy import UniqueConstraint
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint) and constraint.name:
                if constraint.name not in indexes:
                    indexes[constraint.name] = {
                        "columns": [c.name for c in constraint.columns],
                        "unique": True,
                    }

        schema[table_name] = {
            "columns": columns,
            "indexes": indexes,
        }

    return schema


def _normalize_type(col_type) -> str:
    """将 SQLAlchemy 类型转成可比较的字符串表示"""
    type_str = str(col_type)
    # 统一 Boolean 为 BOOLEAN
    if "BOOLEAN" in type_str.upper():
        return "BOOLEAN"
    # 统一 VARCHAR(N) 格式
    if type_str.upper().startswith("VARCHAR"):
        return type_str.upper()
    # 统一 DATETIME / DATE
    if type_str.upper() in ("DATETIME", "DATE"):
        return type_str.upper()
    if type_str.upper() == "INTEGER":
        return "INTEGER"
    if type_str.upper() in ("TEXT",):
        return "TEXT"
    return type_str.upper()


def _extract_default(default) -> Any:
    """提取列的默认值（只提取标量默认值）"""
    if default is None:
        return None
    if hasattr(default, "arg"):
        # ColumnDefault / DefaultClause
        return default.arg if not callable(default.arg) else None
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 第 2 步：获取数据库实际 schema
# ═══════════════════════════════════════════════════════════════════════════════

def get_db_schema(db_path: Path) -> Dict[str, Dict[str, Any]]:
    """从 SQLite 文件中读取实际 schema。

    返回: 与 get_code_schema() 相同格式。
    """
    if not db_path.exists():
        return {}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    schema = {}

    # 获取所有表名
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row["name"] for row in cursor.fetchall()
              if row["name"] not in ("sqlite_sequence",)]

    # 预读所有表的约束名，用于解析 sqlite_autoindex_*
    table_constraints = _load_table_constraints(cursor, tables)

    for table_name in tables:
        columns = {}
        cursor.execute(f'PRAGMA table_info("{table_name}")')
        for row in cursor.fetchall():
            col_name = row["name"]
            col_type = row["type"].upper() if row["type"] else "TEXT"
            # 统一类型表示
            if col_type in ("BOOL", "TINYINT") or col_type.startswith("BOOL"):
                col_type = "BOOLEAN"
            elif col_type.startswith("VARCHAR") or col_type == "CHARACTER VARYING":
                col_type = col_type.upper()
            elif col_type in ("TIMESTAMP",):
                col_type = "DATETIME"
            elif col_type == "INT":
                col_type = "INTEGER"

            columns[col_name] = {
                "type": col_type,
                "nullable": not row["notnull"],
                "primary_key": bool(row["pk"]),
                "default": row["dflt_value"],
                "is_fk": False,
                "fk_target": "",
            }

        # 获取外键信息
        cursor.execute(f'PRAGMA foreign_key_list("{table_name}")')
        for row in cursor.fetchall():
            col_name = row["from"]
            if col_name in columns:
                columns[col_name]["is_fk"] = True
                columns[col_name]["fk_target"] = f"{row['table']}.{row['to']}"

        # 获取索引信息
        indexes = {}
        cursor.execute(f'PRAGMA index_list("{table_name}")')
        index_rows = cursor.fetchall()
        for idx_row in index_rows:
            idx_name = idx_row["name"]
            cursor.execute(f'PRAGMA index_info("{idx_name}")')
            idx_cols = [r["name"] for r in cursor.fetchall()]

            # SQLite 自动为 UNIQUE 约束创建的索引（sqlite_autoindex_*），
            # 用代码侧的 unique 约束名来命名，以便比对一致
            if idx_name.startswith("sqlite_autoindex"):
                if table_name in table_constraints:
                    resolved = _resolve_autoindex_name(
                        idx_cols, table_constraints[table_name]
                    )
                    if resolved:
                        idx_name = resolved
                    else:
                        continue  # 无法解析，跳过
                else:
                    continue

            indexes[idx_name] = {
                "columns": idx_cols,
                "unique": bool(idx_row["unique"]),
            }

        schema[table_name] = {
            "columns": columns,
            "indexes": indexes,
        }

    conn.close()
    return schema


def _load_table_constraints(
    cursor: sqlite3.Cursor, tables: List[str]
) -> Dict[str, List[Dict[str, Any]]]:
    """从 sqlite_master 中解析出每张表的约束定义。

    返回 { table_name: [{"name": str, "columns": list[str], "type": str}, ...] }
    """
    constraints: Dict[str, List[Dict[str, Any]]] = {}
    for table_name in tables:
        cursor.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}'"
        )
        row = cursor.fetchone()
        if not row or not row["sql"]:
            continue
        constraints[table_name] = _parse_sql_constraints(row["sql"], table_name)
    return constraints


def _parse_sql_constraints(
    create_sql: str, table_name: str
) -> List[Dict[str, Any]]:
    """从 CREATE TABLE SQL 中解析 UNIQUE 约束的名称和列。"""
    import re

    result: List[Dict[str, Any]] = []
    # 匹配 CONSTRAINT <name> UNIQUE (<col1>, <col2>)
    pattern = re.compile(
        r'CONSTRAINT\s+["`]?(\w+)["`]?\s+UNIQUE\s*\(([^)]+)\)',
        re.IGNORECASE,
    )
    for match in pattern.finditer(create_sql):
        name = match.group(1)
        cols = [c.strip().strip('"`').strip() for c in match.group(2).split(",")]
        result.append({"name": name, "columns": cols, "type": "unique"})

    # 也匹配行内 UNIQUE (<col1>, <col2>) 但不带 CONSTRAINT 关键字的情况
    # 这种情况 SQLite 也会生成 sqlite_autoindex，但没法映射名字，跳过
    return result


def _resolve_autoindex_name(
    idx_cols: List[str],
    table_constraints: List[Dict[str, Any]],
) -> Optional[str]:
    """尝试将 sqlite_autoindex_* 映射到代码侧定义的约束名。"""
    for constraint in table_constraints:
        if constraint["columns"] == idx_cols:
            return constraint["name"]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 第 3 步：比对 schema 差异
# ═══════════════════════════════════════════════════════════════════════════════

def compare_schemas(
    code_schema: Dict[str, Dict[str, Any]],
    db_schema: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """比对代码定义的 schema 和数据库实际 schema，返回差异报告。

    返回:
        {
            "has_diff": bool,
            "new_tables": [...],
            "missing_tables": [...],
            "changed_tables": {
                "table_name": {
                    "new_columns": [...],
                    "missing_columns": [...],
                    "changed_columns": [...],  # 类型/约束变化
                    "new_indexes": {...},
                    "missing_indexes": {...},
                }
            },
        }
    """
    result: Dict[str, Any] = {
        "has_diff": False,
        "new_tables": [],
        "missing_tables": [],
        "changed_tables": {},
    }

    code_tables = set(code_schema.keys())
    db_tables = set(db_schema.keys())

    # 代码有但数据库没有的表（新建）
    result["new_tables"] = sorted(code_tables - db_tables)
    # 数据库有但代码没有的表（可能是遗留表，不动它）
    result["missing_tables"] = sorted(db_tables - code_tables)

    # 共有的表，逐列比对
    common_tables = code_tables & db_tables
    for table_name in sorted(common_tables):
        code_cols = code_schema[table_name]["columns"]
        db_cols = db_schema[table_name]["columns"]
        code_idxs = code_schema[table_name]["indexes"]
        db_idxs = db_schema[table_name]["indexes"]

        changes: Dict[str, Any] = {}
        has_change = False

        # 新增列
        new_cols = [c for c in code_cols if c not in db_cols]
        if new_cols:
            changes["new_columns"] = new_cols
            has_change = True

        # 缺失列（代码中删除了的列）
        missing_cols = [c for c in db_cols if c not in code_cols]
        if missing_cols:
            changes["missing_columns"] = missing_cols
            has_change = True

        # 类型/约束变化的列
        changed_cols = []
        for col_name in code_cols:
            if col_name in db_cols:
                c = code_cols[col_name]
                d = db_cols[col_name]
                diffs = {}
                if c["type"] != d["type"]:
                    diffs["type"] = (d["type"], c["type"])
                if c["nullable"] != d["nullable"]:
                    diffs["nullable"] = (d["nullable"], c["nullable"])
                if c["primary_key"] != d["primary_key"]:
                    diffs["primary_key"] = (d["primary_key"], c["primary_key"])
                if diffs:
                    changed_cols.append({"column": col_name, "diffs": diffs})
        if changed_cols:
            changes["changed_columns"] = changed_cols
            has_change = True

        # 新增索引
        new_idxs = {k: v for k, v in code_idxs.items() if k not in db_idxs}
        if new_idxs:
            changes["new_indexes"] = new_idxs
            has_change = True

        # 缺失索引
        missing_idxs = {k: v for k, v in db_idxs.items() if k not in code_idxs}
        if missing_idxs:
            changes["missing_indexes"] = missing_idxs
            has_change = True

        if has_change:
            result["changed_tables"][table_name] = changes
            result["has_diff"] = True

    if result["new_tables"] or result["changed_tables"]:
        result["has_diff"] = True

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 第 4 步：打印差异报告
# ═══════════════════════════════════════════════════════════════════════════════

def print_diff_report(diff: Dict[str, Any]) -> None:
    """友好地打印差异报告"""
    if not diff["has_diff"]:
        logger.info("✅ 数据库 schema 与代码模型完全一致，无需迁移。")
        return

    logger.info("=" * 60)
    logger.info("📋 Schema 差异报告")
    logger.info("=" * 60)

    if diff["new_tables"]:
        logger.info(f"\n🆕 需要新建的表 ({len(diff['new_tables'])}):")
        for t in diff["new_tables"]:
            logger.info(f"   + {t}")

    if diff["missing_tables"]:
        logger.info(f"\n📦 数据库中有但代码中已删除的表 ({len(diff['missing_tables'])}):")
        for t in diff["missing_tables"]:
            logger.info(f"   - {t}（将保留不动）")

    for table_name, changes in diff["changed_tables"].items():
        logger.info(f"\n📝 表 {table_name} 的变化:")

        if "new_columns" in changes:
            for col in changes["new_columns"]:
                logger.info(f"   + 新增列: {col}")

        if "missing_columns" in changes:
            for col in changes["missing_columns"]:
                logger.info(f"   - 删除列: {col}")

        if "changed_columns" in changes:
            for cc in changes["changed_columns"]:
                col = cc["column"]
                for attr, (old, new) in cc["diffs"].items():
                    logger.info(f"   ~ {col}.{attr}: {old} → {new}")

        if "new_indexes" in changes:
            for idx_name, idx_info in changes["new_indexes"].items():
                uniq = "UNIQUE " if idx_info["unique"] else ""
                logger.info(f"   + {uniq}索引: {idx_name}({', '.join(idx_info['columns'])})")

        if "missing_indexes" in changes:
            for idx_name in changes["missing_indexes"]:
                logger.info(f"   - 索引: {idx_name}（将删除）")

    logger.info("")


# ═══════════════════════════════════════════════════════════════════════════════
# 第 5 步：执行迁移
# ═══════════════════════════════════════════════════════════════════════════════

def migrate(db_path: Path) -> None:
    """执行完整的数据库迁移流程：备份 → 重建 → 迁移数据 → 修复 → 清理。"""
    logger.info("=" * 60)
    logger.info("🚀 开始执行数据库迁移")
    logger.info(f"📁 数据库路径: {db_path}")
    logger.info("=" * 60)

    # 5a. 备份
    backup_path = _backup_db(db_path)

    # 5b. 按新 schema 建库
    logger.info("正在创建新数据库...")
    new_db_path = _create_new_db(db_path)

    # 5c. 迁移数据
    logger.info("正在迁移数据...")
    _migrate_data(backup_path, new_db_path)

    # 5d. 迁移后修复：为新加列填充值、创建 users 记录
    logger.info("正在执行迁移后修复...")
    _post_migrate_fixups(new_db_path)

    # 5e. 替换
    logger.info("正在替换数据库...")
    _replace_db(db_path, new_db_path)

    logger.info(f"\n✅ 迁移完成！")
    logger.info(f"   📦 新数据库: {db_path}")
    logger.info(f"   🗂️  备份文件: {backup_path}")
    logger.info(f"   💡 确认一切正常后，可手动删除备份: rm '{backup_path}'")
    logger.info("")


def _backup_db(db_path: Path) -> Path:
    """备份旧数据库"""
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.parent / f"{db_path.name}.{timestamp}.bak"
    shutil.copy2(db_path, backup_path)
    logger.info(f"✅ 备份完成: {backup_path} ({db_path.stat().st_size / 1024:.1f} KB)")
    return backup_path


def _create_new_db(db_path: Path) -> Path:
    """按照代码中的 models 定义创建全新的数据库文件"""
    # 导入 app 的 engine 和 Base
    # 注意：此时 database.py 中的 engine 可能绑定了旧的数据库，
    # 我们需要创建一个指向临时文件的新 engine
    from sqlalchemy import create_engine
    from app.models import Base

    new_db_path = db_path.parent / f"{db_path.name}.tmp_migrate"
    if new_db_path.exists():
        new_db_path.unlink()

    tmp_engine = create_engine(f"sqlite:///{new_db_path}", echo=False)

    # 创建所有表
    Base.metadata.create_all(bind=tmp_engine)

    # 验证表数量
    from sqlalchemy import inspect as sa_inspect
    inspector = sa_inspect(tmp_engine)
    tables_created = inspector.get_table_names()
    logger.info(f"   新建了 {len(tables_created)} 个表: {', '.join(sorted(tables_created))}")

    tmp_engine.dispose()
    return new_db_path


def _migrate_data(old_db_path: Path, new_db_path: Path) -> None:
    """从旧数据库读取数据，写入新数据库。

    策略：
    - 对每个表，取新旧 schema 的交集列
    - 只迁移交集列的数据
    - 如果表在新库中不存在或列完全没有交集，跳过
    - 迁移后为新加列填充默认值，并清理旧配置产生的脏数据
    """
    old_conn = sqlite3.connect(str(old_db_path))
    old_conn.row_factory = sqlite3.Row
    new_conn = sqlite3.connect(str(new_db_path))
    new_conn.row_factory = sqlite3.Row

    old_cursor = old_conn.cursor()
    new_cursor = new_conn.cursor()

    # 获取新旧数据库的表列表
    old_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    old_tables = {row["name"] for row in old_cursor.fetchall()
                  if row["name"] != "sqlite_sequence"}
    new_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    new_tables = {row["name"] for row in new_cursor.fetchall()
                  if row["name"] != "sqlite_sequence"}

    common_tables = old_tables & new_tables
    migrated_count = 0
    skipped_tables = []

    for table_name in sorted(common_tables):
        # 取列交集
        old_cursor.execute(f'PRAGMA table_info("{table_name}")')
        old_cols = {row["name"] for row in old_cursor.fetchall()}
        new_cursor.execute(f'PRAGMA table_info("{table_name}")')
        new_cols = {row["name"] for row in new_cursor.fetchall()}

        common_cols = old_cols & new_cols
        if not common_cols:
            skipped_tables.append(table_name)
            continue

        # 特殊处理：users.github_id 在新表中是 NOT NULL 且无 DEFAULT，
        # 旧数据可能为 NULL，不能跳过该列（SQLite 会报 NOT NULL）。
        # 迁入时把 NULL 转为空字符串，后续由 _post_migrate_fixups 修复
        if table_name == "users":
            # 把旧数据中的 NULL github_id 转为空字符串，然后照常迁移
            old_cursor.execute(
                'UPDATE users SET github_id = "" WHERE github_id IS NULL'
            )
            old_conn.commit()

        # 检查旧表是否有数据
        old_cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        count = old_cursor.fetchone()[0]
        if count == 0:
            continue

        # 特殊处理 personal_tasks：将旧 related_* 字段转换为新的 related_refs JSON
        if table_name == "personal_tasks" and "related_repo" in old_cols and "related_refs" in new_cols:
            col_list = sorted(common_cols)
            placeholders = ",".join(["?"] * len(col_list))
            col_names = ",".join(f'"{c}"' for c in col_list)

            batch_size = 500
            offset = 0
            repo_map = {"vllm": "vllm-project/vllm", "vllm-ascend": "vllm-project/vllm-ascend"}
            while True:
                old_cursor.execute(
                    f'SELECT {col_names}, related_repo, related_issue_number, related_pr_number, related_url FROM "{table_name}" LIMIT {batch_size} OFFSET {offset}'
                )
                rows = old_cursor.fetchall()
                if not rows:
                    break

                for row in rows:
                    values = [row[c] for c in col_list]
                    # 构造 related_refs
                    repo = row["related_repo"]
                    refs = []
                    if repo:
                        repo_path = repo_map.get(repo, repo)
                        issue_num = row["related_issue_number"]
                        pr_num = row["related_pr_number"]
                        if issue_num:
                            refs.append({
                                "repo": repo,
                                "number": issue_num,
                                "type": "issue",
                                "url": f"https://github.com/{repo_path}/issues/{issue_num}",
                            })
                        if pr_num:
                            refs.append({
                                "repo": repo,
                                "number": pr_num,
                                "type": "pr",
                                "url": f"https://github.com/{repo_path}/pull/{pr_num}",
                            })
                    # 替换 related_refs 占位值
                    related_refs_idx = col_list.index("related_refs") if "related_refs" in col_list else -1
                    if related_refs_idx >= 0:
                        values[related_refs_idx] = json.dumps(refs, ensure_ascii=False) if refs else None
                    new_cursor.execute(
                        f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
                        values,
                    )
                new_conn.commit()
                migrated_count += len(rows)
                offset += batch_size
            logger.info(f"   📊 {table_name}: 迁移了 {count} 行数据（含 related_* 转换）")
            continue

        # 构造 INSERT 语句
        col_list = sorted(common_cols)
        placeholders = ",".join(["?"] * len(col_list))
        col_names = ",".join(f'"{c}"' for c in col_list)

        # 分批读取并写入（避免大表一次性读入内存）
        batch_size = 500
        offset = 0
        while True:
            old_cursor.execute(
                f'SELECT {col_names} FROM "{table_name}" LIMIT {batch_size} OFFSET {offset}'
            )
            rows = old_cursor.fetchall()
            if not rows:
                break

            for row in rows:
                values = [row[c] for c in col_list]
                new_cursor.execute(
                    f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})',
                    values,
                )
            new_conn.commit()
            migrated_count += len(rows)
            offset += batch_size

        logger.info(f"   📊 {table_name}: 迁移了 {count} 行数据")

    if skipped_tables:
        logger.info(f"   跳过（无交集列）: {', '.join(skipped_tables)}")

    old_conn.close()
    new_conn.close()
    logger.info(f"✅ 数据迁移完成，共迁移 {migrated_count} 行")


def _post_migrate_fixups(db_path: Path) -> None:
    """迁移后修复：为新加列填充值、清理脏数据、从旧配置创建 users 记录。"""
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 1. 为 my_prs 和 user_issues 中 github_id 为空的旧数据填充占位值
    #    （复合主键不允许 NULL 参与唯一性比较，但实际按用户查询时这些行不会被命中）
    #    更好的做法：如果能从旧系统获取 GITHUB_USERNAME，就用它填充
    from app.config import Config
    old_username = os.environ.get("GITHUB_USERNAME", "").strip()
    if old_username:
        cursor.execute(
            'UPDATE my_prs SET github_id = ? WHERE github_id IS NULL OR github_id = ""',
            (old_username,),
        )
        cursor.execute(
            'UPDATE user_issues SET github_id = ? WHERE github_id IS NULL OR github_id = ""',
            (old_username,),
        )
        logger.info(f"   🔧 为旧数据填充 github_id={old_username}")
    else:
        # 没有旧配置，设为空字符串（后续 scheduler 会覆盖，或手动清理）
        cursor.execute(
            'UPDATE my_prs SET github_id = "" WHERE github_id IS NULL'
        )
        cursor.execute(
            'UPDATE user_issues SET github_id = "" WHERE github_id IS NULL'
        )
        logger.info("   🔧 旧数据 github_id 设为空字符串")

    # 2. 从旧 GITHUB_USERNAME 环境变量自动创建 users 记录
    if old_username:
        cursor.execute(
            'SELECT COUNT(*) FROM users WHERE github_id = ?',
            (old_username,),
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                'INSERT INTO users (name, github_id, created_at) VALUES (?, ?, ?)',
                (old_username, old_username, datetime.now(timezone.utc).replace(tzinfo=None).isoformat()),
            )
            logger.info(f"   👤 自动创建 users 记录: {old_username}")

    conn.commit()
    conn.close()


def _replace_db(db_path: Path, new_db_path: Path) -> None:
    """用新数据库替换旧数据库"""
    # 先删除旧库，再重命名新库
    if db_path.exists():
        db_path.unlink()
    new_db_path.rename(db_path)
    logger.info("✅ 数据库替换完成")


# ═══════════════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="数据库 Schema 迁移工具 — 比对 models.py 与 SQLite 的实际 schema",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python scripts/migrate_db.py               # 检查并执行迁移
    python scripts/migrate_db.py --check        # 仅检查差异
    python scripts/migrate_db.py --force        # 跳过差异检查，强制重建
        """,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查差异，不执行迁移",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="跳过差异检查，强制重建数据库",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="指定 SQLite 数据库路径（默认使用 Config.DB_PATH）",
    )

    args = parser.parse_args()

    # 确定数据库路径
    if args.db_path:
        db_path = Path(args.db_path).resolve()
    else:
        from app.config import Config
        db_path = Config.DB_PATH

    if not db_path.exists():
        logger.info(f"📦 数据库文件不存在，将按当前 models 创建: {db_path}")
        from app.models import Base
        from sqlalchemy import create_engine
        engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(bind=engine)
        engine.dispose()
        logger.info("✅ 数据库创建完成")
        return

    # 获取代码 schema
    logger.info("正在读取代码中的 schema 定义...")
    code_schema = get_code_schema()

    # 获取数据库 schema
    logger.info("正在读取数据库实际 schema...")
    db_schema = get_db_schema(db_path)

    # 比对
    diff = compare_schemas(code_schema, db_schema)
    print_diff_report(diff)

    if args.check:
        logger.info("🔍 --check 模式，不执行迁移。")
        sys.exit(0 if not diff["has_diff"] else 1)

    if not diff["has_diff"] and not args.force:
        logger.info("无需迁移。")
        return

    if args.force:
        logger.info("⚠️  --force 模式，跳过差异检查，强制重建。")

    # 执行迁移
    migrate(db_path)


if __name__ == "__main__":
    main()