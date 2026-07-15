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
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: None)
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
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: None)
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
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: None)
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


# ── pyATS 七码子分类(§18.1/DESIGN_dongkl_finalization §④):Errored→reflow / Blocked→env ──
def _vb(result, sub=None, **kw):
    v = _v(result, **kw)
    if sub is not None:
        v["broken_subtype"] = sub
    return v


def test_fold_broken_errored_derives_state():
    """协议级硬码 broken_subtype=errored → S_BROKEN_ERRORED(断言被反证/执行错→reflow)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _vb("broken", sub="errored")]
    vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
    assert vw["cases"][A]["status"] == V.S_BROKEN_ERRORED
    assert vw["counts"].get(V.S_BROKEN_ERRORED) == 1


def test_fold_broken_blocked_derives_state():
    """broken_subtype=blocked → S_BROKEN_BLOCKED(设备不可达→env 呈报)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _vb("broken", sub="blocked")]
    vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
    assert vw["cases"][A]["status"] == V.S_BROKEN_BLOCKED


def test_fold_broken_no_subtype_stays_plain_broken():
    """未打 subtype(not_run/stale/协议级分不清)→ 安全默认 S_BROKEN(复跑)。"""
    for sub in (None, ""):
        fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
              _vb("broken", sub=sub)]
        vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
        assert vw["cases"][A]["status"] == V.S_BROKEN, sub


def test_route_broken_errored_to_attribute_then_author():
    """Errored 路由:reconcile→attribute(跳已归因)→diagnose→author 重写。"""
    from main.ist_core.compile_engine_v8.graph import _after_reconcile, _after_diagnose
    assert _after_reconcile({"n_broken_errored": 1}) == "attribute"
    assert _after_diagnose({"n_broken_errored": 1}) == "author"


def test_reconcile_errored_writes_mechanical_reflow(rec_env, monkeypatch):
    """digest 打 broken_subtype=errored → reconcile 落**机械** reflow 归因(不调 LLM),
    派生态 S_BROKEN_ERRORED → author 据 disposition=reflow 重写(不空跑同一缺陷)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: None)
    rec_env["lr"].write_text(json.dumps([
        {"autoid": A, "verdict": "broken", "broken_subtype": "errored",
         "broken_reason": "assertion-window distortion: A Record Statistics: 1"}]),
        encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    atts = [f for f in fs if f.get("ev") == "attribution"]
    assert atts and atts[-1]["disposition"] == "reflow"
    assert atts[-1].get("mechanical") is True and atts[-1].get("layer") == "E"
    vw = V.batch_view(fs, {"cases": [{"autoid": A, "title": "案A"}]})
    assert vw["cases"][A]["status"] == V.S_BROKEN_ERRORED


def test_reconcile_blocked_writes_env_and_surfaces(rec_env, monkeypatch):
    """broken_subtype=blocked → 机械 env_blocked 归因 → 进 env 确认问询(呈报,不空跑死设备)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: None)
    rec_env["lr"].write_text(json.dumps([
        {"autoid": A, "verdict": "broken", "broken_subtype": "blocked",
         "broken_reason": "device unreachable (ping 100% loss from jumphost)"}]),
        encoding="utf-8")
    out = N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    atts = [f for f in fs if f.get("ev") == "attribution"]
    assert atts and atts[-1]["disposition"] == "env_blocked"
    assert atts[-1].get("mechanical") is True
    assert out.get("n_ask_contradiction", 0) >= 1   # 进 env 呈报集


