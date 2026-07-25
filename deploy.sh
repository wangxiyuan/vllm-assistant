#!/bin/bash
# ============================================================================
# vLLM Assistant — 一键 Docker 部署脚本
# ============================================================================
# 功能：
#   1. 检查 Docker / Docker Compose 是否安装
#   2. 检查 .env 配置文件，缺失则从 .env.example 创建
#   3. 引导用户填写必要的环境变量
#   4. 检测代码变更，自动触发重建
#   5. 优雅替换旧容器，保持数据持久化
# ============================================================================
#
# 用法：
#   ./deploy.sh         部署或重新部署（更新代码后执行）
#   ./deploy.sh stop    停止容器
#   ./deploy.sh restart 重启容器
#   ./deploy.sh logs    查看日志
# ============================================================================
#
# 反复部署说明：
#   - 支持反复执行，第二次及以后会自动检测代码变更
#   - SQLite 数据库和代码仓库通过 Docker 命名卷持久化，不会丢失
#   - 代码变更后执行 ./deploy.sh 即可自动重建镜像并重启容器
#
# 更新代码后部署：
#   git pull
#   ./deploy.sh
# ============================================================================

set -e

# ============================================================================
# 子命令处理（stop / restart / logs / 默认部署）
# ============================================================================
ACTION="${1:-deploy}"

# ============================================================================
# 颜色定义
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ============================================================================
# 辅助函数
# ============================================================================
print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
print_error()   { echo -e "${RED}[✗]${NC} $1"; }
print_step()    { echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

# ============================================================================
# 前置检查
# ============================================================================
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║        vLLM Assistant — Docker               ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# 检查 Docker
print_step "检查运行环境"
if ! command -v docker &> /dev/null; then
    print_error "未找到 docker，请先安装 Docker："
    echo "  macOS:   https://docs.docker.com/desktop/install/mac-install/"
    echo "  Linux:   curl -fsSL https://get.docker.com | sh"
    exit 1
fi
print_success "Docker: $(docker --version)"

# 检查 Docker Compose（v2 插件或 v1 命令）
DOCKER_COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
    print_success "Docker Compose: $(docker compose version)"
elif docker-compose --version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
    print_success "Docker Compose: $(docker-compose --version)"
else
    print_error "未找到 docker compose 或 docker-compose"
    exit 1
fi

# ============================================================================
# 子命令分发
# ============================================================================
case "$ACTION" in
    stop)
        print_step "停止服务"
        $DOCKER_COMPOSE_CMD down --remove-orphans
        print_success "服务已停止"
        exit 0
        ;;
    restart)
        print_step "重启服务"
        $DOCKER_COMPOSE_CMD restart
        print_success "服务已重启"
        exit 0
        ;;
    logs)
        print_step "查看日志"
        $DOCKER_COMPOSE_CMD logs -f
        exit $?
        ;;
    deploy)
        # 继续执行部署流程
        ;;
    *)
        print_error "未知命令: $ACTION"
        echo "用法: ./deploy.sh [stop|restart|logs|deploy]"
        echo "  无参数 = deploy"
        exit 1
        ;;
esac

# ============================================================================
# .env 配置检查与引导
# ============================================================================
print_step "检查配置文件"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f ".env" ]; then
    print_warning "未找到 .env 文件"

    if [ -f ".env.example" ]; then
        echo ""
        echo "是否从 .env.example 创建 .env 文件？[Y/n]"
        read -r answer
        if [[ "$answer" =~ ^[Nn]$ ]]; then
            print_error "请手动创建 .env 文件后再运行此脚本"
            echo "  cp .env.example .env"
            echo "  然后编辑 .env 填入配置"
            exit 1
        fi
        cp .env.example .env
        print_success ".env 文件已从 .env.example 创建"
    else
        print_error "未找到 .env.example 文件，请手动创建 .env"
        exit 1
    fi
else
    print_success ".env 文件已存在"
fi

# 检查必填配置项
print_step "验证必要配置"

NEED_CONFIG=0

