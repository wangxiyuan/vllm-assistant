"""
MCP stdio Server — 直接读取本地 SQLite 知识库

供 opencode、claude code 等本地 agent 直接查询知识库，无需启动 HTTP 服务。

用法:
    python scripts/mcp_server.py

通过 stdin/stdout 实现 MCP stdio 协议，暴露工具:
    - knowledge_search: FTS5 全文检索
    - knowledge_list:   按 source_type 分页浏览
    - knowledge_stats:  知识库统计

配置:
    opencode (~/.config/opencode/opencode.jsonc):
        "mcp": {
          "vllm-knowledge": {
            "type": "local",
            "command": ["python", "/path/to/scripts/mcp_server.py"],
            "enabled": true
          }
        }

    claude code (.claude/settings.local.json):
        {
          "mcpServers": {
            "vllm-knowledge": {
              "command": "python",
              "args": ["scripts/mcp_server.py"]
            }
          }
        }
"""
import json
import logging
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                    format="%(levelname)s: %(message)s")
logger = logging.getLogger("mcp-knowledge")

# 数据库路径 — 与 mcp_server.py 同目录
DB_PATH = Path(__file__).resolve().parent / "vllm_assistant.db"


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _entry_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "content": row["content"],
        "source_type": row["source_type"],
        "source_ref": row["source_ref"] or "",
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "updated_at": (row["updated_at"] + "Z") if row["updated_at"] else None,
    }


def knowledge_search(query: str, top_k: int = 5,
                     tags: str = "", source_type: str = "") -> list:
    if not query.strip():
        return []
    conn = get_db()
    try:
        escaped = query.replace("'", "''")
        fts_sql = """
            SELECT rowid FROM ai_memory_fts
            WHERE ai_memory_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        rows = conn.execute(fts_sql, (escaped, top_k * 3)).fetchall()
        if not rows:
            rows = conn.execute(
                fts_sql,
                (f"{escaped}*", top_k * 3),
            ).fetchall()
        if not rows:
            return []

        row_ids = [r[0] for r in rows]
        placeholders = ",".join("?" for _ in row_ids)
        sql = f"SELECT * FROM ai_memory WHERE id IN ({placeholders}) AND is_stale = 0"

        if source_type:
            st_list = [s.strip() for s in source_type.split(",") if s.strip()]
            if st_list:
                st_placeholders = ",".join("?" for _ in st_list)
                sql += f" AND source_type IN ({st_placeholders})"
                rows = conn.execute(sql, (*row_ids, *st_list)).fetchall()
            else:
                rows = conn.execute(sql, row_ids).fetchall()
        else:
            rows = conn.execute(sql, row_ids).fetchall()

        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            filtered = []
            for r in rows:
                entry_tags = json.loads(r["tags"]) if r["tags"] else []
                if any(t in entry_tags for t in tag_list):
                    filtered.append(r)
            rows = filtered

        rows.sort(key=lambda r: r["updated_at"] or "", reverse=True)
        return [_entry_to_dict(r) for r in rows[:top_k]]
    finally:
        conn.close()


def knowledge_list(source_type: str = "", offset: int = 0,
                   limit: int = 20, query: str = "") -> dict:
    conn = get_db()
    try:
        if source_type:
            base_sql = "SELECT * FROM ai_memory WHERE source_type = ? AND is_stale = 0"
            count_sql = "SELECT COUNT(*) FROM ai_memory WHERE source_type = ? AND is_stale = 0"
            params = [source_type]
        else:
            base_sql = "SELECT * FROM ai_memory WHERE is_stale = 0"
            count_sql = "SELECT COUNT(*) FROM ai_memory WHERE is_stale = 0"
            params = []

        if query.strip():
            like = f"%{query.strip()}%"
            base_sql += " AND (content LIKE ? OR source_ref LIKE ?)"
            count_sql += " AND (content LIKE ? OR source_ref LIKE ?)"
            params.extend([like, like])

        total = conn.execute(count_sql, params).fetchone()[0]
        entries = conn.execute(
            base_sql + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        return {
            "results": [_entry_to_dict(r) for r in entries],
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total,
        }
    finally:
        conn.close()


def knowledge_stats() -> dict:
    conn = get_db()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM ai_memory WHERE is_stale = 0"
        ).fetchone()[0]
        stale = conn.execute(
            "SELECT COUNT(*) FROM ai_memory WHERE is_stale = 1"
        ).fetchone()[0]
        type_rows = conn.execute(
            "SELECT source_type, COUNT(*) as cnt FROM ai_memory WHERE is_stale = 0 GROUP BY source_type"
        ).fetchall()
        by_type = {r["source_type"]: r["cnt"] for r in type_rows}
        known_types = ["docs", "code_structure", "issue", "pr",
                       "article", "manual", "conversation", "report"]
        for t in known_types:
            by_type.setdefault(t, 0)
        return {"total": total, "stale": stale, "by_type": by_type}
    finally:
        conn.close()


# ======================================================================
# MCP stdio 协议实现
# ======================================================================

TOOLS = [
    {
        "name": "knowledge_search",
        "description": "Search knowledge base using full-text search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keywords"},
                "top_k": {"type": "integer", "description": "Max results", "default": 5},
                "tags": {"type": "string", "description": "Filter by tags, comma-separated"},
                "source_type": {"type": "string", "description": "Filter by source type, comma-separated"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "knowledge_list",
        "description": "List knowledge entries by source type with pagination",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_type": {"type": "string", "description": "Source type filter"},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
                "limit": {"type": "integer", "description": "Page size", "default": 20},
                "query": {"type": "string", "description": "Optional keyword filter"},
            },
            "required": [],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "Get knowledge base statistics",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def handle_request(req: dict) -> dict:
    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "vllm-knowledge",
                    "version": "1.0.0"
                }
            }
        }

    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    elif method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "knowledge_search":
                result = knowledge_search(**args)
            elif name == "knowledge_list":
                result = knowledge_list(**args)
            elif name == "knowledge_stats":
                result = knowledge_stats()
            else:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                }
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]},
            }
        except Exception as e:
            logger.exception("Tool call failed")
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32603, "message": str(e)},
            }

    elif method == "notifications/initialized":
        return None

    else:
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}


def main():
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        logger.error("Make sure the vLLM Assistant service has been started at least once.")
        sys.exit(1)

    logger.info(f"MCP knowledge server started, db: {DB_PATH}")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {line}")
            continue

        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()