# ── 回归#2 修:broken liveness(per-case streak + 卷指纹隔离)——欠定必问的前提 ──
def test_broken_streak_per_case_escalates_across_reflow(rec_env, monkeypatch):
    """治 yzg 活锁:同 case 连续未跑成跨 reflow(不同 artifact)也要 escalated——
    per-artifact 计数会被 reflow 换 artifact 重置成 1、永不升级 → 非收敛 broken 恒占
    live 饿死 gather。改 per-case 累计:art a0 broken + art a1 broken = 2 → escalated。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: None)
    # 上一轮 reflow 的 artifact a0 上已 not_run 一次
    F.append_facts(rec_env["facts"], [_v("not_run", rid="prev", art="a0")])
    # 本轮(artifact_fingerprint 夹具=a1)又 not_run —— per-artifact 各 1、per-case 2
    rec_env["lr"].write_text(json.dumps([{"autoid": A, "verdict": "unknown"}]),
                             encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    esc = [f for f in fs if f.get("ev") == "escalated"]
    assert esc and "consecutive" in esc[-1]["reason"], "跨 reflow 的连续未跑成未升级(仍 per-artifact)"


def test_delivery_pass_survives_subsequent_subset_merge():
    """治卷 churn 假 live:案 pass@delivery(volA)后,别案的 broken 子集复跑产生
    subset merge(volB)不该把它从 deliverable 降级回 subset_verified(否则 17 pass
    案恒占 live 饿死 gather)。current_volume 只跟 **delivery** 卷走。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "merged", "aid": "", "volume": "volA", "ctx": "delivery",
           "composition": [A]},
          _v("pass", ctx="delivery", art="a1", vol="volA"),
          # 别案的 broken 子集复跑:subset merge 换了最新 merge 卷指纹
          {"ev": "merged", "aid": "", "volume": "volB", "ctx": "subset",
           "composition": ["203600000000000002"]}]
    vw = V.batch_view(fs, {"cases": [{"autoid": A}]})
    assert vw["cases"][A]["status"] == V.S_DELIVERABLE, \
        "delivery-pass 案被后续 subset merge 的卷指纹 churn 降级(current_volume 跟了 subset 卷)"


def test_errored_broken_not_counted_by_frozen():
    """errored 是 broken 子类:frozen 仍不看它((44):broken 不构成同法证伪证据)。
    fail(SIG)→broken-errored(SIG)→fail(SIG):中间 broken 轮被跳过,前后两 fail
    同签名 → 仍 frozen(与 test_frozen_ignores_broken_rounds 同型);纯 broken-errored
    序列不 frozen(没跑成≠证伪)。"""
    fs = [_v("fail", rid="r1", sigs=["SIG"]),
          _vb("broken", sub="errored", rid="r2", sigs=["SIG"]),
          _v("fail", rid="r3", sigs=["SIG"])]
    assert F.frozen(fs, A, "a1") is True
    fs2 = [_vb("broken", sub="errored", rid="r1", sigs=["SIG"]),
           _vb("broken", sub="errored", rid="r2", sigs=["SIG"])]
    assert F.frozen(fs2, A, "a1") is False


def test_errored_reflow_repeated_failure_escalates_via_streak(rec_env, monkeypatch):
    """S3-R2(MEDIUM 批·regression 矩阵)复测:errored 反复失败的**终止链**。errored 走
    author reflow(S_BROKEN_ERRORED),auditor 疑其绕过 streak 两轮止损。但 per-case streak
    (回归#2 修)计的是 `result`(errored 的 verdict=broken → result=broken),故 errored
    反复失败**也**累计 streak。此锚验:同 case 连续 errored 跨 reflow(换 artifact)→
    streak≥2 → escalated,不无限 churn 到 cap(与 test_broken_streak_per_case_escalates_
    across_reflow 互补:那条测 plain not_run,这条专测 errored 子类)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    monkeypatch.setattr(N, "_writeback_one", lambda aid, ref, provisional=False: None)
    # 上一轮 reflow 的 artifact a0 上已 errored 一次(result=broken)
    F.append_facts(rec_env["facts"],
                   [_vb("broken", sub="errored", rid="prev", art="a0")])
    # 本轮(fixture artifact_fingerprint=a1)又 errored → per-case result=broken ×2 → 应 escalated
    rec_env["lr"].write_text(json.dumps([
        {"autoid": A, "verdict": "broken", "broken_subtype": "errored",
         "broken_reason": "assertion-window distortion (repeat)"}]), encoding="utf-8")
    N.reconcile(rec_env["state"])
    fs = F.load_facts(rec_env["facts"])
    esc = [f for f in fs if f.get("ev") == "escalated"]
    assert esc and "consecutive" in esc[-1]["reason"], \
        "errored 反复失败跨 reflow 未升级——streak 未覆盖 errored 子类(S3-R2 未防住)"