# 检查 VLLM_ASSISTANT_PAT
if grep -q "^VLLM_ASSISTANT_PAT=github_pat_your_token_here" .env 2>/dev/null || \
   grep -q "^VLLM_ASSISTANT_PAT=$" .env 2>/dev/null || \
   ! grep -q "^VLLM_ASSISTANT_PAT=" .env 2>/dev/null; then
    print_warning "VLLM_ASSISTANT_PAT 未配置（GitHub Personal Access Token）"
    echo "  请访问 https://github.com/settings/tokens 创建 PAT"
    echo "  需要权限: repo (全部), read:org"
    echo ""
    echo "  请输入你的 GitHub PAT（输入后回车）:"
    read -r github_pat
    if [ -n "$github_pat" ]; then
        # 替换或追加 PAT
        if grep -q "^VLLM_ASSISTANT_PAT=" .env; then
            # macOS 兼容: sed -i 需要 '' 参数
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s|^VLLM_ASSISTANT_PAT=.*|VLLM_ASSISTANT_PAT=$github_pat|" .env
            else
                sed -i "s|^VLLM_ASSISTANT_PAT=.*|VLLM_ASSISTANT_PAT=$github_pat|" .env
            fi
        else
            echo "VLLM_ASSISTANT_PAT=$github_pat" >> .env
        fi
        print_success "VLLM_ASSISTANT_PAT 已配置"
    else
        print_error "VLLM_ASSISTANT_PAT 未填写，服务启动后大部分 API 将不可用"
        NEED_CONFIG=1
    fi
fi

# 检查 GITHUB_USERNAME
if grep -q "^GITHUB_USERNAME=your_github_username" .env 2>/dev/null || \
   ! grep -q "^GITHUB_USERNAME=" .env 2>/dev/null; then
    print_warning "GITHUB_USERNAME 未配置（用于 PR 指挥中心功能）"
    echo "  请输入你的 GitHub 用户名（输入后回车，留空跳过）:"
    read -r github_username
    if [ -n "$github_username" ]; then
        if grep -q "^GITHUB_USERNAME=" .env; then
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s|^GITHUB_USERNAME=.*|GITHUB_USERNAME=$github_username|" .env
            else
                sed -i "s|^GITHUB_USERNAME=.*|GITHUB_USERNAME=$github_username|" .env
            fi
        else
            echo "GITHUB_USERNAME=$github_username" >> .env
        fi
        print_success "GITHUB_USERNAME 已配置"
    else
        print_warning "GITHUB_USERNAME 未填写，PR 指挥中心功能将受限"
    fi
fi

# 可选：询问是否配置 REPOS（仅在首次部署时提示）
if ! grep -q "^REPOS=" .env 2>/dev/null || grep -q "^REPOS=$" .env 2>/dev/null; then
    echo ""
    print_info "是否配置代码仓库列表？（用于代码浏览器/学习文章功能）[y/N]"
    read -r config_repos
    if [[ "$config_repos" =~ ^[Yy]$ ]]; then
        echo "  请输入仓库配置（格式: name=url，多个用逗号分隔）"
        echo "  示例: vllm=https://github.com/vllm-project/vllm.git"
        echo "  输入:"
        read -r repos_value
        if [ -n "$repos_value" ]; then
            if grep -q "^REPOS=" .env; then
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    sed -i '' "s|^REPOS=.*|REPOS=$repos_value|" .env
                else
                    sed -i "s|^REPOS=.*|REPOS=$repos_value|" .env
                fi
            else
                echo "REPOS=$repos_value" >> .env
            fi
            print_success "REPOS 已配置"
        fi
    fi
fi

if [ $NEED_CONFIG -eq 1 ]; then
    echo ""
    print_warning "部分必要配置未填写，请编辑 .env 文件补全后重新运行"
    echo "  vi .env"
    exit 1
fi

# ============================================================================
# 检测当前部署状态，决定是否重建
# ============================================================================
print_step "检测部署状态"

CONTAINER_EXISTS=false
CONTAINER_RUNNING=false

if docker ps -a --format '{{.Names}}' | grep -q "^vllm-assistant$"; then
    CONTAINER_EXISTS=true
    if docker ps --format '{{.Names}}' | grep -q "^vllm-assistant$"; then
        CONTAINER_RUNNING=true
        print_info "检测到正在运行的容器 vllm-assistant"
    else
        print_info "检测到已停止的容器 vllm-assistant"
    fi
else
    print_info "首次部署，未检测到现有容器"
fi

# ============================================================================
# 检测代码是否变更（基于 git 或文件哈希）
# ============================================================================
NEED_REBUILD=false
BUILD_CACHE_FILE=".deploy_build_hash"

# 计算当前代码的哈希值（检测 app/ static/ requirements.txt Dockerfile 的变更）
compute_code_hash() {
    # 如果 git 可用，用 git 的 HEAD 哈希
    if git rev-parse --git-dir > /dev/null 2>&1; then
        git log -1 --format=%H -- app/ static/ requirements.txt Dockerfile docker-compose.yml 2>/dev/null || \
        git rev-parse HEAD 2>/dev/null
    else
        # 否则用文件内容的 md5
        find app/ static/ -type f -name "*.py" -o -name "*.html" -o -name "*.js" -o -name "*.css" 2>/dev/null | \
            sort | xargs md5 -r 2>/dev/null | md5 -r | awk '{print $1}'
    fi
}

