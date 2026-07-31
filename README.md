# vLLM Assistant

vLLM 贡献者效率工具 - 帮助贡献者高效参与社区，加速成为 committer

## 功能特性

### 📡 Community Pulse（社区动态感知）
- 实时展示活跃的 Issues 和 PRs
- 按领域过滤（Engine Core, Model Implementation, Hardware 等）
- 新 items 高亮标记
- AI 标签建议
- 一键跳转到 GitHub 详情页

### 📋 PR Command Center（PR 指挥中心）
- 一站式管理你的所有 PR
- 按贡献者过滤，查看个人贡献数据
- 月度贡献柱状图
- CI 状态实时显示（pass/fail/pending）
- 冲突检测过滤
- PR/Issue 详情抽屉，支持 AI 总结、Review、翻译

### ⭐ 特别关注（Watchlist）
- 追踪重要的 Issue 和 PR
- 添加备注和责任人
- 关联个人任务
- 一键从 GitHub 编号添加

### 📝 任务面板（Personal Todo）
- 个人任务管理（P0-P3 优先级）
- Kanban 卡片视图 / 列表视图
- 子任务支持
- 任务去重检查（关联社区 Issue/PR）
- 关联洞察报告生成

### 🔍 洞察面板（Intelligence Reports）
- AI 驱动的多源报告生成
- 支持来源：vLLM 社区、vLLM-Ascend、sglang、学术动态、新闻
- 关联任务自动生成
- 报告状态轮询
- Markdown 导出

### 📚 技术 Blog（Articles）
- Markdown 文章编辑器
- 代码引用嵌入（自动同步仓库代码）
- 引用有效性验证
- 目录（TOC）导航
- MathJax 数学公式支持
- 发布/草稿管理

### 🧠 模型拆解（Model Anatomy）
- 算子知识库管理
- 模型架构可视化编辑器
- 算子分类管理
- 架构图渲染（重复块、嵌套算子）

### 🤖 AI Assistant（AI 辅助）
- **Review 意见生成**：基于 PR diff 自动生成结构化 review 建议
- **PR/Issue 总结**：自动提取核心问题、关键要点、影响范围
- **英文翻译**：一键翻译 PR/Issue 描述为中文
- **Issue 分类建议**：根据内容推荐标签和领域

## 快速开始

### 1. 安装依赖

```bash
cd vllm-assistant
pip install -r requirements.txt
```

### 2. 安装前端依赖并构建

```bash
cd frontend
npm install
npm run build
cd ..
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并填写必要配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# GitHub Personal Access Token (required)
VLLM_ASSISTANT_PAT=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# OpenAI API Key for AI Assistant (optional but recommended)
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# Server configuration
HOST=0.0.0.0
PORT=8000
```

### 4. 启动服务

**方式一：使用启动脚本（推荐）**
```bash
./start.sh
```

**方式二：手动启动**
```bash
python -m app.main
```

或使用 uvicorn（开发模式）：
```bash
uvicorn app.main:app --reload
```

### 5. 访问 Web 界面

打开浏览器访问：http://localhost:8000

## 前端开发

前端使用 Vue 3 + TypeScript + Vite 构建，代码位于 `frontend/` 目录。

```bash
cd frontend

# 启动开发服务器（端口 5173，自动代理 /api 到后端 :8000）
npm run dev

# 构建生产版本（输出到 static/dist/）
npm run build
```

### 技术栈

- **Vue 3** (Composition API) — 前端框架
- **TypeScript** — 类型安全
- **Vite** — 构建工具
- **Pinia** — 状态管理
- **Vue Router** — 路由

## Docker 部署

```bash
# 构建并启动
./deploy.sh

# 停止
./deploy.sh stop

# 重启
./deploy.sh restart

# 查看日志
./deploy.sh logs
```

## 配置说明

### GitHub PAT 权限要求

需要以下 scopes：
- `repo` — 访问仓库信息
- `read:user` — 获取用户信息

### OpenAI 配置（可选）

如需使用 AI 辅助功能，配置 OpenAI API Key：

```yaml
ai:
  provider: "openai"
  api_key: "${OPENAI_API_KEY}"
  base_url: "https://api.openai.com/v1"  # 可自定义 endpoint
  model: "gpt-4o"
```

## 项目结构

