# vLLM Assistant — 生产部署指南

> ⚠️ **重要：当前服务已通过 `deploy.sh` 部署在生产环境运行。所有代码修改必须考虑服务升级的兼容性，尤其是数据库 schema 变更。修改前请仔细评估对现有生产实例的影响，遵循向后兼容原则。**

## 架构概览

生产环境采用**双机部署**架构：

```
                           公网用户
                               │
                               ▼
                     ┌───────────────────┐
                     │  机器 ip1 (公网)   │
                     │  Nginx 反向代理    │
                     │  监听 0.0.0.0:9527 │
                     └────────┬──────────┘
                              │ ip1:9527 → ip2:9527
                              ▼
                     ┌───────────────────┐
                     │  机器 ip2 (内网)   │
                     │  Docker 容器化部署  │
                     │  宿主机 9527       │
                     │  ⇄ 容器内 9527     │
                     └───────────────────┘
```

- **ip1** — 面向公网的 Nginx 反向代理服务器，监听 `9527` 端口
- **ip2** — 内网应用服务器，通过 Docker Compose 运行 vLLM Assistant

---

## 一、在 ip2 上部署应用服务

### 1. 前置条件

- Docker Engine ≥ 20.10
- Docker Compose Plugin (v2) 或 `docker-compose` (v1)
- git

### 2. 部署步骤

```bash
# 克隆代码
git clone <your-repo-url> /path/to/vllm-assistant
cd /path/to/vllm-assistant

# 执行部署脚本
./deploy.sh
```

部署过程中脚本会：

1. 检查 Docker / Docker Compose 环境
2. 检查 `.env` 文件，缺失时从 `.env.example` 创建
3. 引导填写 GitHub PAT 等必要环境变量
4. 构建 Docker 镜像并启动容器

### 3. 部署后验证

在 ip2 本机验证服务是否正常：

```bash
curl http://localhost:9527/health
```

预期返回 `{"status": "ok"}` 或类似 JSON 响应。

### 4. 常用管理命令

| 操作 | 命令 |
|------|------|
| 部署/重新部署 | `./deploy.sh` |
| 停止服务 | `./deploy.sh stop` |
| 重启服务 | `./deploy.sh restart` |
| 查看日志 | `./deploy.sh logs` |
| 重置数据 | `./deploy.sh reset` |
| 清除数据 | `./deploy.sh clean` |

### 5. 更新服务

```bash
git pull
./deploy.sh
```

脚本会自动检测代码变更并触发镜像重建和容器替换。

---

## 二、在 ip1 上配置 Nginx 反向代理

### 1. 安装 Nginx

```bash
# Ubuntu/Debian
apt update && apt install -y nginx

# CentOS/RHEL
yum install -y nginx

# macOS (开发环境)
brew install nginx
```

### 2. 创建 Nginx 配置文件

创建 `/etc/nginx/conf.d/vllm-assistant.conf`（或 `/usr/local/etc/nginx/servers/vllm-assistant.conf`）：

```nginx
server {
    listen 9527;
    server_name _;

    location / {
        proxy_pass http://ip2:9527;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        client_max_body_size 50m;
    }
}
```

> 请将 `ip2` 替换为 ip2 的实际内网 IP 地址。

**关键配置说明：**

| 参数 | 说明 |
|------|------|
| `proxy_pass http://ip2:9527` | 请求转发到 ip2 的 9527 端口 |
| `proxy_http_version 1.1` | 支持 WebSocket 升级必须 |
| `proxy_set_header Upgrade` / `Connection "upgrade"` | 支持 WebSocket 长连接 |
| `proxy_read_timeout 300s` | 后端响应超时 5 分钟（AI 推理可能耗时较长） |
| `client_max_body_size 50m` | 上传请求体最大 50MB |

### 3. 启用并重启 Nginx

```bash
# 检查配置语法
nginx -t

# 重新加载配置
nginx -s reload

# 或 systemctl（Linux）
systemctl restart nginx
```

### 4. 验证公网访问

```bash
# 从任意机器访问
curl http://ip1:9527/health

# 或浏览器访问
open http://ip1:9527
```

---

## 三、端口映射说明

生产环境中，`.env` 配置了 `PORT=9527`，因此整体映射链路为：

```
ip1 Nginx 0.0.0.0:9527  →  ip2 宿主机 :9527  →  容器内 :9527
```

| 位置 | 端口 | 说明 |
|------|------|------|
| ip1 Nginx | `0.0.0.0:9527` | 公网监听端口 |
| ip2 宿主机 | `9527` | 宿主机端口（由 `docker-compose.yml` 的 `${PORT:-8000}` 决定） |
| ip2 容器内 | `9527` | 应用服务监听端口（通过 `.env` 中 `PORT=9527` 配置） |
| ip1 → ip2 透传 | `ip2:9527` | Nginx `proxy_pass` 目标地址 |

---

## 四、Slack 消息采集配置

Slack 消息采集功能通过 Slack Web API 直接获取频道消息，存入知识库，供 AI 在生成报告和对话时参考。

### 1. 生产环境自动刷新凭证（VNC 方式）

生产环境服务器 IP 可能被 Slack 风控拦截，导致自动刷新失败。解决方案：

**前提**：服务器安全组放行 TCP 5900 端口。

**步骤**：

```bash
# 1. 服务器上安装依赖
apt-get update && apt-get install -y xvfb x11vnc chromium-browser

# 2. 启动虚拟显示器 + VNC + chromium
Xvfb :99 -screen 0 1280x720x24 &
x11vnc -display :99 -forever -listen 0.0.0.0 -rfbport 5900 &

# 设置 VNC 密码（首次执行）
x11vnc -storepasswd

# 用密码文件重启 VNC（后续执行）
kill $(pgrep x11vnc)
x11vnc -display :99 -forever -rfbauth ~/.vnc/passwd -listen 0.0.0.0 &

# 3. 启动 chromium
DISPLAY=:99 chromium-browser --no-sandbox https://vllm-dev.slack.com/sign_in_with_password &
```

**本地连接**：macOS Finder → 菜单栏「前往」→「连接服务器...」→ `vnc://190.92.220.4:5900`

在 VNC 窗口中正常登录 Slack（邮箱 → 密码 → 验证码）。登录后服务器 IP 被 Slack 信任，后续 `_refresh_credentials` 可正常工作。

**用完清理**：
```bash
kill $(pgrep -f "Xvfb|x11vnc|chromium") 2>/dev/null
apt-get purge -y x11vnc chromium-browser xvfb 2>/dev/null
```
