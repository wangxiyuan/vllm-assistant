# vLLM Assistant

vLLM 贡献者效率工具：聚合社区动态、集中管理自己的 PR 和任务，并提供 AI 辅助（Review 意见生成、PR 总结、翻译等）。

## 功能

- **Community Pulse** — 社区活跃 Issue/PR 一览，按领域过滤，新条目高亮
- **PR Command Center** — 集中管理自己的 PR：CI 状态、冲突检测、贡献统计图表
- **特别关注** — 追踪重点 Issue/PR，支持备注和关联任务
- **个人任务** — Kanban / 列表视图，P0-P3 优先级，可关联社区条目并做去重检查
- **洞察报告** — AI 生成多源报告（vLLM、vLLM-Ascend、sglang 等），可一键关联任务
- **技术 Blog** — Markdown 编辑器，支持代码引用同步、TOC、MathJax
- **模型拆解** — 算子知识库 + 模型架构可视化编辑
- **AI 辅助** — Review 意见生成、PR/Issue 总结、英文翻译、标签建议

数据走 SQLite 缓存，后台定时增量同步 GitHub，不频繁打 API。

## 快速开始

```bash
pip install -r requirements.txt

# 构建前端（产物输出到 static/dist/）
cd frontend && npm install && npm run build && cd ..

cp .env.example .env   # 编辑 .env，至少填写 VLLM_ASSISTANT_PAT

./start.sh             # 或 python -m app.main
```

打开 http://localhost:8000，首次使用先在「用户管理」添加自己的 GitHub ID。API 文档在 http://localhost:8000/docs。

`.env` 常用项（完整说明见 `.env.example`）：

```env
VLLM_ASSISTANT_PAT=github_pat_xxx   # GitHub PAT，必需，需 repo / read:user 权限
OPENAI_API_KEY=sk-xxx               # AI 功能用，可选
OPENAI_BASE_URL=                    # OpenAI 兼容 endpoint，可选
GITHUB_SYNC_ENABLED=true            # 设为 false 禁用定时同步，本地调试省 API 配额
HOST=0.0.0.0
PORT=8000
```

## 前端开发

```bash
cd frontend
npm run dev    # 开发服务器 :5173，/api 代理到后端 :8000
npm run build  # 生产构建
```

## Docker

```bash
./deploy.sh          # 构建并启动
./deploy.sh stop     # 停止
./deploy.sh logs     # 查看日志
```

## 目录结构

```
app/        FastAPI 后端（api/ 路由，services/ 业务逻辑）
frontend/   Vue 3 + TypeScript 前端
docs/       设计文档
static/     前端构建产物
```

## License

MIT
