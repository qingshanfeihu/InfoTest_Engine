"""K 健康度三面 gate_disabled + 报告健康度行(§18.2 第6行补齐,2026-07-13)。

审计发现:式③此前只 grammar 面(diagnose_s0)落 gate_disabled;inventory(inverse_forms)
读失败静默降级、画像(_case_touch_profile)except 静默、报告 K 健康度行未渲染、零测试。
补齐三面各落 gate_disabled + render 渲染健康度行。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8 import render as R


def test_report_renders_k_health_line_for_each_gate():
    """三面 gate_disabled 事实 → 报告 K 健康度行(用户看得见,非只机读)。"""
    fs = [
        {"ev": "gate_disabled", "gate": "diagnose_s0", "reason": "grammar unavailable"},
        {"ev": "gate_disabled", "gate": "inverse_forms", "reason": "inventory unavailable"},
        {"ev": "gate_disabled", "gate": "touch_profile", "reason": "profile failed"},
    ]
    report = {"totals": {"deliverable": 5, "cases": 6, "broken": 0}, "cases": {}}
    md = R.render_delivery_report(report, fs, {"cases": []}, {})
    assert "K 健康度" in md
    assert "3 个判定门" in md
    assert "批级污染诊断" in md and "τ 覆盖门/机械恢复" in md and "触碰画像" in md


def test_report_no_health_line_when_all_gates_up():
    """三面齐备(无 gate_disabled)→ 不渲染健康度行(不噪音)。"""
    report = {"totals": {"deliverable": 6, "cases": 6, "broken": 0}, "cases": {}}
    md = R.render_delivery_report(report, [], {"cases": []}, {})
    assert "K 健康度" not in md


def test_inverse_forms_gate_landed_when_inventory_empty(monkeypatch):
    """inventory 面(inverse_forms)缺席 → diagnose 落 gate_disabled(gate=inverse_forms)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import _shared as sh
    import main.ist_core.compile_engine_v8.bed as B

    appended: list = []
    monkeypatch.setattr(sh, "append", lambda st, facts: appended.extend(facts))
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(B, "_inverse_pairs", lambda: {})            # inventory 空
    # grammar 面正常(只测 inventory 面单独落)
    monkeypatch.setattr(N, "_diag_grammar",
                        lambda: ([__import__("re").compile("x")], [], ([], [])))
    monkeypatch.setattr(N, "_load_case_rows", lambda aid: [])
    fs = [{"ev": "authored", "aid": "203600000000000001", "round": 1, "artifact": "a"},
          {"ev": "merged", "aid": "", "volume": "v1",
           "composition": ["203600000000000001"]},
          {"ev": "verdict", "aid": "203600000000000001", "result": "fail",
           "run_id": "r1", "ctx": "delivery", "artifact": "a", "volume": "v1"}]
    monkeypatch.setattr(sh, "load_facts", lambda st: fs)
    monkeypatch.setattr(sh, "view", lambda st, f=None: {"cases": {
        "203600000000000001": {"status": "failed", "rounds": 1, "contradictions": 0}}})
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [{"autoid": "203600000000000001"}]})
    monkeypatch.setattr(sh, "counts_update", lambda st, f=None: {})
    N.diagnose({"out_name": "b1"})
    gates = [f for f in appended if f.get("ev") == "gate_disabled"]
    assert any(g["gate"] == "inverse_forms" for g in gates)
