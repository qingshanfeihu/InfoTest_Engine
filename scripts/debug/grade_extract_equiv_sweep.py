"""grade_extract 等价性反扫（P2 三层重构验收工具，2026-07-08）。

对全仓卷（mirror 金标准 + workspace + archive 的 *.xlsx）跑 `extract()`，结果落
JSONL；两份结果逐卷 diff（`*_note` 字段忽略——P2-3 判例化允许文案差异）。
重构 grade_extract / domain_grammar 词面时用它证明「事实输出逐比特一致」——
强字典误杀金标准（GA-CUT 回归）这类回归在 511 卷上无处可藏。

用法：
    python -m scripts.debug.grade_extract_equiv_sweep sweep <out.jsonl>
    python -m scripts.debug.grade_extract_equiv_sweep diff <baseline.jsonl> <after.jsonl>

验收流程：改动前 sweep 存 baseline → 改代码/数据 → sweep 存 after → diff 必须
「PASS 全部等价」（P2 首轮验收：511 卷 0 差异）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from main.knowledge_paths import PROJECT_ROOT
from main.ist_core.tools.device.grade_extract_script import extract

_SCAN_BASES = ("knowledge/framework/mirror", "workspace", "archive")


def _volumes():
    seen: set[Path] = set()
    for base in _SCAN_BASES:
        d = PROJECT_ROOT / base
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.xlsx")):
            if p.name.startswith("~$") or p in seen:
                continue
            seen.add(p)
            yield p


def sweep(out_path: str) -> None:
    n_ok = n_err = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for p in _volumes():
            rel = str(p.relative_to(PROJECT_ROOT))
            prov = p.parent / "case.provenance.json"
            try:
                res = extract(str(p), str(prov) if prov.is_file() else "-")
                fh.write(json.dumps({"xlsx": rel, "result": res},
                                    ensure_ascii=False, sort_keys=True) + "\n")
                n_ok += 1
            except Exception as exc:  # noqa: BLE001 — 单卷坏不该断反扫,记录后继续
                fh.write(json.dumps({"xlsx": rel, "error": f"{type(exc).__name__}: {exc}"},
                                    ensure_ascii=False) + "\n")
                n_err += 1
    print(f"ok={n_ok} err={n_err} -> {out_path}")


def _strip_notes(obj):
    # *_note 与 suspect_reason 是自由文案通道(判例化/语言分层允许演化),事实字段才比对
    if isinstance(obj, dict):
        return {k: _strip_notes(v) for k, v in obj.items()
                if not (k.endswith("_note") or k == "suspect_reason")}
    if isinstance(obj, list):
        return [_strip_notes(x) for x in obj]
    return obj


def _load(path: str) -> dict:
    out = {}
    for line in open(path, encoding="utf-8"):
        rec = json.loads(line)
        out[rec["xlsx"]] = _strip_notes(rec.get("result", {"__error__": rec.get("error")}))
    return out


def diff(base_path: str, after_path: str) -> int:
    a, b = _load(base_path), _load(after_path)
    common = set(a) & set(b)
    only_a, only_b = set(a) - common, set(b) - common
    if only_a or only_b:
        # 卷集漂移(运行批新增/清理产生)不算回归——交集比对,差集如实报告
        print(f"卷集漂移: baseline 独有 {len(only_a)}, 新扫独有 {len(only_b)}(交集 {len(common)} 卷参与比对)")
    n_diff = 0
    for k in sorted(common):
        if a[k] != b[k]:
            n_diff += 1
            if n_diff <= 5:
                for f in sorted(set(list(a[k]) + list(b[k]))):
                    if a[k].get(f) != b[k].get(f):
                        print(f"DIFF {k} :: {f}\n"
                              f"  base={json.dumps(a[k].get(f), ensure_ascii=False)[:300]}\n"
                              f"  new ={json.dumps(b[k].get(f), ensure_ascii=False)[:300]}")
    print(f"{'PASS 全部等价' if n_diff == 0 else 'FAIL'}: {len(common)} 卷比对, {n_diff} 卷有差异")
    return 0 if n_diff == 0 else 1


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "sweep":
        sweep(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "diff":
        sys.exit(diff(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
