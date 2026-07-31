# 知识库 MCP 包导出设计

## 概述

为 vLLM Assistant 提供一个知识库导出功能，允许用户将当前的知识库数据（`ai_memory` 表）+ MCP stdio 脚本打包成 zip 压缩包下载。第三方用户可以直接用这个包配置到本地 agent（如 opencode、claude code）中，无需部署整个服务。

典型场景：vllm-ascend 做 main2main 适配 vllm 时，用这个知识库包快速获取 vllm 项目的代码结构、文档、issue/PR 等知识。

## 架构

```
用户点击"下载 MCP"按钮
        │
        ▼
前端 fetch /api/knowledge/export（带 Bearer Token）
        │
        ▼
后端连接原始 SQLite 数据库
  1. SELECT * FROM ai_memory → 写入临时精简库
  2. 重建 ai_memory_fts FTS5 索引
  3. 读取 scripts/mcp/mcp_server.py
        │
        ▼
zipfile 打包（精简库 + mcp_server.py）
        │
        ▼
返回 StreamingResponse (application/zip)
```

## 后端接口

### `GET /api/knowledge/export`

**认证**：通过 AuthMiddleware 的 Bearer Token 验证（与现有 `/api/*` 路由一致）

**响应**：
- Content-Type: `application/zip`
- Content-Disposition: `attachment; filename="vllm-knowledge-mcp-{date}.zip"`
- Body: zip 包

**ZIP 包内容**：
```
vllm-knowledge-mcp-{date}.zip
├── scripts/mcp/mcp_server.py   # MCP stdio 协议脚本
└── data/vllm_assistant.db       # 精简版 SQLite 知识库（仅 ai_memory 表）
```

### 精简数据库生成逻辑

1. 用 `sqlite3` 连接原始数据库（只读模式）
2. 在临时文件中创建新库：
   - 创建 `ai_memory` 表（与原始库相同的 schema）
   - `INSERT INTO ... SELECT * FROM original.ai_memory WHERE is_stale = 0`
   - 创建 `ai_memory_fts` FTS5 虚拟表
   - 重建 FTS 索引：`INSERT INTO ai_memory_fts(rowid, content) SELECT id, content FROM ai_memory`
3. 临时文件用完即删

**为什么不直接拷贝原始数据库？**
原始数据库包含 `local_code_cache`（~83M）、`items`（~8.5M）等大表，总计约 132M。MCP 脚本只用到 `ai_memory`（~17M），导出精简版可大幅减小 zip 体积。

## 前端改动

**文件**：`frontend/src/views/AIAgentView.vue`

在知识库侧边栏的 `kb-stats-header` 区域（"共 N 条"和"+ 添加知识"之间）添加"下载 MCP"按钮：

```html
<button class="btn btn-sm" @click="downloadMcpPackage">
  下载 MCP
</button>
```

点击后通过 `fetch` 携带认证头获取二进制流，用 `blob` 方式触发浏览器下载：

```typescript
function downloadMcpPackage() {
  const headers: Record<string, string> = {}
  const authStore = useAuthStore()
  if (authStore.token) headers['Authorization'] = `Bearer ${authStore.token}`
  
  fetch('/api/knowledge/export', { headers })
    .then(res => res.blob())
    .then(blob => {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `vllm-knowledge-mcp-${new Date().toISOString().slice(0, 10)}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    })
}
```

## 用户配置指南

下载 zip 并解压后，配置到 agent 的 MCP：

### opencode (`~/.config/opencode/opencode.jsonc`)
```jsonc
{
  "mcp": {
    "vllm-knowledge": {
      "type": "local",
      "command": ["python", "/path/to/scripts/mcp_server.py"],
      "enabled": true
    }
  }
}
```

### claude code (`.claude/settings.local.json`)
```json
{
  "mcpServers": {
    "vllm-knowledge": {
      "command": "python",
      "args": ["scripts/mcp_server.py"]
    }
  }
}
```

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/api/knowledge_export.py` | 新建 | 导出 API 端点 |
| `app/main.py` | 修改 | 注册新路由 |
| `frontend/src/views/AIAgentView.vue` | 修改 | 添加下载按钮 |