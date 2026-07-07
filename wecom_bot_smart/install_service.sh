#!/bin/bash
# 企微智能机器人 — WebSocket 长连接模式，生成 systemd 服务并设为开机自启
#
# 用法：
#   sudo bash wecom_bot_smart/install_service.sh
#
# 前提：
#   1. environment 文件已配置 WECOM_SMART_BOT_ID / WECOM_SMART_SECRET / WECOM_SMART_GATEWAY_URL
#   2. venv 已安装依赖（pip install websocket-client）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

VENV_PYTHON="/root/venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "❌ venv 不存在: $VENV_PYTHON"
    echo "   请先创建 venv：python3 -m venv venv && venv/bin/pip install websocket-client"
    exit 1
fi

SERVICE_NAME="wecom-smart-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "📝 写入 systemd 服务: $SERVICE_FILE"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=InfoTest Engine — 企微智能机器人 (WebSocket 长连接)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_ROOT}
ExecStart=${VENV_PYTHON} -m wecom_bot_smart.main
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "🔄 重载 systemd…"
systemctl daemon-reload

echo "🚀 启动并启用开机自启…"
systemctl enable "$SERVICE_NAME" --now

sleep 2

echo ""
echo "============================================"
systemctl status "$SERVICE_NAME" --no-pager
echo "============================================"
echo ""
echo "✅ 安装完成"
echo ""
echo "常用命令："
echo "  sudo systemctl status ${SERVICE_NAME}    # 查看状态"
echo "  sudo journalctl -u ${SERVICE_NAME} -f    # 实时日志"
echo "  sudo systemctl restart ${SERVICE_NAME}   # 重启"
echo "  sudo systemctl stop ${SERVICE_NAME}      # 停止"
echo "  sudo systemctl disable ${SERVICE_NAME}   # 取消开机自启"
