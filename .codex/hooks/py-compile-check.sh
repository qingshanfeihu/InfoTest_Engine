#!/usr/bin/env bash
# PostToolUse 快检:对刚编辑/写入的 .py 跑 py_compile(毫秒级),抓语法/缩进破坏。
# 失败时 exit 2 把错误回传给模型(全量 pytest 在云盘上太慢,不适合做 hook)。
set -euo pipefail

input=$(cat)
fp=$(printf '%s' "$input" | /usr/bin/python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
except Exception:
    print(""); sys.exit(0)
print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)

case "$fp" in
  *.py) : ;;
  *) exit 0 ;;
esac

[ -f "$fp" ] || exit 0

PYBIN="$HOME/.venvs/infotest-engine/bin/python"
if [ ! -x "$PYBIN" ]; then
  PYBIN="/usr/bin/python3"
fi
if [ ! -x "$PYBIN" ]; then
  echo "[py_compile] 找不到可用的 Python 解释器(试过 \$HOME/.venvs/infotest-engine/bin/python 与 /usr/bin/python3)" >&2
  exit 2
fi

if ! err=$("$PYBIN" -m py_compile "$fp" 2>&1); then
  echo "[py_compile] 语法检查失败: $fp" >&2
  echo "$err" >&2
  exit 2
fi
exit 0
