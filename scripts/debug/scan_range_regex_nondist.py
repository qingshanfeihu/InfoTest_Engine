#!/usr/bin/env python3
"""回归#1/S1 eval 反扫:非分布上下文里手写 range 正则(`[d-d]`)断言的计数。

背景(docs/forensics/regression_1_S1_overgeneralization.md):区间/范围正则只该绑
分布采样命中计数(h-in-λ)。容量/存在性/枚举类(无 h 确定性,如满配 N 条 listener)
用假设布局的范围正则会与设备实际 show 格式对不齐(667986 实证 broken)。

用法(仓库外 venv):
  ~/.venvs/infotest-engine/bin/python scripts/debug/scan_range_regex_nondist.py [outputs_glob]

判据:基线(收紧 worker 指引前)= 非分布上下文 1/8(667986);worker 指引收紧 + 重编后
应 = 0。这是 before/after 测量工具,不是 pass/fail 门(存量卷不会自动重编)。
"""
from __future__ import annotations

import glob
import os
import re
import sys

import openpyxl

RANGE_RE = re.compile(r"\[\d-\d\]")               # 数字字符类范围 = 手写区间/范围正则特征
DIST_METHODS = ("rr", "wrr", "grr", "gwrr")       # 分布类算法(domain_grammar.json)


def scan(glob_pat: str) -> tuple[int, int, list]:
    total = nondist = 0
    examples: list[tuple[str, bool, str]] = []
    for f in glob.glob(glob_pat, recursive=True):
        try:
            ws = openpyxl.load_workbook(f, data_only=True).active
        except Exception:  # noqa: BLE001
            continue
        cells = [str(v) for row in ws.iter_rows(min_row=2, values_only=True)
                 for v in row if v]
        blob = " ".join(cells).lower()
        is_dist = any(re.search(rf"\b{m}\b", blob) for m in DIST_METHODS)
        # 短单元格里的范围正则 = 断言正则(排除表头那段几千字符的函数签名说明)
        hits = [c for c in cells if RANGE_RE.search(c) and len(c) < 80]
        if hits:
            total += 1
            if not is_dist:
                nondist += 1
                examples.append((os.path.basename(os.path.dirname(f)), is_dist, hits[0][:60]))
    return total, nondist, examples


def main() -> int:
    pat = sys.argv[1] if len(sys.argv) > 1 else "workspace/outputs/**/case.xlsx"
    total, nondist, examples = scan(pat)
    print(f"含 [d-d] 范围正则的 case.xlsx: {total}; 其中**非分布上下文**: {nondist}")
    for d, isd, g in examples:
        print(f"  非分布: {d}  regex={g}")
    print("\n判据:非分布上下文应为 0(收紧后重编);>0 = 手写范围正则套到无 h 枚举/容量案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
