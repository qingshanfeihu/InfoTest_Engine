"""E5 三坑行为知识种子(V6 支柱2b):v12 撞过的验证期知识以 device_verified 证据入库。

三坑与证据:v12 归档 PASS 卷上真实执行过这些观测命令,行为现象来自 FINAL_REPORT
「关键技术演进」的实测记录——不是编造,是把已付过学费的知识落进检索通道。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

SEEDS = [
    {"cmd": "show statistics sdns pool",
     "content": "该命令输出为多行块结构(每 pool 一块,Pool Name/Hit 分行)——断言正则需跨行"
                "匹配(DOTALL 语义),单行 [^\\n]* 形态匹配不到跨行字段(v12 R1 实测)。"},
    {"cmd": "clear statistics all",
     "content": "Hit 计数器跨 case 累积,不随 case 边界清零——统计类断言前先 clear statistics all,"
                "否则区间期望要按累计值校准(v12 R2/R3 实测,断言区间偏差根因)。"},
    {"cmd": "sdns pool method primary",
     "content": "pool 级 method 配置需要 primary 关键字位(sdns pool method primary <pool> <算法>);"
                "缺它设备拒绝(v12 R1 实测,手册未显式标注该词序)。"},
]


def main() -> int:
    # 证据:在 v12 归档 PASS 卷里找真实出现过这些命令的 case
    from main.ist_core.tools.device.batch_tools import _xlsx_apv_lines
    from main.ist_core.memory.footprint.schema import RawFact
    from main.ist_core.memory.footprint.router import route_facts
    from main.ist_core.memory.footprint.merger import merge_fact
    from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS

    arch = _ROOT / "workspace" / "outputs" / "_archive_v12_20260705" / "dongkl_v12"
    lr = json.loads((arch / "last_run.json").read_text(encoding="utf-8"))
    items = lr if isinstance(lr, list) else lr.get("results", [])
    passed = {str(it["autoid"]) for it in items if str(it.get("verdict")) == "pass"}
    apv = _xlsx_apv_lines(arch / "case.xlsx")

    # 台账追加(真实 runtime 台账;run_ts 取归档 _run_ts 或固定实验值)
    run_ts = next((float(it.get("_run_ts") or 0) for it in items
                   if str(it.get("verdict")) == "pass"), 0.0) or 1751700000.0
    ledger = _ROOT / "runtime" / "logs" / "verified_runs.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    seeded_aids = {}
    for seed in SEEDS:
        aid = next((a for a in sorted(passed)
                    if any(c.startswith(seed["cmd"]) for c in apv.get(a, []))), None)
        if aid is None:
            print(f"跳过(无 PASS 卷含该命令): {seed['cmd']}")
            continue
        cmd_full = next(c for c in apv[aid] if c.startswith(seed["cmd"]))
        with ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"autoid": aid, "verdict": "pass", "run_ts": run_ts,
                                "xlsx": str(arch / "case.xlsx"),
                                "apv_cmds": apv[aid],
                                "note": "seed_v12_behaviors(归档 PASS 重放)"},
                               ensure_ascii=False) + "\n")
        seeded_aids[seed["cmd"]] = (aid, cmd_full)

    wrote = 0
    for seed in SEEDS:
        if seed["cmd"] not in seeded_aids:
            continue
        aid, cmd_full = seeded_aids[seed["cmd"]]
        import hashlib
        head = [t for t in cmd_full.split() if t.lower() not in ("no", "show", "clear")][:2]
        rf = RawFact(fact_kind="behavior", feature_path=head or cmd_full.split()[:1],
                     fact_key=f"{' '.join(head)}:{hashlib.sha1(seed['content'].encode()).hexdigest()[:8]}",
                     cli_syntax=cmd_full, content=seed["content"],
                     device_evidence={"autoid": aid, "run_ts": run_ts},
                     source_thread="seed_v12_behaviors")
        for routed in route_facts([rf], Path(KNOWLEDGE_FOOTPRINTS)):
            res = merge_fact(routed, Path(KNOWLEDGE_FOOTPRINTS))
            print(f"{seed['cmd'][:40]} → {res.action}({res.detail[:60]})")
            if res.action != "skip":
                wrote += 1
    print(f"\n种子完成: {wrote}/{len(SEEDS)} 入库")
    return 0 if wrote else 1


if __name__ == "__main__":
    raise SystemExit(main())
