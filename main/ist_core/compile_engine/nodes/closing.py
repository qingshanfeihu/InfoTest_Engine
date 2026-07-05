"""收尾节点:writeback([mech])→ report([mech])。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from main.ist_core.compile_engine import ledger as L
from main.ist_core.compile_engine.nodes import _shared as sh


# ------------------------------------------------------------- [mech] writeback
def writeback(state: dict) -> dict:
    """真 PASS 双写回:先例库(compile_writeback)+ footprint G 段(device_verified
    第二权威源自动挂,支柱2a)。失败只记不阻断。"""
    led = sh.load_ledger(state)
    passed = led.in_state(L.S_PASSED)
    if not passed:
        return {"phase_status": "nothing_to_do", **sh.counts_update(led)}
    lr_ref = str(state.get("last_run_ref") or "")
    wrote = 0
    for aid in passed:
        try:
            from main.ist_core.tools.device.precedent_tools import compile_writeback
            compile_writeback.func(autoid=aid, last_run_path=lr_ref)
        except Exception:  # noqa: BLE001
            led.data["audit"]["notes"].append({"autoid": aid, "event": "precedent_writeback_fail"})
        try:
            from main.ist_core.tools.knowledge.footprint_writeback import compile_footprint_writeback
            pv = f"workspace/outputs/{aid}/case.provenance.json"
            compile_footprint_writeback.func(autoid=aid, provenance_path=pv,
                                             on_device_passed=True)
            wrote += 1
        except Exception:  # noqa: BLE001
            led.data["audit"]["notes"].append({"autoid": aid, "event": "footprint_writeback_fail"})
        try:
            _promote_behavior_candidates(aid, led)
        except Exception:  # noqa: BLE001
            led.data["audit"]["notes"].append({"autoid": aid, "event": "behavior_promote_fail"})
    led.save()
    sh.emit(f"写回: {wrote}/{len(passed)} PASS case")
    return {"phase_status": "ok", **sh.counts_update(led)}


def _promote_behavior_candidates(aid: str, led) -> None:
    """行为候选晋升(V6 支柱2b 两段闸第二段):case 真 PASS 才把候选转
    RawFact(behavior)+device_evidence 入库——merger 的 device_verified 门再校验
    「观测命令真实出现在该 PASS 卷面」。fail/awaiting 的候选永不到这里。
    ``FOOTPRINT_BEHAVIOR_WRITEBACK=0`` 关。"""
    if not sh.env_flag("FOOTPRINT_BEHAVIOR_WRITEBACK"):
        return
    cand_path = sh.outputs_root() / aid / "behavior_candidates.json"
    cands = sh.read_json(cand_path, []) or []
    if not cands:
        return
    # 该 aid 最近一条 PASS 台账(device_evidence 锚)
    ledger_file = sh.project_root() / "runtime" / "logs" / "verified_runs.jsonl"
    ref = None
    if ledger_file.is_file():
        for line in ledger_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if str(rec.get("autoid")) == aid and str(rec.get("verdict")) == "pass":
                ref = {"autoid": aid, "run_ts": rec.get("run_ts")}
    if ref is None:
        return
    import hashlib
    from main.ist_core.memory.footprint.schema import RawFact
    from main.ist_core.memory.footprint.router import route_facts
    from main.ist_core.memory.footprint.merger import merge_fact
    from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS
    promoted = 0
    for c in cands:
        cmd = str(c.get("observe_cmd") or "").strip()
        content = str(c.get("content") or "").strip()
        if not cmd or not content:
            continue
        head = [t for t in cmd.split() if t.lower() not in ("no", "show", "clear")][:2] or cmd.split()[:1]
        rf = RawFact(fact_kind="behavior", feature_path=head,
                     fact_key=f"{' '.join(head)}:{hashlib.sha1(content.encode()).hexdigest()[:8]}",
                     cli_syntax=cmd, content=content,
                     device_evidence=dict(ref),
                     source_thread=f"engine_behavior:{aid}")
        try:
            for routed in route_facts([rf], Path(KNOWLEDGE_FOOTPRINTS)):
                if merge_fact(routed, Path(KNOWLEDGE_FOOTPRINTS)).action != "skip":
                    promoted += 1
        except Exception:  # noqa: BLE001
            continue
    if promoted:
        sh.emit(f"{aid[-6:]} 行为知识晋升 {promoted} 条")


# --------------------------------------------------------------- [mech] report
def report(state: dict) -> dict:
    """机读交付判定 + engine_report.json;人话摘要作为薄工具返回值素材。

    交付判定(用户判据机读形式):非 pass 的 case 全部 ∈ {awaiting_user,
    failed_terminal(DC/env/frozen), escalated} → delivered_with_labels;
    全 pass → delivered_all_pass;否则 stopped(带原因)。
    """
    led = sh.load_ledger(state)
    c = led.counts()
    n_total = len(led.data["cases"])
    n_pass = c.get(L.S_PASSED, 0)
    nonterminal = {k: v for k, v in c.items() if k not in L.TERMINAL_STATES and v}

    if state.get("phase_status") == "error" or state.get("error"):
        outcome = "error"
    elif n_pass == n_total and n_total > 0:
        outcome = "delivered_all_pass"
    elif not nonterminal and n_total > 0:
        outcome = "delivered_with_labels"
    else:
        outcome = "stopped"

    rep = {
        "outcome": outcome,
        "generated_at": time.time(),
        "totals": {"cases": n_total, "passed": n_pass, **c},
        "rounds": int(state.get("round") or 0),
        "waves": int(state.get("wave") or 0),
        "error": state.get("error") or "",
        "cases": {aid: {"state": cc.get("state"),
                        "rounds_used": cc.get("rounds_used"),
                        "verdicts": cc.get("verdict_history", []),
                        "detail": cc.get("last_detail", ""),
                        "runtime_underdetermined": bool(cc.get("runtime_underdetermined")),
                        "attribution": cc.get("attribution", {})}
                  for aid, cc in sorted(led.data["cases"].items())},
        "audit": led.data.get("audit", {}),
        "refs": {"manifest": state.get("manifest_ref"),
                 "merged_xlsx": state.get("merged_xlsx_ref"),
                 "last_run": state.get("last_run_ref"),
                 "ledger": state.get("ledger_ref")},
    }
    out_name = str(state.get("out_name") or "engine")
    rp = sh.outputs_root() / out_name / "engine_report.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    tmp = rp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    import os
    os.replace(tmp, rp)
    sh.emit(f"report: {outcome} pass={n_pass}/{n_total}")
    return {"phase_status": "ok",
            "report_ref": str(rp.relative_to(sh.project_root())),
            **sh.counts_update(led)}
