# 知识库对外暴露方案设计

> 日期: 2026-07-31
> 目标: 将生产环境 vLLM Assistant SQLite 中的知识库（ai_memory + articles）暴露给 opencode、claude code 等外部 agent 工具使用。

---

## 架构总览

```
                    ┌──────────────────────┐
                    │  opencode / claude    │
                    │  code / 其他 agent    │
                    └──────┬───────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │  MCP     │ │ MCP      │ │ 本地文件  │
       │  HTTP    │ │ Filesys  │ │ 直接读取  │
       └────┬─────┘ └──────────┘ └──────────┘
            │
            ▼
    ┌───────────────┐     ┌───────────────┐
    │ vLLM Assistant │     │ 导出脚本       │
    │ (Docker 容器)  │────▶│ exported_knowl-│
    │ /api/mcp       │     │ edge/ 目录     │
    │                │     │ (Markdown)    │
    └───────┬───────┘     └───────────────┘
            │
            ▼
    ┌───────────────┐
    │  SQLite 知识库  │
    │ (ai_memory +   │
    │  articles)     │
    └───────────────┘
```

---

## 方案 A：MCP Server（主推，实时查询）

在 vllm-assistant 服务内新增一个 MCP 协议 endpoint，外部 agent 通过 HTTP 远程调用，实时搜索知识库。

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/api/mcp.py` | 新增 | MCP 协议实现，暴露 3 个工具 |
| `app/main.py` | 修改 | 注册 mcp router，+2 行 |

### MCP 工具定义

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `knowledge_search` | FTS5 全文检索知识库 | query(必填), top_k, tags, source_type |
| `knowledge_list` | 按 source_type 分页浏览 | source_type, offset, limit, query |
| `knowledge_stats` | 知识库统计 | 无 |

### MCP 协议端点

- `GET /api/mcp` — 返回 tools list
- `POST /api/mcp` — 接收 `tools/call` 请求并执行

遵循 MCP 规范（Model Context Protocol），请求/响应格式为 JSON-RPC。

### 认证

复用已有的 `AuthMiddleware`，外部 agent 在 HTTP Header 中传入 `Authorization: Bearer <API_KEY>`。

### 外部 agent 配置

**opencode**（`~/.config/opencode/opencode.jsonc`）：

```json
"mcp": {
  "vllm-knowledge": {
    "type": "url",
    "url": "http://ip1:9527/api/mcp",
    "headers": {
      "Authorization": "Bearer <你的API_KEY>"
    },
    "enabled": true
  }
}
```

**claude code**（`.claude/settings.local.json`）：

```json
{
  "mcpServers": {
    "vllm-knowledge": {
      "type": "url",
      "url": "http://ip2:9527/api/mcp",
      "headers": {
        "Authorization": "Bearer <你的API_KEY>"
      }
    }
  }
}
```

> `ip1` 是公网 Nginx 代理地址，`ip2` 是内网应用服务器地址。按实际部署拓扑选择。

### 优点

- 实时查询，知识更新即时可用
- 无需数据同步，无数据冗余
- 改动极小（新增 1 个文件 + 1 行路由注册）
- 部署后无需额外运维

### 注意

- 依赖网络连通性
- 外部 agent 需要配置 `API_KEY`

---

## 方案 B：导出为本地 Markdown 文件（备选，离线可用）

将知识库导出为本地 markdown 文件目录，通过 opencode/claude code 的 file context 或 MCP filesystem 使用。

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/export_knowledge.py` | 新增 | 从 SQLite 读取并导出为 markdown |

### 导出目录结构

```
exported_knowledge/
├── INDEX.md                          # 总索引
├── articles/                         # 文章（--include-articles）
│   ├── 0001-Transformer-Architecture.md
│   └── ...
├── code_structure/                   # 代码结构知识
│   ├── 0001-attention-module.md
│   └── ...
├── docs/                             # 文档知识
├── issue/                            # Issue 总结
├── pr/                               # PR 分析
├── manual/                           # 手动录入
└── ...
```

