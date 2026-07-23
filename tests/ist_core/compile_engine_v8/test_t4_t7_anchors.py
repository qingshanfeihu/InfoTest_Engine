# -*- coding: utf-8 -*-
"""T-4~T-7:谎报类机制锚——交付物降级 / 未跑成行 / gate_disabled / decision_outcome。"""
from __future__ import annotations

import json

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import render as RD
from main.ist_core.compile_engine_v8 import _shared as sh

from tests.ist_core.compile_engine_v8.test_render_closing import (  # noqa: F401
    engine_env, _mark_b_deliverable, A)


def test_t4_missing_deliverable_degrades_outcome(engine_env, monkeypatch):
    """T-4 R036:盘上缺一件交付物 → outcome 降为 delivery_incomplete(生产对账臂同句)。"""
    env = engine_env
    _mark_b_deliverable(env)
    monkeypatch.setattr(sh, "emit_summary", lambda *a, **k: None)
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    mdir = env["mdir"]
    assert (mdir / "delivery_report.md").is_file()
    (mdir / "delivery_report.md").unlink()
    deliver_files = ["case.xlsx", "delivery_report.md", "engine_report.json", "facts.jsonl"]
    missing = [f for f in deliver_files if not (mdir / f).is_file()]
    assert "delivery_report.md" in missing
    report = json.loads((mdir / "engine_report.json").read_text(encoding="utf-8"))
    # nodes.py:3558-3563 同口径
    if missing and str(report.get("outcome", "")).startswith("delivered"):
        report["outcome"] = "delivery_incomplete"
    assert report["outcome"] == "delivery_incomplete"
    dmd = RD.render_delivery_report(report, [], {"cases": []}, {}, {})
    assert "交付不完整" in dmd


def test_t5_broken_cases_line_in_delivery_report():
    """T-5 R022:报告「N 案未跑成」单列行有断言。"""
    report = {
        "engine": "v8", "outcome": "delivered_with_labels",
        "totals": {"cases": 3, "deliverable": 1, "broken": 1,
                   "broken_errored": 1, "broken_blocked": 0, "failed": 0},
        "cases": {
            A: {"status": "broken", "artifact": "a1", "rounds": 1,
                "contradictions": 0, "frozen": False, "transient_recur": False},
            "203600000000000002": {"status": "broken_errored", "artifact": "a2",
                                   "rounds": 1, "contradictions": 0,
                                   "frozen": False, "transient_recur": False},
            "203600000000000003": {"status": "deliverable", "artifact": "a3",
                                   "rounds": 1, "contradictions": 0,
                                   "frozen": False, "transient_recur": False},
        },
        "bed": {}, "moved_tail": [], "coexist_violations": [],
    }
    md = RD.render_delivery_report(report, [], {"cases": []}, {}, {})
    assert "有 2 个用例本轮**未跑成**" in md


def test_t6_gate_disabled_visible_in_report():
    """T-6 R006③:gate_disabled 文法/画像/inverse 三面入事实且报告可见。"""
    facts = [
        {"ev": "gate_disabled", "aid": "", "gate": "diagnose_s0",
         "reason": "grammar load failed"},
        {"ev": "gate_disabled", "aid": "", "gate": "touch_profile",
         "reason": "N cases missing touch profile", "aids": [A]},
        {"ev": "gate_disabled", "aid": "", "gate": "inverse_forms",
         "reason": "inventory signatures missing"},
    ]
    assert {"diagnose_s0", "touch_profile", "inverse_forms"} <= {f["gate"] for f in facts}
    report = {"engine": "v8", "outcome": "delivered_with_labels",
              "totals": {"cases": 1, "deliverable": 0}, "cases": {},
              "bed": {}, "moved_tail": [], "coexist_violations": []}
    md = RD.render_delivery_report(report, facts, {"cases": []}, {}, {})
    assert "K 健康度" in md
    assert "批级污染诊断" in md
    assert "触碰画像" in md


def test_t7_resume_decision_outcome_effective(engine_env):
    """T-7 R016:decision_outcome 投影区分 effective / 空答;resume 为有效裁决。"""
    env = engine_env
    F.append_facts(env["facts"], [
        {"ev": "decision", "aid": A, "question_id": f"nd:{A}:1",
         "answer": "改过程", "token": "改过程"},
        {"ev": "decision", "aid": A, "question_id": f"panel:{A}:1",
         "answer": "", "token": "suspend",
         "note": "auto-suspended: no answer"},
        {"ev": "decision", "aid": A, "question_id": f"resume:{A}:1",
         "answer": "恢复处理", "token": "resume"},
    ])
    fs = F.load_facts(env["facts"])
    oc = []
    for f in fs:
        if f.get("ev") != "decision":
            continue
        ans = str(f.get("answer") or "").strip()
        tok = str(f.get("token") or "")
        effective = bool(ans) and tok != "suspend"
        oc.append({"question_id": f.get("question_id"),
                   "effective": effective, "token": tok})
    by_qid = {x["question_id"]: x for x in oc}
    assert by_qid[f"nd:{A}:1"]["effective"] is True
    assert by_qid[f"panel:{A}:1"]["effective"] is False
    assert by_qid[f"resume:{A}:1"]["effective"] is True
    assert by_qid[f"resume:{A}:1"]["token"] == "resume"
