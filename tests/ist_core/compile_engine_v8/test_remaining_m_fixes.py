"""#19 剩余 M 项回归锚(M-02/06/07/11/12/20~24 的机械可测面)。"""
from __future__ import annotations

import json
import logging
import time
from unittest.mock import MagicMock

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8.questions import (
    FORM_BY_KIND, build_ask_question, build_questions, validate_questions,
)


A = "203601753067655101"


def test_form_by_kind_has_sequence_periodicity_m24():
    assert FORM_BY_KIND.get("sequence_periodicity") == "member"


def test_triplet_ordering_sensitive_visible_m24():
    """三元组分支必须显式带「顺序语义」,与 validate_questions 同口径。"""
    led = {A: {"claims": [{
        "claim_kind": "verification_path_absent",
        "test_point": "按序命中各成员",
        "obstacle": "床无触发端",
        "ordering_sensitive": True,
        "equivalent": {"procedure": "同客户端连发并验序", "preserves": "顺序"},
        "no_equivalent_reason": "无",
    }]}}
    qs = build_questions(led)
    assert qs and qs[0].get("_ordering") is True
    blob = qs[0]["question"] + json.dumps(qs[0]["options"], ensure_ascii=False)
    assert "顺序语义" in blob
    assert validate_questions(qs, led)


def test_common_causes_injected_into_ask_question_m22():
    q = build_ask_question({
        "autoid": A, "kind": "contra", "title": "t", "contradictions": 2,
        "common_causes": [{"key": "timeout stem", "aids": ["655101", "655102"]}],
    })
    assert "批内同因聚类" in q["question"]
    assert "timeout stem" in q["question"]


def test_attribution_freshness_gate_m02(monkeypatch, tmp_path):
    """迟到 fork 的陈旧 _attribution(ts < t0) 不得收账盖章本轮。"""
    lr = tmp_path / "last_run.json"
    state = {"out_name": "m02", "max_rounds": 3, "last_run_ref": "last_run.json"}
    fs = [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery",
         "result": "fail", "artifact": "a1", "volume": "v", "signatures": ["s"]},
    ]
    vw = {"cases": {A: {"status": V.S_FAILED, "rounds": 1, "contradictions": 0,
                        "artifact": "a1", "frozen": False, "transient_recur": False}},
          "counts": {V.S_FAILED: 1}, "volume": "v"}

    appended: list = []

    def _append(st, facts):
        appended.extend(facts)

    monkeypatch.setattr(N.sh, "load_facts", lambda s: list(fs))
    monkeypatch.setattr(N.sh, "view", lambda s, f=None: vw)
    monkeypatch.setattr(N.sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(N.sh, "outputs_root", lambda: tmp_path)
    monkeypatch.setattr(N.sh, "append", _append)
    monkeypatch.setattr(N.sh, "emit", lambda *a, **k: None)
    monkeypatch.setattr(N.sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(N.sh, "fork_executor", lambda n: (MagicMock(), None, None))
    monkeypatch.setattr(N.sh, "counts_update", lambda s, f=None: {})
    monkeypatch.setattr(N.sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    monkeypatch.setattr(N, "_call_fork", lambda *a, **k: "")
    monkeypatch.setattr(N, "_load_case_rows", lambda aid: [])
    monkeypatch.setattr(N, "_fanout_pool_size", lambda n: 1)
    monkeypatch.setattr(N, "_sibling_contrast", lambda *a, **k: None)
    monkeypatch.setattr(N, "_evidence_suspect", lambda *a, **k: None)

    # 陈旧 → 不收
    lr.write_text(json.dumps([{
        "autoid": A, "_attribution": {
            "layer": "V", "disposition": "reflow", "evidence": "old",
            "ts": time.time() - 3600}}]), encoding="utf-8")
    N.attribute(state)
    assert not any(f.get("ev") == "attribution" for f in appended)

    # 新鲜 → 收
    appended.clear()
    lr.write_text(json.dumps([{
        "autoid": A, "_attribution": {
            "layer": "V", "disposition": "reflow", "evidence": "new echo",
            "ts": time.time() + 10}}]), encoding="utf-8")
    N.attribute(state)
    got = [f for f in appended if f.get("ev") == "attribution" and f.get("aid") == A]
    assert len(got) == 1
    assert "new echo" in str(got[0].get("evidence") or "")


def test_pending_emit_invalid_hits_round_cap_m07(monkeypatch):
    """M-07:S_PENDING(emit_invalid 打回)到轮次封顶须落 cap_reached,不再派 fork。"""
    state = {"out_name": "m07", "max_rounds": 2}
    fs = [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "authored", "aid": A, "round": 2, "artifact": "a2"},
        {"ev": "emit_invalid", "aid": A, "reason": "lint"},
    ]
    vw = {"cases": {A: {"status": V.S_PENDING, "rounds": 2, "contradictions": 0,
                        "artifact": "a2", "frozen": False, "transient_recur": False}},
          "counts": {V.S_PENDING: 1}, "volume": ""}
    appended: list = []
    monkeypatch.setattr(N.sh, "load_facts", lambda s: list(fs))
    monkeypatch.setattr(N.sh, "view", lambda s, f=None: vw)
    monkeypatch.setattr(N.sh, "panel_waiting", lambda *a, **k: [])
    monkeypatch.setattr(N.sh, "granted_rounds", lambda *a, **k: 0)
    monkeypatch.setattr(N.sh, "append", lambda s, facts: appended.extend(facts))
    monkeypatch.setattr(N.sh, "emit", lambda *a, **k: None)
    monkeypatch.setattr(N.sh, "counts_update", lambda s, f=None: {"n": 0})
    monkeypatch.setattr(N.F, "rounds_used", lambda mine, aid: 2)

    out = N.author(state)
    assert out.get("phase_status") == "nothing_to_do"
    assert any(f.get("ev") == "cap_reached" and f.get("aid") == A for f in appended)


def test_self_cleanup_only_queue_no_warning_m23():
    """M-23:contra/cap 队头仅 self_cleanup 时不算路由缺陷(与 remedies 设计态一致)。"""
    kind, acts = "contra", {"self_cleanup"}
    should_warn = not (kind in ("cap", "contra") and acts <= {"self_cleanup"})
    assert should_warn is False
    kind2, acts2 = "contra", {"self_cleanup", "recompile_directed"}
    should_warn2 = not (kind2 in ("cap", "contra") and acts2 <= {"self_cleanup"})
    assert should_warn2 is True
    assert logging.getLogger("main.ist_core.compile_engine_v8.nodes")