### 使用方式

```bash
# 在宿主机上导出（需要有 sqlite 文件读权限）
python scripts/export_knowledge.py -o /path/to/knowledge --include-articles

# 或通过 docker exec
docker exec vllm-assistant python scripts/export_knowledge.py -o /tmp/knowledge
docker cp vllm-assistant:/tmp/knowledge ./knowledge
```

### opencode 配置（MCP filesystem）

```json
"mcp": {
  "knowledge-fs": {
    "type": "local",
    "command": [
      "npx", "-y", "@modelcontextprotocol/server-filesystem",
      "/path/to/exported_knowledge"
    ],
    "enabled": true
  }
}
```

### 优点

- 离线可用，不依赖网络
- 可直接被 agent 读取（无需 HTTP 调用）
- 导出目录可被任何工具使用

### 缺点

- 知识更新后需要重新导出
- 有数据冗余，占用磁盘空间

---

## 数据库模型参考

### ai_memory 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| content | Text | 知识内容（Markdown） |
| source_type | String(30) | 来源类型：docs/code_structure/issue/pr/article/manual/conversation/report |
| source_ref | Text | 来源引用，如 "vllm-project/vllm#1234" |
| tags | Text | JSON 数组标签 |
| checksum | String(64) | 文件内容 hash |
| is_stale | Boolean | 是否过时 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### articles 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| title | Text | 标题 |
| content | Text | Markdown 原文 |
| area | String(50) | 所属领域 |
| tags | Text | JSON 数组标签 |
| status | String(20) | draft/published/archived |

---

## 方案 C：MCP stdio 本地脚本（推荐，本地开发用）

在本地开发时，agent 通过一个独立的 Python 脚本直接读取本地 SQLite 数据库，无需启动 HTTP 服务。

### 架构

```
agent (opencode/claude code)
        │
        │  MCP stdio 协议 (stdin/stdout)
        ▼
scripts/mcp/mcp_server.py
        │
        │  直接读同目录 SQLite
        ▼
scripts/mcp/vllm_assistant.db
```

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/mcp/mcp_server.py` | 新增 | MCP stdio server，直接读本地 sqlite |
| `.claude/settings.local.json` | 修改 | 注册 MCP server |
| `CLAUDE.md` | 修改 | 添加使用说明 |

### 工具定义

与方案 A 一致：`knowledge_search`、`knowledge_list`、`knowledge_stats`。

### 外部 agent 配置

**opencode**（`~/.config/opencode/opencode.jsonc`）：

```json
"mcp": {
  "vllm-knowledge": {
    "type": "local",
    "command": ["python", "/path/to/vllm-assistant/scripts/mcp/mcp_server.py"],
    "enabled": true
  }
}
```

**claude code**（项目目录下 `.claude/settings.local.json`）：

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

### 拷贝生产环境知识库到本地

SQLite 是单文件数据库，生产库可直接拷贝到本地使用：

```bash
# 先合并 WAL 再拷贝（避免 WAL 文件不一致）
docker exec vllm-assistant python -c "
import sqlite3
conn = sqlite3.connect('/app/data/vllm_assistant.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"
docker cp vllm-assistant:/app/data/vllm_assistant.db ./scripts/mcp/vllm_assistant.db
```

### 优点

| 对比项 | 方案 C（MCP stdio） | 方案 A（MCP HTTP） |
|--------|---------------------|---------------------|
| 启动服务 | 不需要 | 需要 Docker/uvicorn 运行中 |
| 依赖 | Python 标准库 | 需 FastAPI + uvicorn |
| 认证 | 不需要 | 需要 API_KEY |
| 性能 | 直接读文件，毫秒级 | HTTP 网络开销 |
| 开发调试 | 可直接运行测试 | 需 curl 测试 |

### 注意

- 读的是本地 sqlite 文件，需要自己从生产同步 db 文件到 `scripts/mcp/` 目录
- 只读不写，不会污染生产库