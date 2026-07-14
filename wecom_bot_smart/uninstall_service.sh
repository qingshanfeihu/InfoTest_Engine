#!/bin/bash
# 停止并删除企微智能机器人 systemd 服务
#
# 用法：
#   sudo bash wecom_bot_smart/uninstall_service.sh

set -euo pipefail

SERVICE_NAME="wecom-smart-bot"

echo "⏹ 停止服务…"
systemctl stop "$SERVICE_NAME" 2>/dev/null || true

echo "🚫 禁用开机自启…"
systemctl disable "$SERVICE_NAME" 2>/dev/null || true

echo "🗑 删除服务文件…"
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"

echo "🔄 重载 systemd…"
systemctl daemon-reload

echo "✅ 已卸载"
