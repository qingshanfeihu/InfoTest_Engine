# -*- coding: utf-8 -*-
"""INV-11 失败语义红线专项(§18.2,审计坑#4/12/14/18;式①已在 test_broken_third_state)。

三式:输入解析失败=error 态;动作失败=failed 事实(禁成功事实);门数据面缺席
=显式入账。「静默继续」不是合法选项。
"""
from __future__ import annotations

import json

import pytest

from main.ist_core.compile_engine_v8 import facts as F
from tests.ist_core.compile_engine_v8.test_broken_third_state import rec_env, A, _v  # noqa: F401


def test_writeback_failure_lands_failed_fact(rec_env, monkeypatch):
    """式②(坑#4):写回失败不落成功事实——落 writeback_failed,台账不为失败背书。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref: ["precedent", "footprint"])
    rec_env["lr"].write_text(json.dumps([{"autoid": A, "verdict": "pass"}]),
                             encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    assert not [f for f in fs if f.get("ev") == "writeback"]
    wf = [f for f in fs if f.get("ev") == "writeback_failed"]
    assert wf and set(wf[-1]["targets"]) == {"precedent", "footprint"}


def test_writeback_partial_failure_split(rec_env, monkeypatch):
    """部分失败:成功目标落 writeback,失败目标落 writeback_failed——按真发生记账。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref: ["footprint"])
    rec_env["lr"].write_text(json.dumps([{"autoid": A, "verdict": "pass"}]),
                             encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    ok = [f for f in fs if f.get("ev") == "writeback"]
    bad = [f for f in fs if f.get("ev") == "writeback_failed"]
    assert ok and ok[-1]["targets"] == ["precedent"]
    assert bad and bad[-1]["targets"] == ["footprint"]


def test_rollback_failure_lands_failed_fact(rec_env, monkeypatch):
    """式②:回滚失败=半毒残留在库,落 rollback_failed 非 rollback。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref: [])
    monkeypatch.setattr(N, "_rollback_one", lambda aid: ["precedent"])
    F.append_facts(rec_env["facts"], [
        _v("pass", ctx="subset", rid="r0"),
        {"ev": "writeback", "aid": A, "targets": ["precedent"], "voucher_run": "r0"}])
    rec_env["lr"].write_text(json.dumps([{"autoid": A, "verdict": "fail"}]),
                             encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    assert not [f for f in fs if f.get("ev") == "rollback"]
    assert [f for f in fs if f.get("ev") == "rollback_failed"]


def test_user_decision_persist_failure_no_fact(rec_env, monkeypatch):
    """式②(坑#14):裁决落盘失败=decision 不落账(留 needs_decision 下轮重问)——
    emit 的 A 层硬门以盘上文件为凭据,账在盘不在=硬门被击穿。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.tools.device import verifiability_tool as VT
    monkeypatch.setattr(VT.compile_user_decision, "func",
                        lambda autoid, decision: "error: disk full")
    F.append_facts(rec_env["facts"], [
        {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:1"}])
    monkeypatch.setattr(N, "interrupt", lambda payload: {A: "改过程"})
    from main.ist_core.compile_engine_v8.questions import build_questions
    monkeypatch.setattr("main.ist_core.compile_engine_v8.questions.load_ledgers",
                        lambda root, aids: {A: {"autoid": A, "claims": [
                            {"claim_kind": "unverifiable", "reason": "r"}]}})
    N.ask_decision(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    assert not [f for f in fs if f.get("ev") == "decision"]


def test_probe_empty_echo_is_failed():
    """式③盲区(坑#12):探针空回显=床态未知,不是干净。"""
    from main.ist_core.compile_engine_v8.bed import _probe_failed
    assert _probe_failed("") is True
    assert _probe_failed("   \n") is True
    assert _probe_failed("(no output)") is False


def test_bed_closure_failed_fact_surfaces_next_batch(rec_env, monkeypatch):
    """坑#12 消费端:上批床态收敛失败事实 → 本批 bed_gate 强制呈报(床离场态未知)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.compile_engine_v8 import bed as B
    F.append_facts(rec_env["facts"], [
        {"ev": "bed_closure_failed", "aid": "", "host": "h",
         "reason": "post-batch bed convergence crashed"}])
    monkeypatch.setattr(N.B, "bed_unrestored", lambda root, host: [])
    monkeypatch.setattr(N.B, "bed_check", lambda *a, **k: {
        "host": "h", "probes": {}, "findings": [], "needs_ask": False,
        "anchor": {"status": "match", "device": "x"}, "ours_unrestored": []})
    monkeypatch.setattr(N.B, "bed_snapshot", lambda fn: {})
    captured = {}
    monkeypatch.setattr(N, "interrupt", lambda payload: captured.update(payload) or {"decision": "继续"})
    out = N.bed_gate(rec_env["state"])
    assert out["phase_status"] == "ok"
    kinds = [f.get("kind") for f in (captured.get("report") or {}).get("findings", [])]
    assert "bed_closure_failed" in kinds
