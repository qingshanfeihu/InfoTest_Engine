#!/usr/bin/env bash
# PreToolUse 守护:拒绝对密钥/凭据文件的写入(CLAUDE.md Token 安全红线)。
# 命中 environment / ssh_users.json / .env 时 exit 2 阻断,并把原因回传给模型。
# environment.example(模板,无密钥)放行。
set -euo pipefail

input=$(cat)
fp=$(printf '%s' "$input" | /usr/bin/python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)

base=$(basename "$fp" 2>/dev/null || echo "")
case "$base" in
  environment|ssh_users.json|.env|.env.*)
    echo "[guard-secrets] 拒绝修改密钥/凭据文件: $fp" >&2
    echo "该文件含 API key / SSH 凭据(见 CLAUDE.md「Token 安全」红线)。如确需改动,请人工手动编辑。" >&2
    exit 2
    ;;
esac
exit 0