# 检查是否有代码变更
if [ "$CONTAINER_EXISTS" = true ]; then
    CURRENT_HASH=$(compute_code_hash)
    PREVIOUS_HASH=""
    [ -f "$BUILD_CACHE_FILE" ] && PREVIOUS_HASH=$(cat "$BUILD_CACHE_FILE")

    if [ "$CURRENT_HASH" != "$PREVIOUS_HASH" ]; then
        print_warning "检测到代码变更，需要重新构建镜像"
        NEED_REBUILD=true
    else
        print_success "代码未变更，使用现有镜像"
    fi
else
    NEED_REBUILD=true
fi

# ============================================================================
# 构建镜像（仅在需要时）
# ============================================================================
if [ "$NEED_REBUILD" = true ]; then
    print_step "构建 Docker 镜像"
    echo "  镜像名: vllm-assistant:latest"
    echo "  构建上下文: $(pwd)"
    echo ""

    $DOCKER_COMPOSE_CMD build

    # 保存构建哈希
    compute_code_hash > "$BUILD_CACHE_FILE"
    print_success "镜像构建完成"
else
    # 即使代码没变，也检查镜像是否存在，不存在则构建
    if ! docker images vllm-assistant:latest | grep -q "vllm-assistant"; then
        print_warning "未找到镜像，执行首次构建"
        print_step "构建 Docker 镜像"
        $DOCKER_COMPOSE_CMD build
        compute_code_hash > "$BUILD_CACHE_FILE"
        print_success "镜像构建完成"
    fi
fi

# ============================================================================
# 停止并删除旧容器
# ============================================================================
print_step "启动服务"

if [ "$CONTAINER_RUNNING" = true ]; then
    print_info "停止旧容器..."
    $DOCKER_COMPOSE_CMD down --remove-orphans
    print_success "旧容器已停止并移除"
elif [ "$CONTAINER_EXISTS" = true ]; then
    print_info "移除已停止的旧容器..."
    $DOCKER_COMPOSE_CMD down --remove-orphans
fi

# ============================================================================
# 启动新容器
# ============================================================================
print_info "启动新容器..."
$DOCKER_COMPOSE_CMD up -d

# ============================================================================
# 等待服务就绪
# ============================================================================
echo ""
print_info "等待服务就绪..."

MAX_RETRIES=30
RETRY_COUNT=0
SERVICE_READY=false

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -sf http://localhost:${PORT:-8000}/health > /dev/null 2>&1; then
        SERVICE_READY=true
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 2
done

echo ""

if [ "$SERVICE_READY" = true ]; then
    print_success "vLLM Assistant 部署成功！"
    echo ""
    echo -e "  ${GREEN}访问地址:${NC}      http://localhost:${PORT:-8000}"
    echo -e "  ${GREEN}API 文档:${NC}      http://localhost:${PORT:-8000}/docs"
    echo -e "  ${GREEN}健康检查:${NC}      http://localhost:${PORT:-8000}/health"
    echo ""
    print_info "查看容器日志："
    echo "  $DOCKER_COMPOSE_CMD logs -f"
    echo ""
    print_info "停止服务："
    echo "  $DOCKER_COMPOSE_CMD down"
    echo ""
    print_info "重启服务："
    echo "  $DOCKER_COMPOSE_CMD restart"
    echo ""
    print_info "更新服务（拉取最新代码后）："
    echo "  git pull && ./deploy.sh"
    echo ""
    print_info "数据持久化说明："
    echo "  - SQLite 数据库：位于命名卷 vllm-assistant-data，容器重建后数据不丢失"
    echo "  - 代码仓库缓存：位于命名卷 vllm-assistant-repos-cache，重建后无需重新 clone"
    echo "  - 如需备份数据库："
    echo "      docker run --rm -v vllm-assistant-data:/data -v $(pwd):/backup alpine cp /data/vllm_assistant.db /backup/"
else
    print_warning "服务启动中，但健康检查尚未通过"
    print_info "请检查日志："
    echo "  $DOCKER_COMPOSE_CMD logs -f"
    echo ""
    print_info "手动检查健康状态："
    echo "  curl http://localhost:${PORT:-8000}/health"
fi

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""