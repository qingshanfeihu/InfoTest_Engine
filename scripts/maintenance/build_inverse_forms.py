# -*- coding: utf-8 -*-
"""从 command_inventory 机械派生 create↔no/clear 配对表 → domain_grammar.inverse_forms。

§18.4 τ 推导化(审计坑#5):τ 公式 (39) 的 grounding 从 3 族坑驱动正则升级为
结构推导——3 条公理(no=否定/clear=清理/show=观测,CLI 语言元语义)+inventory
签名配对(闭合于框架手册版本)。run13 推导实验实证:1383 配置头 62% 可推逆元,
run12/13 全部主角(vlan/listener/bond/slb virtual)命中。

用法: python scripts/maintenance/build_inverse_forms.py [--version 10.5]
inventory 重建(build_command_inventory)后重跑本脚本即完成随版本更新。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def build(version: str) -> dict:
    from main.case_compiler.command_inventory import load_inventory
    inv = load_inventory(version)
    if not inv:
        raise SystemExit(f"inventory for {version} not found")
    heads = inv["heads"]
    hset = set(heads)

    def anc(prefix: str, h: str) -> str | None:
        ws = h.split()
        for k in range(len(ws), 0, -1):
            cand = f"{prefix} {' '.join(ws[:k])}"
            if cand in hset:
                return cand
        return None

    pairs: dict[str, dict] = {}
    for h in sorted(hset):
        if h.startswith(("show ", "no ", "clear ")):
            continue
        inv_no = anc("no", h)
        inv_clear = anc("clear", h)
        if inv_no or inv_clear:
            pairs[h] = {"no": inv_no, "clear": inv_clear,
                        "src": str(heads[h].get("src", ""))}
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="10.5")
    args = ap.parse_args()
    pairs = build(args.version)
    gp = ROOT / "knowledge/data/compile_ref/domain_grammar.json"
    g = json.loads(gp.read_text(encoding="utf-8"))
    g["inverse_forms"] = {
        "_provenance": (f"machine-derived from command_inventory_{args.version} "
                        f"(build_inverse_forms.py; 3 axioms: no=negation, clear=aggregate "
                        f"reset, show=observe — CLI meta-semantics, closed over manual "
                        f"version). Each pair carries the manual line anchor of its "
                        f"construct head. Regenerate after inventory rebuild. "
                        f"Derivation validated on run13 (yzg 26 sheets: all L2/L3 "
                        f"actors covered; 62% of 1383 config heads derivable)."),
        "version": args.version,
        "pairs": pairs,
    }
    gp.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"inverse_forms: {len(pairs)} pairs written for {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
