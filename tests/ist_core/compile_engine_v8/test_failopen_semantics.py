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
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: ["precedent", "footprint"])
    rec_env["lr"].write_text(json.dumps([{"autoid": A, "verdict": "pass"}]),
                             encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    assert not [f for f in fs if f.get("ev") == "writeback"]
    wf = [f for f in fs if f.get("ev") == "writeback_failed"]
    assert wf and set(wf[-1]["targets"]) == {"precedent", "footprint"}


def test_writeback_threads_provisional_keeps_footprint_device_verified(monkeypatch):
    """S5(§18.15-A / K (45)):子集轮 provisional 贯通到先例写回(检索期「用前先核」);
    footprint on_device_passed 恒 True——子集轮语法也真上机跑过,device_verified 不因未
    终验而降级(误降会断 device_verified 第二权威源拉取)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    from main.ist_core.tools.device import precedent_tools as PT
    from main.ist_core.tools.knowledge import footprint_writeback as FW
    cap: dict = {}

    class _WB:
        @staticmethod
        def func(autoid, last_run_path, provisional=None):
            cap["prov"] = provisional
            return "written back: ok"

    class _FP:
        @staticmethod
        def func(autoid, provenance_path, on_device_passed=True):
            cap["odp"] = on_device_passed
            return "ok"

    monkeypatch.setattr(PT, "compile_writeback", _WB)
    monkeypatch.setattr(FW, "compile_footprint_writeback", _FP)

    N._writeback_one(A, "workspace/outputs/x/last_run.json", provisional=True)
    assert cap["prov"] is True, "子集轮 provisional 应贯通到先例写回"
    assert cap["odp"] is True, "footprint 语法真上机跑过,不因子集/未终验降 device_verified"

    cap.clear()
    N._writeback_one(A, "workspace/outputs/x/last_run.json", provisional=False)
    assert cap["prov"] is False, "终验轮先例标非 provisional"
    assert cap["odp"] is True


def test_writeback_partial_failure_split(rec_env, monkeypatch):
    """部分失败:成功目标落 writeback,失败目标落 writeback_failed——按真发生记账。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: ["footprint"])
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
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: [])
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
         "run_id": "bc:b1:0:1",
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
    # H-11:答完落 bedclosure:{run_id},下批不再重问
    fs = F.load_facts(rec_env["facts"])
    assert any(f.get("ev") == "decision" and f.get("question_id") == "bedclosure:bc:b1:0:1"
               for f in fs)


def test_bed_closure_answered_not_reasked_H11(rec_env, monkeypatch):
    """H-11:已有 bedclosure:{run_id} decision 时,陈年 bed_closure_failed 不再 needs_ask。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    F.append_facts(rec_env["facts"], [
        {"ev": "bed_closure_failed", "aid": "", "host": "h", "run_id": "bc:old:1",
         "reason": "crashed"},
        {"ev": "decision", "aid": "", "question_id": "bedclosure:bc:old:1",
         "answer": "继续"},
    ])
    monkeypatch.setattr(N.B, "bed_unrestored", lambda root, host: [])
    monkeypatch.setattr(N.B, "bed_check", lambda *a, **k: {
        "host": "h", "probes": {}, "findings": [], "needs_ask": False,
        "anchor": {"status": "match", "device": "x"}, "ours_unrestored": []})
    monkeypatch.setattr(N.B, "bed_snapshot", lambda fn: {})
    captured = {}
    monkeypatch.setattr(N, "interrupt", lambda payload: captured.update(payload) or {"decision": "继续"})
    out = N.bed_gate(rec_env["state"])
    assert out["phase_status"] == "ok"
    assert not captured  # 未 interrupt
    kinds = [f.get("kind") for f in (captured.get("report") or {}).get("findings", [])]
    assert "bed_closure_failed" not in kinds


# ── B-1:run() 陈旧 last_run.json 新鲜度门(旧 pass 不得背书未上机的新卷面) ──────
@pytest.fixture()
def run_env(tmp_path, monkeypatch):
    """run() 节点夹具:merged 卷 + facts(merged 事实)+ 全 sh 注入点。"""
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
    xlsx = mdir / "case.xlsx"
    xlsx.write_text("volume", encoding="utf-8")
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: out)
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "emit_tick", lambda *a, **k: None)
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    return {"mdir": mdir, "xlsx": xlsx, "facts": facts_file,
            "state": {"out_name": "b1", "run_ctx": "delivery",
                      "merged_ref": "outputs/b1/case.xlsx"}}


def test_run_stale_last_run_is_error_not_ok(run_env, monkeypatch):
    """B-1 红绿:digest 失败早退不写文件、上轮 last_run.json 批内存活——旧代码只查
    存在性 → ok 放行(reconcile 拿上轮 pass 背书没上机的新卷面);修后 mtime<本卷
    case.xlsx = 陈旧 → error 硬停且带 digest 原话。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    import os
    # digest 返回非 list 错误(非三个 busy 标记),不写 last_run——设备失败形态
    monkeypatch.setattr(N, "_digest_fn",
                        lambda *a, **k: '{"error": "ssh connection reset by peer"}')
    stale = run_env["mdir"] / "last_run.json"
    stale.write_text(json.dumps([{"autoid": A, "verdict": "pass"}]), encoding="utf-8")
    old = run_env["xlsx"].stat().st_mtime - 100      # 上轮遗留:比本轮卷旧
    os.utime(stale, (old, old))
    out = N.run(run_env["state"])
    assert out["phase_status"] == "error"
    assert "no fresh last_run" in out["error"] and "ssh connection reset" in out["error"]


