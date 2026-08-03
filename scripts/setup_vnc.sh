#!/bin/bash
# 在服务器上执行：安装并启动 VNC，然后启动 chromium 登录 Slack

set -e

echo "=== 1. 安装依赖 ==="
apt-get update -qq
apt-get install -y -qq xvfb x11vnc chromium-browser 2>&1 | tail -3

echo "=== 2. 启动虚拟显示器 ==="
Xvfb :99 -screen 0 1280x720x24 &
sleep 1

echo "=== 3. 启动 VNC 服务 ==="
x11vnc -display :99 -forever -nopw -listen 0.0.0.0 -rfbport 5900 &
sleep 1

echo "=== 4. 启动 chromium ==="
DISPLAY=:99 chromium-browser --no-sandbox https://vllm-dev.slack.com/sign_in_with_password &
sleep 3

echo "=== 5. 检查服务 ==="
echo "VNC: $(ps aux | grep x11vnc | grep -v grep | head -1)"
echo "Chromium: $(ps aux | grep chromium | grep -v grep | head -1)"
echo "Xvfb: $(ps aux | grep Xvfb | grep -v grep | head -1)"

echo ""
echo "===== 完成 ====="
echo "本地 macOS 打开 Finder → 菜单栏「前往」→「连接服务器...」"
echo "输入: vnc://190.92.220.4:5900"
echo "然后能看到 Slack 登录页面，登录一次即可"
echo ""
echo "安全组需要放行端口 5900（如果连不上）"
echo "用完记得关闭: kill %1 %2 %3 2>/dev/null; apt-get purge -y x11vnc chromium-browser 2>/dev/null"
