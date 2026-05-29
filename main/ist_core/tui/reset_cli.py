"""``infotest reset`` CLI 入口。

用法::

    infotest reset            # 显示待清理列表 → 确认 → 执行
    infotest reset --yes      # 跳过确认（脚本/CI 用）
    infotest reset --all      # 同时清理长期记忆
    infotest reset --all -y   # 全清且不问
"""
from __future__ import annotations

import argparse
import sys


def run_reset_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="infotest reset",
        description="清除对话历史和 agent 临时存储文件。",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="同时清理长期记忆 (memory/long_term/)",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="跳过确认提示（脚本/CI 用）",
    )
    args = parser.parse_args(argv)

    from main.ist_core.tui.reset_command import perform_reset, preview_reset

    preview = preview_reset(include_long_term=args.all)
    if preview == "无可清理内容。":
        print(preview)
        return 0

    print(preview)

    if not args.yes:
        print()
        try:
            answer = input("确认清理? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return 1
        if answer not in ("y", "yes"):
            print("已取消。")
            return 1

    print()
    result = perform_reset(include_long_term=args.all)
    print(result.summary())
    return 0 if result.success else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run_reset_command(sys.argv[1:]))