def test_run_fresh_last_run_from_this_round_accepted(run_env, monkeypatch):
    """防过修:批内复跑读**自己刚写的** last_run(digest 本轮产出,mtime≥卷)→ 照常 ok。"""
    from main.ist_core.compile_engine_v8 import nodes as N

    def _ok_digest(xlsx_path, autoids, build=""):
        (run_env["mdir"] / "last_run.json").write_text(
            json.dumps([{"autoid": a, "verdict": "pass"} for a in autoids]),
            encoding="utf-8")
        return "=== dev_run_batch_digest ===\nok"

    monkeypatch.setattr(N, "_digest_fn", _ok_digest)
    out = N.run(run_env["state"])
    assert out["phase_status"] == "ok"
    assert out["last_run_ref"] == "outputs/b1/last_run.json"


def test_run_missing_last_run_still_error(run_env, monkeypatch):
    """既有语义不动:digest 没产出且盘上无 last_run → error(带 digest 原话)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_digest_fn", lambda *a, **k: "error: framework crashed")
    out = N.run(run_env["state"])
    assert out["phase_status"] == "error"
    assert "framework crashed" in out["error"]


# ── H-18:author 的 needs_decision 判据查新鲜度(mtime≥t0,与 xlsx :497 同款) ──────
@pytest.fixture()
def author_env(tmp_path, monkeypatch):
    """author 节点夹具:S_FAILED(reflow 定向)+ 全注入点;fork 恒声明 needs_user_decision。"""
    from main.ist_core.compile_engine_v8 import _shared as sh
    from main.ist_core.compile_engine_v8 import nodes as N
    out = tmp_path / "outputs"
    mdir = out / "b1"
    (out / A).mkdir(parents=True)
    mdir.mkdir(parents=True)
    facts_file = mdir / "facts.jsonl"
    F.append_facts(facts_file, [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "subset", "result": "fail",
         "artifact": "a1", "volume": "v1", "signatures": []},
        {"ev": "attribution", "aid": A, "round": 1, "run_id": "r1", "layer": "V",
         "disposition": "reflow", "fix_direction": "x", "evidence": "y"},
    ])
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: out)
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "emit_tick", lambda *a, **k: None)
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(N.BR, "build_brief", lambda aid, state, fs: "brief")
    monkeypatch.setattr(N, "_FORK_OVERRIDE",
                        lambda skill, brief, *, tag="", effort="":
                        "worker said: 意图的验证路径在本床不存在\nSTATUS: needs_user_decision")
    return {"out": out, "facts": facts_file,
            "state": {"out_name": "b1", "run_ctx": "subset", "max_rounds": 3}}


def _write_ledger(out, stale: bool):
    import os
    p = out / A / "needs_decision.json"
    p.write_text(json.dumps({"autoid": A, "claims": [
        {"claim_kind": "distribution_algorithm", "reason": "r1 旧台账"}]}),
        encoding="utf-8")
    if stale:
        old = p.stat().st_mtime - 100
        os.utime(p, (old, old))
    return p


def test_author_stale_needs_decision_ledger_escalates_H18(author_env):
    """H-18 红绿:r1 旧台账(compile_user_decision 落盘后不删)+ r2 worker 又声明欠定
    但没写新台账——旧判据只查存在性 → 拿旧 claims 重问(worker 原文被丢弃,
    no_ledger_channel 升级被旁路);修后旧台账(mtime<t0)→ 走升级分支如实呈报。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    _write_ledger(author_env["out"], stale=True)
    N.author(author_env["state"])
    fs = F.load_facts(author_env["facts"])
    assert not [f for f in fs if f.get("ev") == "needs_decision"]
    esc = [f for f in fs if f.get("ev") == "escalated"]
    assert esc and esc[-1].get("subclass") == F.ESC_NO_LEDGER_CHANNEL
    assert "意图的验证路径在本床不存在" in esc[-1]["reason"]   # worker 原文保留


def test_author_fresh_needs_decision_ledger_accepted_H18(author_env):
    """防过修:本轮新写的台账(mtime≥t0)→ 正常 needs_decision 入账,不升级。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    _write_ledger(author_env["out"], stale=False)
    N.author(author_env["state"])
    fs = F.load_facts(author_env["facts"])
    assert [f for f in fs if f.get("ev") == "needs_decision"]
    assert not [f for f in fs if f.get("ev") == "escalated"]
