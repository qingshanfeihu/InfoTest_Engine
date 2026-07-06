"""验证回路升级出口门(CNAME 570 复盘 #2):"没路可走"必须升级人工,不静默吞终态。

- 轮次耗尽仍 fail(disposition 一路 reflow)→ escalated + escalation_reason
  + 逐轮 fail_evidence(带 device_context 原文摘录),而非 failed_terminal;
- fork 归因未落盘 → escalated(attribution_missing);
- 定性终态(env_blocked 等)仍 failed_terminal,不被误转;
- 迁移合法性:failed_active→escalated 合法,passed→escalated 抛错;
- 收敛路由不扰动:escalated 混入后,子集轮剩余全终态且有 pass 仍回 merge 终验
  (zhaiyq 终验整卷语义保持)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import main.ist_core.compile_engine.nodes.compile_phase as CP
import main.ist_core.compile_engine.nodes as N
import main.ist_core.compile_engine.nodes._shared as SH
from main.ist_core.compile_engine import ledger as L
from main.ist_core.compile_engine.graph import build_compile_engine_graph

_OUT = "engine_escalation_ut"
_AID_OK = "203099999999900601"
_AID_BAD = "203099999999900602"


class _NullLimiter:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    out_root = tmp_path / "outputs"
    out_root.mkdir()
    monkeypatch.setattr(SH, "project_root", lambda: tmp_path)
    monkeypatch.setattr(SH, "outputs_root", lambda: out_root)
    monkeypatch.setattr(SH, "emit", lambda text: None)

    def fake_prep_for(aids):
        def fake_prep(state):
            (out_root / _OUT).mkdir(exist_ok=True)
            mf = out_root / _OUT / "manifest.json"
            mf.write_text(json.dumps({"cases": [{"autoid": a} for a in aids]}),
                          encoding="utf-8")
            led = SH.load_ledger({**state, "out_name": _OUT,
                                  "ledger_ref": f"outputs/{_OUT}/engine_ledger.json"})
            for a in aids:
                if not led.case(a).get("state"):
                    led.transition(a, L.S_PENDING)
            led.save()
            return {"phase_status": "ok", "out_name": _OUT,
                    "manifest_ref": f"outputs/{_OUT}/manifest.json",
                    "ledger_ref": str(led.path.relative_to(tmp_path)),
                    "round": 0, "wave": 0, **SH.counts_update(led)}
        return fake_prep

    monkeypatch.setattr(N, "prep", fake_prep_for([_AID_OK, _AID_BAD]))

    def fake_dispatch(executor, aid, brief, t0):
        d = out_root / aid
        d.mkdir(exist_ok=True)
        (d / "case.xlsx").write_bytes(b"x" + aid.encode())
        return L.S_PRODUCED, "stub"
    monkeypatch.setattr(CP, "_dispatch_one", fake_dispatch)
    monkeypatch.setattr(SH, "fork_executor", lambda n: (object(), _NullLimiter(), 2))

    import main.ist_core.tools.device.compile_pipeline as PIPE
    monkeypatch.setattr(PIPE, "_grade_extract_facts", lambda aid: {}, raising=False)

    import main.ist_core.tools.device.emit_xlsx_tool as EM

    def fake_merged(autoids=None, out_name="", **kw):
        d = out_root / out_name
        d.mkdir(exist_ok=True)
        (d / "case.xlsx").write_text(",".join(sorted(autoids or [])), encoding="utf-8")
        return f"已合并 {len(autoids or [])}"
    monkeypatch.setattr(EM.compile_emit_merged, "func", staticmethod(fake_merged))

    monkeypatch.setattr(N, "writeback", lambda state: {"phase_status": "ok"})
    yield


def _make_digest(attribution_for_bad):
    """fail 恒定在 _AID_BAD;每轮 device_context 原文不同(逐轮证据可辨)。"""
    calls = {"n": 0}

    def fake_digest(xlsx_path, *a, **kw):
        calls["n"] += 1
        xp = Path(xlsx_path)
        aids = xp.read_text(encoding="utf-8").split(",")
        recs = []
        for aid in aids:
            fail = aid == _AID_BAD
            recs.append({"autoid": aid, "verdict": "fail" if fail else "pass",
                         "device_context": f"cli echo round{calls['n']} for {aid[-3:]}",
                         "_attribution": (dict(attribution_for_bad) if fail
                                          and attribution_for_bad else {})})
        (xp.parent / "last_run.json").write_text(json.dumps(recs), encoding="utf-8")
        return "digest ok"
    return fake_digest


def _run(monkeypatch, digest, max_rounds=2, thread="t-esc"):
    import main.ist_core.tools.device.batch_tools as BT
    monkeypatch.setattr(BT.dev_run_batch_digest, "func", staticmethod(digest))
    graph = build_compile_engine_graph()
    graph.invoke({"mindmap_path": "x.txt", "product_version": "10.5",
                  "out_name": _OUT, "max_rounds": max_rounds},
                 {"configurable": {"thread_id": thread}, "recursion_limit": 60})
    led = SH.load_ledger({"out_name": _OUT,
                          "ledger_ref": f"outputs/{_OUT}/engine_ledger.json"})
    rep = json.loads((SH.outputs_root() / _OUT / "engine_report.json")
                     .read_text(encoding="utf-8"))
    return led, rep


def test_max_rounds_exhausted_escalates_with_evidence(monkeypatch):
    """耗尽轮次一路 reflow → escalated(非 failed_terminal)+ reason + 逐轮证据;
    且 escalated 混入后仍完成终验整卷(收敛路由不扰动)。"""
    led, rep = _run(monkeypatch, _make_digest(
        {"layer": "V", "disposition": "reflow", "fix_direction": "stub fix"}))

    bad = led.case(_AID_BAD)
    assert bad["state"] == L.S_ESCALATED, bad
    assert bad["escalation_reason"] == "max_rounds_exhausted"
    rounds_seen = [e["round"] for e in bad["fail_evidence"]]
    assert rounds_seen == [1, 2], bad["fail_evidence"]
    assert all("cli echo round" in e["device_context"] for e in bad["fail_evidence"])

    rc = rep["cases"][_AID_BAD]
    assert rc["state"] == "escalated"
    assert rc["escalation_reason"] == "max_rounds_exhausted"
    assert rc["fail_evidence"], "report 必须带逐轮设备原文摘录"

    # pass 侧完成终验整卷(subset 收敛 → merge full → writeback):
    assert led.case(_AID_OK)["state"] == L.S_PASSED
    assert rep["outcome"] == "delivered_with_labels"
    assert rep["rounds"] >= 3, "round1 full + round2 subset + 终验 full"
    assert rep["totals"].get("escalated") == 1
    assert not rep["totals"].get("failed_terminal"), "escalated 不得再计为 failed_terminal 态"


def test_attribution_missing_escalates(monkeypatch):
    """fork 归因未落盘 → escalated(attribution_missing),不吞成 failed_terminal。"""
    import main.ist_core.tools.device.batch_tools as BT
    import main.ist_core.tools.device.fail_attribution as FA
    monkeypatch.setattr(BT.compile_fanout, "func", staticmethod(lambda **kw: "fork done"))
    monkeypatch.setattr(FA, "attribute_fail",
                        lambda *a, **kw: {"layer": "", "disposition": ""})

    led, rep = _run(monkeypatch, _make_digest(None), max_rounds=3, thread="t-esc-am")

    bad = led.case(_AID_BAD)
    assert bad["state"] == L.S_ESCALATED
    assert bad["escalation_reason"] == "attribution_missing"
    assert rep["cases"][_AID_BAD]["escalation_reason"] == "attribution_missing"


def test_qualified_terminal_not_converted(monkeypatch):
    """定性终态(env_blocked)仍 failed_terminal——已定性结论不属于升级出口。"""
    led, rep = _run(monkeypatch, _make_digest(
        {"layer": "E", "disposition": "env_blocked"}), thread="t-esc-env")

    bad = led.case(_AID_BAD)
    assert bad["state"] == L.S_FAILED_TERMINAL
    assert bad.get("last_detail") == "env_blocked"
    assert not bad.get("escalation_reason")
    assert rep["totals"].get("escalated", 0) == 0


def test_transition_legality():
    """failed_active→escalated 合法;passed→escalated 仍非法(pass 锁不动)。"""
    led = L.EngineLedger(Path("/nonexistent/never_saved.json"))
    led.transition("a1", L.S_PENDING)
    led.transition("a1", L.S_DISPATCHED)
    led.transition("a1", L.S_PRODUCED)
    led.transition("a1", L.S_FAILED_ACTIVE)
    led.transition("a1", L.S_ESCALATED)
    assert led.case("a1")["state"] == L.S_ESCALATED

    led.transition("a2", L.S_PENDING)
    led.transition("a2", L.S_DISPATCHED)
    led.transition("a2", L.S_PRODUCED)
    led.transition("a2", L.S_PASSED)
    with pytest.raises(L.IllegalTransition):
        led.transition("a2", L.S_ESCALATED)


def test_high_global_round_fresh_case_reflows_not_premature_escalate(monkeypatch):
    """脏 checkpoint 续跑根治(2026-07-07):全局 round 带高、但 case 新鲜(rounds_used 从 0)时,
    升级/reflow 判据用本 case rounds_used——新鲜 case 应走满 max_rounds reflow 才 escalate,
    不因 round_no>=max 在首 fail 就误升级(旧版实测 11→7 假回归)。"""
    def hi_prep(state):
        out_root = SH.outputs_root()
        (out_root / _OUT).mkdir(exist_ok=True)
        (out_root / _OUT / "manifest.json").write_text(
            json.dumps({"cases": [{"autoid": a} for a in (_AID_OK, _AID_BAD)]}), encoding="utf-8")
        led = SH.load_ledger({**state, "out_name": _OUT,
                              "ledger_ref": f"outputs/{_OUT}/engine_ledger.json"})
        for a in (_AID_OK, _AID_BAD):
            if not led.case(a).get("state"):
                led.transition(a, L.S_PENDING)
        led.save()
        return {"phase_status": "ok", "out_name": _OUT,
                "manifest_ref": f"outputs/{_OUT}/manifest.json",
                "ledger_ref": str(led.path.relative_to(SH.project_root())),
                "round": 5, "wave": 0, **SH.counts_update(led)}   # ← 全局轮次带高(模拟脏续跑)
    monkeypatch.setattr(N, "prep", hi_prep)

    led, rep = _run(monkeypatch, _make_digest(
        {"layer": "V", "disposition": "reflow", "fix_direction": "stub"}),
        max_rounds=3, thread="t-hi-round")

    bad = led.case(_AID_BAD)
    assert bad["state"] == L.S_ESCALATED
    # 关键:走满 3 轮 reflow 才升级(非首 fail 即升级)——per-case rounds_used 判据、非全局 round_no
    assert int(bad.get("rounds_used") or 0) == 3, f"新鲜 case 应走满 3 轮 reflow,实 {bad.get('rounds_used')}"
    assert len(bad["fail_evidence"]) == 3, f"应有 3 轮逐轮证据,实 {len(bad['fail_evidence'])}"
    assert led.case(_AID_OK)["state"] == L.S_PASSED
    assert rep["outcome"] == "delivered_with_labels"