```
vllm-assistant/
├── app/                          # FastAPI 后端
│   ├── main.py                   # FastAPI 入口
│   ├── config.py                 # 配置管理
│   ├── database.py               # SQLite 引擎 + Session
│   ├── models.py                 # SQLAlchemy ORM 模型
│   ├── schemas.py                # Pydantic 请求/响应模型
│   ├── scheduler.py              # APScheduler 定时同步
│   ├── api/                      # API 路由
│   │   ├── community.py          # 社区动态
│   │   ├── pr_center.py          # PR 中心
│   │   ├── watchlist.py          # 特别关注
│   │   ├── my_stats.py           # 贡献统计
│   │   ├── personal_todo.py      # 个人任务
│   │   ├── intelligence.py       # 洞察报告
│   │   ├── articles.py           # 技术博客
│   │   ├── model_anatomy.py      # 模型拆解
│   │   ├── ai_assistant.py       # AI 助手
│   │   └── ai_agent.py           # AI Agent
│   └── services/                 # 服务层
│       ├── github_client.py      # GitHub API 封装
│       ├── area_mapper.py        # CODEOWNERS 解析
│       ├── conflict_detector.py  # 冲突检测
│       ├── task_dedup.py         # 任务去重
│       ├── ai_assistant.py       # OpenAI 集成
│       ├── intelligence_report.py # 报告生成
│       ├── agent_runner.py       # Agent 运行器
│       ├── memory_service.py     # 记忆服务
│       └── repo_manager.py       # 仓库管理
├── frontend/                     # Vue 3 前端
│   ├── index.html                # SPA 入口
│   ├── package.json              # 依赖配置
│   ├── vite.config.ts            # Vite 配置
│   ├── tsconfig.json             # TypeScript 配置
│   └── src/
│       ├── main.ts               # 应用入口
│       ├── App.vue               # 根组件
│       ├── router/               # Vue Router 路由
│       ├── api/                  # API 客户端
│       ├── stores/               # Pinia 状态管理
│       ├── composables/          # 组合式函数
│       ├── utils/                # 工具函数 + 类型定义
│       ├── components/
│       │   ├── layout/           # 布局组件
│       │   ├── auth/             # 认证组件
│       │   ├── common/           # 通用组件
│       │   ├── markdown/         # Markdown 渲染
│       │   ├── ai/               # AI 结果展示
│       │   └── modals/           # 弹窗/抽屉
│       └── views/                # 页面视图
│           ├── CommunityView.vue
│           ├── WatchlistView.vue
│           ├── PRCenterView.vue
│           ├── PersonalTodoView.vue
│           ├── IntelligenceView.vue
│           ├── ArticlesView.vue
│           └── ModelAnatomyView.vue
├── static/                       # 静态文件
│   └── dist/                     # 前端构建产物（gitignore）
├── deploy.sh                     # Docker 部署脚本
├── start.sh                      # 启动脚本
├── Dockerfile                    # Docker 构建
├── docker-compose.yml            # Docker Compose
└── README.md
```

## 数据策略

- **缓存优先**：所有 API 端点优先从 SQLite 缓存读取，scheduler 后台增量同步 GitHub 数据
- **增量拉取**：每次轮询只拉取 `since=now-1.5*interval` 的新数据
- **手动刷新**：点击界面 R 键或刷新按钮触发同步

## API 文档

启动服务后访问：http://localhost:8000/docs

## 故障排查

### 贡献数据为空
- 在「用户管理」中添加用户，填写 GitHub ID
- Scheduler 会在下次同步时自动拉取该用户的 PR/Issue 数据
- 也可手动触发同步：按 R 键或点击刷新按钮

### 社区动态一直为空
- 检查 `GET /api/status` 看 scheduler 是否在跑
- 查看 server log：scheduler 会输出 `Synced N issues` 或 `401 Unauthorized`
- 401 表示 PAT 无效：去 https://github.com/settings/tokens 重新生成

### "OPENAI_API_KEY not configured"
- AI 功能可选，不影响其他视图
- 需要时在 `.env` 配 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`

### 数据库 schema 不匹配
- 删除 `data/vllm_assistant.db` 后重启，scheduler 会自动重建表

### 前端报错
- 确保已执行 `cd frontend && npm install && npm run build`
- 开发模式使用 `cd frontend && npm run dev`（需同时运行后端）

## 开发指南

### 运行测试

```bash
pytest tests/
```

### 添加新功能

1. 在 `app/services/` 创建新的服务模块
2. 在 `app/api/` 创建对应的 API 路由
3. 在 `frontend/src/views/` 添加新视图组件
4. 在 `frontend/src/router/index.ts` 注册新路由
5. 更新 `app/main.py` 注册新路由

## License

MIT License