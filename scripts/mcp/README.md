## 本地开发：通过 MCP 在 agent 中使用知识库

在本地开发时，agent（opencode/claude code）可以直接读取本地 SQLite 中的知识库，
无需启动 HTTP 服务或配置 API Key。

### 1. 准备知识库文件

将生产环境的 SQLite 数据库拷贝到 `scripts/mcp/` 目录下：

```bash
# 从生产容器拷贝（先合并 WAL 避免文件不一致）
docker exec vllm-assistant python -c "
import sqlite3
conn = sqlite3.connect('/app/data/vllm_assistant.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"
docker cp vllm-assistant:/app/data/vllm_assistant.db ./scripts/mcp/vllm_assistant.db
```

### 2. 启动 MCP 知识库 Server

```bash
python scripts/mcp/mcp_server.py
```

脚本会监听 stdin/stdout，实现 MCP stdio 协议。直接运行不会有输出，
等待 agent 通过 stdin 发送 MCP 请求。

### 3. 配置到 agent

**opencode**（`~/.config/opencode/opencode.jsonc`）：

```jsonc
"mcp": {
  "vllm-knowledge": {
    "type": "local",
    "command": ["python", "/path/to/vllm-assistant/scripts/mcp/mcp_server.py"],
    "enabled": true
  }
}
```

**claude code**（在项目目录下 `.claude/settings.local.json`）：

```json
{
  "mcpServers": {
    "vllm-knowledge": {
      "command": "python",
      "args": ["scripts/mcp/mcp_server.py"]
    }
  }
}
```

### 4. 暴露的 MCP 工具

| 工具名 | 说明 | 关键参数 |
|--------|------|----------|
| `knowledge_search` | FTS5 全文检索知识库 | `query`(必填), `top_k`, `tags`, `source_type` |
| `knowledge_list` | 按 source_type 分页浏览 | `source_type`, `offset`, `limit`, `query` |
| `knowledge_stats` | 知识库统计信息 | 无 |

### 5. 在 agent 中使用的提示词示例

在对话中，agent 会自动发现 MCP 工具，可以这样触发：

```
请搜索知识库中关于 attention mechanism 的内容
```

或显式调用：

```
请使用 knowledge_search 工具搜索 "flash attention"，返回 5 条结果
```