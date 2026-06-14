#!/usr/bin/env python
"""CLI 手册命令语法块本地重抽 — 试点验证（只读，不改 md）。

MinerU 对"命令名独占一行 + 参数另起行"的跨行语法块系统性丢参数（截断率 98.8%）。
本脚本用 pypdf 抽 PDF 文字层，按 APV 命令行手册表1-1符号约定重建完整语法行：

  命令块 = 命令名行(纯英文词，无 < [ { ) + 紧随的参数行(含 < [ { 或为其续行)
           直到遇到中文说明行(常以"该命令"开头) / 空行后的非参数行 / 表格。

参数行判定：行内出现 < > [ ] { } 之一，或为纯 ASCII 参数续行（上一行是参数行且本行无中文）。

试点：在 cli_74.pdf 上跑，对已知截断案例打印 本地重建 vs MinerU 落地 对比。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from pypdf import PdfReader  # noqa: E402

_PDF = _ROOT / "knowledge/data/orgin/cli_74.pdf"

# 命令名行：全小写英文 + 空格（含数字/连字符），无语法标记符号
_CMD_NAME = re.compile(r"^[a-z][a-z0-9 _\-]+$")
# 参数行：含 < > [ ] { } | 任一
_PARAM_LINE = re.compile(r"[<>\[\]{}|]")
# 中文说明行（语法块结束标志）
_CJK = re.compile(r"[一-鿿]")

# Unicode 排版连字 → ASCII（pypdf 抽 PDF 时 fi/fl 等会成合字符）
_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl",
    "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
}


def _delig(s: str) -> str:
    for lig, rep in _LIGATURES.items():
        s = s.replace(lig, rep)
    return s

# 已知截断案例（来自规模评估），用于试点校验
_KNOWN = [
    "monitor system memory utilization",
    "ip address",
    "aaa radius host",
    "slb real sipudp",
    "show route match",
    "http redirect url",
]


def _is_param_continuation(line: str) -> bool:
    """参数续行：无中文，且含语法符号 < > [ ] { } | 。

    严格要求含语法符号——裸 ASCII 行（如目录里的命令名列表 ``ip route`` ``ssh`` 等）
    不算参数续行，避免把相邻命令名误吞进当前命令的参数。
    """
    s = line.strip()
    if not s or _CJK.search(s):
        return False
    return bool(_PARAM_LINE.search(s))


def reconstruct_blocks(pages_text: list[str]) -> dict[str, str]:
    """扫所有页，重建 {命令名: 完整语法行}。后出现的覆盖（取定义处通常最完整）。"""
    blocks: dict[str, str] = {}
    for text in pages_text:
        lines = [ln.rstrip() for ln in text.splitlines()]
        i = 0
        while i < len(lines):
            name = lines[i].strip()
            if _CMD_NAME.match(name) and 2 <= len(name) <= 60:
                # 向下找参数行（跳过紧随的空行）
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                params: list[str] = []
                k = j
                while k < len(lines) and _is_param_continuation(lines[k]):
                    params.append(lines[k].strip())
                    k += 1
                if params:
                    full = name + " " + " ".join(params)
                    # 归一空格 + 去连字
                    full = _delig(re.sub(r"\s+", " ", full).strip())
                    blocks[name] = full
                    i = k
                    continue
            i += 1
    return blocks


def _norm(s: str) -> str:
    """归一：\\_ → _，压空格，去首尾。"""
    return re.sub(r"\s+", " ", s.replace("\\_", "_")).strip()


def main() -> int:
    reader = PdfReader(str(_PDF))
    pages_text = [(pg.extract_text() or "") for pg in reader.pages]
    print(f"cli_74.pdf 页数: {len(pages_text)}")

    blocks = reconstruct_blocks(pages_text)
    print(f"本地重建命令语法块: {len(blocks)} 个\n")

    # 加载 MinerU md（3 卷拼一起）
    md_dir = _ROOT / "knowledge/data/markdown/product"
    md_text = ""
    for part in ["cli_74__part1_p1-200.md", "cli_74__part2_p201-400.md",
                 "cli_74__part3_p401-525.md"]:
        p = md_dir / part
        if p.exists():
            md_text += p.read_text(encoding="utf-8") + "\n"
    md_lines = [_norm(ln) for ln in md_text.splitlines()]

    print("=== 已知截断案例：本地重建 vs MinerU 落地 ===\n")
    for cmd in _KNOWN:
        local = blocks.get(cmd)
        # 在 md 里找以该命令名开头的行
        md_hits = [ln for ln in md_lines if ln.startswith(cmd) and "no " not in ln[:4]]
        print(f"命令: {cmd}")
        print(f"  本地重建 : {local}")
        print(f"  MinerU md: {md_hits[0] if md_hits else '(未找到)'}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
