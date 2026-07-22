# vLLM Assistant

vLLM贡献者效率工具 - 帮助贡献者高效参与社区，加速成为committer

## 功能特性

### 📡 Community Pulse（社区动态感知）
- 实时展示活跃的Issues和PRs
- 按领域过滤（Engine Core, Model Implementation, Hardware等）
- 新items高亮标记
- 一键跳转到GitHub详情页

### 📋 PR Command Center（PR指挥中心）
- 一站式管理你的所有PR
- 自动检测冲突（落后于main的commit数）
- CI状态实时显示（pass/fail/pending）
- Review状态追踪（approved/changes_requested/pending）
- 红色/黄色/绿色高亮问题PR

### 🗺️ Area Explorer（领域探索器）
- 可视化展示vllm所有CODEOWNERS领域
- 显示各领域对应的committer
- 基于你的贡献历史推荐适合focus的领域
- 帮助你建立area ownership

### 🤖 AI Assistant（AI辅助）⭐
- **Review意见生成**：基于PR diff自动生成结构化review建议
- **PR影响范围分析**：分析变更可能影响的模块和测试
- **Issue分类建议**：根据内容推荐标签和领域
- **Committer路径规划**：基于你的贡献数据，给出达到committer标准的路径建议

## 快速开始

### 1. 安装依赖

```bash
cd vllm-assistant
pip install -r requirements.txt
```

### 2. 配置环境变量

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

### 3. 启动服务

**方式一：使用启动脚本（推荐）**
```bash
./start.sh
```

**方式二：手动启动**
```bash
python -m app.main
```

或使用uvicorn：
```bash
uvicorn app.main:app --reload
```

### 4. 访问Web界面

打开浏览器访问：http://localhost:8000

## 配置说明

### GitHub PAT权限要求

需要以下scopes：
- `repo` - 访问仓库信息
- `read:user` - 获取用户信息

### OpenAI配置（可选）

如需使用AI辅助功能，配置OpenAI API Key：

```yaml
ai:
  provider: "openai"
  api_key: "${OPENAI_API_KEY}"
  base_url: "https://api.openai.com/v1"  # 可自定义endpoint
  model: "gpt-4o"
```

## 项目结构

```
vllm-assistant/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理（支持 .env 和 config.yaml）
│   ├── database.py          # SQLite 引擎 + Session
│   ├── models.py            # SQLAlchemy ORM 模型
│   ├── schemas.py           # Pydantic 请求/响应模型
│   ├── scheduler.py         # APScheduler 定时同步（缓存优先）
│   ├── api/                 # API 路由
│   │   ├── community.py     # Community Pulse（读缓存）
│   │   ├── pr_center.py     # PR Command Center（读缓存）
│   │   ├── area_explorer.py # Area Explorer（读缓存）
│   │   └── ai_assistant.py  # AI Assistant
│   └── services/            # 服务层
│       ├── github_client.py     # GitHub REST API 封装
│       ├── area_mapper.py       # CODEOWNERS 解析
│       ├── conflict_detector.py # Compare API 冲突检测
│       ├── recommender.py       # 领域推荐
│       └── ai_assistant.py      # OpenAI API 集成
├── static/                  # 前端（CDN + Alpine.js）
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── app.js
│       ├── community.js
│       ├── pr_center.js
│       ├── area_explorer.js
│       └── ai_assistant.js
├── tests/                   # 单元测试
├── requirements.txt
└── README.md
```

## 数据策略

- **缓存优先**：所有 API 端点优先从 SQLite 缓存读取，scheduler 后台增量同步 GitHub 数据
- **增量拉取**：每次轮询只拉取 `since=now-1.5*interval` 的新数据
- **手动刷新**：`GET /api/community/items?force_refresh=true` 触发同步后返回
- **领域过滤**：通过 `POLLING_AREAS` 环境变量只同步指定领域

## API文档

启动服务后访问：http://localhost:8000/docs

主要API端点：

- `GET /api/community/items` - 获取社区动态
- `GET /api/community/areas` - 获取领域列表
- `GET /api/pr-center/my-prs` - 获取我的PR列表
- `POST /api/ai-assistant/generate-review` - 生成Review意见
- `POST /api/ai-assistant/analyze-impact` - 分析影响范围
- `POST /api/refresh` - 手动触发后台同步
- `GET /api/status` - 查看 scheduler 状态
- `GET /health` - 健康检查（含配置状态）

## 故障排查

### "请配置 GITHUB_USERNAME" 错误
- 编辑 `.env`，设置 `GITHUB_USERNAME=your_github_handle`
- 重启服务让 scheduler 重新加载

### 社区动态一直为空
- 检查 `GET /api/status` 看 scheduler 是否在跑
- 点击前端"刷新"按钮触发 `force_refresh=true`
- 查看 server log：scheduler 会输出 `Synced N issues` 或 `401 Unauthorized`
- 401 表示 PAT 无效：去 https://github.com/settings/tokens 重新生成

### "OPENAI_API_KEY not configured" 
- AI 功能可选，不影响其他视图
- 需要时在 `.env` 配 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`

### 数据库 schema 不匹配
- 删除 `data/vllm_assistant.db` 后重启，scheduler 会自动重建表

## 开发指南

### 运行测试

```bash
pytest tests/
```

### 添加新功能

1. 在 `app/services/` 创建新的服务模块
2. 在 `app/api/` 创建对应的API路由
3. 在 `static/index.html` 添加前端视图
4. 更新 `app/main.py` 注册新路由

## License

MIT License
