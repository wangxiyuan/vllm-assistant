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
print_success "依赖检查完成"

# 检查环境变量文件
if [ ! -f ".env" ]; then
    print_warning "未找到.env文件，从.env.example复制..."
    cp .env.example .env
    print_error "请编辑.env文件，填入你的配置："
    echo "  - VLLM_ASSISTANT_PAT (GitHub PAT)"
    echo "  - OPENAI_API_KEY (OpenAI API Key)"
    echo "  - GITHUB_USERNAME (你的GitHub用户名)"
    echo ""
    echo "配置文件位置: .env"
    exit 1
fi

# 加载环境变量
export $(grep -v '^#' .env | xargs)

# 验证必要配置
if [ -z "$VLLM_ASSISTANT_PAT" ]; then
    print_error "VLLM_ASSISTANT_PAT未配置，请编辑.env文件"
    exit 1
fi

if [ -z "$GITHUB_USERNAME" ]; then
    print_warning "GITHUB_USERNAME未配置，某些功能可能无法使用"
fi

print_success "配置验证通过"
echo ""

# 启动服务
print_info "启动vLLM Assistant..."
print_info "访问地址: http://localhost:${PORT:-8000}"
print_info "API文档: http://localhost:${PORT:-8000}/docs"
echo ""

python -m app.main