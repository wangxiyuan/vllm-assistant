# vLLM Assistant

vLLM 贡献者效率工具：聚合社区动态、集中管理自己的 PR，NPU 算力统一管理，并提供 AI 辅助（Review 意见生成、PR 总结、翻译等）。

## 功能

- **Community Pulse** — 社区活跃 Issue/PR 一览，按领域过滤，新条目高亮
- **PR Command Center** — 集中管理自己的 PR：CI 状态、冲突检测、贡献统计图表
- **特别关注** — 追踪重点 Issue/PR，支持备注和责任人
- **洞察报告** — AI 生成多源报告（vLLM、vLLM-Ascend、sglang 等），支持每日定时推送
- **模型拆解** — 算子知识库 + 模型架构可视化编辑
- **AI 辅助** — Review 意见生成、PR/Issue 总结、英文翻译、标签建议
- **NPU 算力管理** — 统一纳管 Ascend NPU 机器（SSH），一切任务容器化运行：
  - **机器纳管与巡检**：npu-smi 状态采集（利用率/显存/温度曲线）、驱动版本、`docker images` 与模型目录自动扫描；一键复制 ssh / `docker exec` 命令与 `~/.ssh/config` 片段
  - **任务中心**：自定义命令为一等公民，bash 常驻开发容器（exec 进去改码即生效）；机型模板（A2/A3/300I DUO）自动生成 `docker run` 命令（设备/驱动挂载/`ASCEND_RT_VISIBLE_DEVICES`），提交前可预览，配置可存模板复用；日志实时增量查看
  - **服务部署**：选机器→选模型目录→启动；自动健康检查（/health）；**调试模式**注入 debugpy（一键复制 VSCode launch.json attach 片段，断点打进容器内 vllm/vllm-ascend 源码）；**统一推理网关** `/api/npu/services/{id}/proxy/v1/*`（SSE 流式）+ 内嵌 Playground 对话测试，外部脚本拿统一 base_url
  - **Profiling 采集**：部署时可选开启（自动注入 vllm-ascend 现行 `--profiler-config`），页面一键开始/停止采集（服务自带 `/start_profile` 端点），输出文件列表化、单文件下载，供 MindStudio Insight 离线分析
  - **测试与压测**：预定义用例（OpenAI 接口探活 / 容器命令）；一键 `vllm bench serve` 压测（自动等服务就绪、结果 JSON 解析落库），吞吐/TTFT/TPOT 历史对比
  - **AI Agent 运维**：注册 npu 工具类别，Agent 可对话式查机器、部署服务、跑压测、采集 profile（命令执行带 confirm 守卫）

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
