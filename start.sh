#!/bin/bash
# vLLM Assistant 启动脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查是否在项目目录
if [ ! -f "requirements.txt" ]; then
    print_error "请在项目根目录运行此脚本"
    exit 1
fi

print_info "============================================"
print_info "vLLM Assistant - 贡献者效率工具"
print_info "============================================"
echo ""

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    print_error "未找到python3，请先安装Python 3.8+"
    exit 1
fi

print_info "Python版本: $(python3 --version)"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    print_info "创建虚拟环境..."
    python3 -m venv .venv
    source .venv/bin/activate
    print_success "虚拟环境创建成功"
else
    print_info "激活虚拟环境..."
    source .venv/bin/activate
fi

# 检查依赖
print_info "检查依赖..."
pip install -q -r requirements.txt

# 验证所有依赖是否已安装（用临时文件传递缺失列表，避免 subshell 变量为空）
python3 -c "
import pkg_resources, sys
with open('requirements.txt') as f:
    reqs = [line.strip() for line in f if line.strip() and not line.startswith('#')]
missing = []
for req in reqs:
    try:
        pkg_resources.require(req)
    except (pkg_resources.DistributionNotFound, pkg_resources.VersionConflict):
        missing.append(req)
if missing:
    print(' '.join(missing))
    sys.exit(0)
else:
    sys.exit(1)
" 2>/dev/null && {
    print_warning "检测到未安装的依赖，尝试重新安装..."
    pip install -U -r requirements.txt
    print_success "缺失依赖已安装"
}
print_success "依赖检查完成"

# 检查环境变量文件
if [ ! -f ".env" ]; then
    print_warning "未找到.env文件，从.env.example复制..."
    cp .env.example .env
    print_error "请编辑.env文件，填入你的配置："
    echo "  - VLLM_ASSISTANT_PAT (GitHub PAT)"
    echo "  - OPENAI_API_KEY (OpenAI API Key)"
    echo ""
    echo "配置文件位置: .env"
    exit 1
fi

# 加载环境变量（安全方式：使用 set -a 自动导出所有变量，支持含空格的值）
set -a
source .env
set +a

# 清理旧进程
old_pids=$(lsof -ti:${PORT:-8000} 2>/dev/null) || true
if [ -n "$old_pids" ]; then
    print_info "检测到端口 ${PORT:-8000} 已被占用，停止旧进程..."
    # 先发 SIGTERM，等待后强制退出
    for pid in $old_pids; do
        kill "$pid" 2>/dev/null || true
    done
    sleep 2
    for pid in $old_pids; do
        kill -9 "$pid" 2>/dev/null || true
    done
    print_success "旧进程已停止"
fi

# 验证必要配置
if [ -z "$VLLM_ASSISTANT_PAT" ]; then
    print_error "VLLM_ASSISTANT_PAT未配置，请编辑.env文件"
    exit 1
fi

print_success "配置验证通过"
echo ""

# 构建前端（Vue 3 SPA）
print_info "构建前端..."
cd frontend
print_info "安装前端依赖..."
npm install
npm run build && {
    print_success "前端构建成功"
} || {
    print_warning "前端构建失败，请检查 frontend/ 目录"
    print_warning "新前端（Vue 3 SPA）不可用，将仅运行后端"
}
cd ..

# 启动服务
print_info "启动vLLM Assistant..."
print_info "访问地址: http://localhost:${PORT:-8000}"
print_info "API文档: http://localhost:${PORT:-8000}/docs"
echo ""

python3 -m app.main