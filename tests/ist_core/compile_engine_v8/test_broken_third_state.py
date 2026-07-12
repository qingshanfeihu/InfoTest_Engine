# -*- coding: utf-8 -*-
"""(43)(44) broken 第三态全链 + INV-2 残差真门(DESIGN §18.1/18.2;审计坑#1/2/3)。

金标准形态:668030 空真(恢复步失败断言恒真"过")与级联 unknown 折叠成 fail
(假签名→误 frozen→假归因)。broken/not_run=案没跑成,结论无效≠断言红。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import views as V

A = "203600000000000001"


def _v(result, ctx="delivery", art="a1", vol="v1", rid="r1", sigs=None):
    return {"ev": "verdict", "aid": A, "run_id": rid, "ctx": ctx, "result": result,
            "artifact": art, "volume": vol, "signatures": sigs or []}


# ── fold:S_BROKEN 派生态 ─────────────────────────────────────────────────────
def test_fold_broken_and_not_run_derive_s_broken():
    for res in ("broken", "not_run"):
        fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"}, _v(res)]
        vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
        assert vw["cases"][A]["status"] == V.S_BROKEN, res
        assert vw["counts"].get(V.S_BROKEN) == 1


def test_fold_broken_then_pass_recovers():
    """复跑后 pass:标签跟最新裁决走(broken 不留疤)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "merged", "aid": "", "volume": "v1", "composition": [A]},
          _v("not_run"), _v("pass", rid="r2")]
    vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
    assert vw["cases"][A]["status"] == V.S_DELIVERABLE


# ── frozen:broken 不构成证据 ─────────────────────────────────────────────────
def test_frozen_ignores_broken_rounds():
    """fail(sig X)→not_run→fail(sig X):broken 轮不打断同法证伪序列 → 仍 frozen;
    且 fail→not_run→not_run 不 frozen(没跑成≠证伪)。"""
    fs = [_v("fail", rid="r1", sigs=["X"]), _v("not_run", rid="r2"),
          _v("fail", rid="r3", sigs=["X"])]
    assert F.frozen(fs, A, "a1") is True
    fs2 = [_v("fail", rid="r1", sigs=["X"]), _v("not_run", rid="r2"),
           _v("not_run", rid="r3")]
    assert F.frozen(fs2, A, "a1") is False


# ── reconcile:透传/残差门/硬停/streak(用真节点+盘面夹具) ─────────────────────
@pytest.fixture()
def rec_env(tmp_path, monkeypatch):
    from main.ist_core.compile_engine_v8 import _shared as sh
    out = tmp_path / "outputs"
    mdir = out / "b1"
    mdir.mkdir(parents=True)
    facts_file = mdir / "facts.jsonl"
    F.append_facts(facts_file, [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "merged", "aid": "", "volume": "v1", "composition": [A],
         "moved_tail": [], "coexist_violations": []},
    ])
    manifest = {"cases": [{"autoid": A, "title": "案A"}]}
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: out)
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: manifest)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "emit_tick", lambda *a, **k: None)
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(sh, "artifact_fingerprint", lambda aid: "a1")
    lr = mdir / "last_run.json"
    return {"tmp": tmp_path, "lr": lr, "facts": facts_file,
            "state": {"out_name": "b1", "run_ctx": "delivery",
                      "last_run_ref": str(lr.relative_to(tmp_path))}}


def test_reconcile_unknown_becomes_not_run(rec_env, monkeypatch):
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref: None)
    rec_env["lr"].write_text(json.dumps([
        {"autoid": A, "verdict": "unknown", "detail_tail": "stale_log: ..."}]),
        encoding="utf-8")
    out = N.reconcile(rec_env["state"])
    assert out["phase_status"] == "ok"
    fs = F.load_facts(rec_env["facts"])
    v = [f for f in fs if f.get("ev") == "verdict"][-1]
    assert v["result"] == "not_run"           # 禁折叠成 fail(坑#1)
    assert out.get("n_broken") == 1


def test_reconcile_inv2_residual_gate(rec_env):
    """INV-2 真门:组成内案在 last_run 无记录=裁决蒸发,error 硬停。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rec_env["lr"].write_text("[]", encoding="utf-8")
    out = N.reconcile(rec_env["state"])
    assert out["phase_status"] == "error"
    assert "verdict_unconsumed" in out["error"]


def test_reconcile_lastrun_unreadable_hard_stop(rec_env):
    """INV-11 式①:last_run 损坏=error 硬停,禁 default-空(坑#3)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rec_env["lr"].write_text("{corrupted", encoding="utf-8")
    out = N.reconcile(rec_env["state"])
    assert out["phase_status"] == "error"
    assert "unreadable" in out["error"]
    # 且没有任何裁决入账(禁半账)
    fs = F.load_facts(rec_env["facts"])
    assert not [f for f in fs if f.get("ev") == "verdict"]


def test_reconcile_broken_streak_escalates(rec_env, monkeypatch):
    """同案同卷面连续 2 轮没跑成 → escalated(复跑救不了,升级人工)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref: None)
    F.append_facts(rec_env["facts"], [_v("not_run", rid="prev")])
    rec_env["lr"].write_text(json.dumps([
        {"autoid": A, "verdict": "unknown"}]), encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    esc = [f for f in fs if f.get("ev") == "escalated"]
    assert esc and "consecutive" in esc[-1]["reason"]


def test_reconcile_broken_does_not_rollback(rec_env, monkeypatch):
    """(44):broken 不构成对 pass 的反证——终验 not_run 不触发先例回滚。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rolled = []
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref: None)
    monkeypatch.setattr(N, "_rollback_one", lambda aid: rolled.append(aid))
    F.append_facts(rec_env["facts"], [
        _v("pass", ctx="subset", rid="r0"),
        {"ev": "writeback", "aid": A, "targets": ["precedent"], "voucher_run": "r0"}])
    rec_env["lr"].write_text(json.dumps([
        {"autoid": A, "verdict": "unknown"}]), encoding="utf-8")
    N.reconcile(rec_env["state"])
    assert rolled == []


# ── 路由与词表 ───────────────────────────────────────────────────────────────
def test_route_broken_goes_to_merge_rerun():
    from main.ist_core.compile_engine_v8.graph import _after_reconcile
    assert _after_reconcile({"n_broken": 1}) == "merge"
    assert _after_reconcile({"phase_status": "error"}) == "closing"


def test_status_vocab_and_leak():
    from main.ist_core.compile_engine_v8 import render as RD
    assert "broken" in RD.STATUS_CN
    assert RD.leak_scan("案状态为 broken 与 not_run") != []   # 英文枚举必须被拦
    assert RD.leak_scan(RD.STATUS_CN["broken"]) == []
