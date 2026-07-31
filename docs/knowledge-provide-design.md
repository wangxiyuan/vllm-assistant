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

## 方案 ：MCP Server（主推，实时查询）

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
