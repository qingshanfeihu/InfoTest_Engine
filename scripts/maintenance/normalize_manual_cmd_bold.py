"""归一化已转换手册 .md 的命令签名加粗（补 adoc_to_md 旧版 sdns 偏置遗留）。

背景：早期 ``adoc_to_md._bold()`` 只把 sdns/config/slb/ha 前缀命令转成 ``**粗体**``，
其余命令留成单星 ``*斜体*``，导致 footprint 切片器（``_is_signature`` 认 ``**`` / 行首小写）
漏掉绝大多数命令。``adoc_to_md._bold()`` 已通用化；本脚本对**已生成、无 adoc 源可重转**的
``manual_10.5/*.md`` 就地补做命令签名加粗（复用同一 ``_bold_leading_command``，幂等）。

用法：
    python -m scripts.maintenance.normalize_manual_cmd_bold --glob 'cli_10.5_*.md'           # 默认仅 cli
    python -m scripts.maintenance.normalize_manual_cmd_bold --glob '*.md' --dry-run          # 全量预览
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.adoc_to_md import _bold_leading_command  # noqa: E402

MANUAL_DIR = ROOT / "knowledge/data/markdown/product/manual_10.5"


def _clean_line(ln: str) -> str:
    """命令签名加粗 + 清 adoc 转义残留 `\\{`→`{`(与 adoc_to_md 对齐;污染命令主体解析)。"""
    return re.sub(r"\\([{}\[\]])", r"\1", _bold_leading_command(ln))


def normalize_file(md: Path, *, dry_run: bool) -> int:
    """对一个 .md 逐行补命令签名加粗 + 清转义；返回改动行数。"""
    text = md.read_text(encoding="utf-8")
    lines = text.split("\n")
    fixed = [_clean_line(ln) for ln in lines]
    changed = sum(1 for a, b in zip(lines, fixed) if a != b)
    if changed and not dry_run:
        md.write_text("\n".join(fixed), encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="归一化手册命令签名加粗")
    ap.add_argument("--glob", default="cli_10.5_*.md", help="manual_10.5 下文件 glob（默认仅 cli）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写回")
    args = ap.parse_args(argv)

    files = sorted(MANUAL_DIR.glob(args.glob))
    if not files:
        print(f"无匹配文件: {MANUAL_DIR}/{args.glob}")
        return 1

    total = 0
    for md in files:
        changed = normalize_file(md, dry_run=args.dry_run)
        total += changed
        if changed:
            print(f"{'[dry]' if args.dry_run else '[fix]'} {md.name}: {changed} 行")
    print(f"\n合计改动 {total} 行 / {len(files)} 文件{'（dry-run 未写回）' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
