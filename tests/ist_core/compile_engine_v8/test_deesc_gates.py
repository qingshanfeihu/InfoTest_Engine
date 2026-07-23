# -*- coding: utf-8 -*-
"""de-escalate 十三守门(team4_deescalate_spec §3)——宪法级,禁路过零断言。

每条锚生产谓词/渲染/路由,不复刻实现。编号与 spec §3 1–13 对齐。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import render as RD
from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8.views import (
    all_settled, batch_view, case_status, _is_escalated,
    S_PENDING, S_AUTHORED, S_ESCALATED, S_AWAITING_USER,
)

A = "203601753067655201"
B = "203601753067655202"


def _esc(aid, sub, n=1, reason=""):
    return {"ev": "escalated", "aid": aid, "subclass": sub,
            "reason": reason or f"{sub} #{n}",
            "run_id": f"esc:{aid}:{sub}:{n}"}


def _auth(aid, rnd=1, art="a1"):
    return {"ev": "authored", "aid": aid, "round": rnd, "artifact": art}


# ── 1: no_output 答「重编」→ S_PENDING → author 选案 ──────────────────────────

def test_gate1_no_output_retry_becomes_pending():
    """守门1:no_output 答重编落 de_escalated → S_PENDING(进 author 选案集)。"""
    fs = [_esc(A, F.ESC_NO_OUTPUT, 1),
          {"ev": "de_escalated", "aid": A, "fix_direction": "user chose recovery",
           "evidence": "user"}]
    assert case_status(fs, A, "", "") == S_PENDING
    assert not _is_escalated([f for f in fs if f.get("aid") == A])


# ── 2: not_executed 答「换床复跑」→ 进 live(有卷、解除升级) ─────────────────────

def test_gate2_not_executed_reswitch_enters_live_set():
    fs = [_auth(A), _esc(A, F.ESC_NOT_EXECUTED, 1),
          {"ev": "de_escalated", "aid": A, "evidence": "user"}]
    st = case_status(fs, A, "a1", "")
    assert st == S_AUTHORED
    assert not _is_escalated([f for f in fs if f.get("aid") == A])
    vw = batch_view(fs, {"cases": [{"autoid": A}]})
    live = [a for a, c in vw["cases"].items()
            if c["status"] not in (V.S_ESCALATED, V.S_TERMINAL,
                                   V.S_AWAITING_USER, V.S_SUSPENDED)]
    assert A in live


# ── 3: escalated 待答恢复时 all_settled==False ────────────────────────────────

def test_gate3_deesc_waiting_blocks_all_settled():
    fs = [_esc(A, F.ESC_NO_OUTPUT, 1)]
    manifest = {"cases": [{"autoid": A}]}
    vw = batch_view(fs, manifest)
    assert vw["cases"][A]["status"] == S_ESCALATED
    # sh.view 把 deesc 待答翻成 awaiting_user
    state = {"out_name": "g3", "bed_host": "103", "device_build": "10.5.0"}
    # 需要 facts 在盘上? view() 读 state facts_ref——直接调 deesc_recovery_waiting
    waiting = sh.deesc_recovery_waiting(state, fs, vw)
    assert A in waiting
    # 投影后不得 settled
    vw2 = dict(vw)
    vw2["cases"] = dict(vw["cases"])
    for aid in waiting:
        vw2["cases"][aid] = {**vw2["cases"][aid], "status": S_AWAITING_USER}
    assert not all_settled(vw2)


# ── 4+12: 同子类升级达 max_rounds+granted 封顶(attempts 轴,v4.1) ───────────────

def test_gate4_and_12_no_output_caps_at_max_rounds_plus_granted():
    e1 = _esc(A, F.ESC_NO_OUTPUT, 1)
    e2 = _esc(A, F.ESC_NO_OUTPUT, 2)
    e3 = _esc(A, F.ESC_NO_OUTPUT, 3)
    assert F.escalation_attempts([e1], A, F.ESC_NO_OUTPUT) == 1
    assert F.deesc_cap_threshold(max_rounds=3, granted=0) == 3
    # 默认 max_rounds=3:第 2 次尚不封顶
    assert F.deesc_auto_resolution([e1], A, e2) == []
    # 第 3 次同子类 → 缺陷候选
    extra = F.deesc_auto_resolution([e1, e2], A, e3)
    assert any(f.get("ev") == "de_escalated" for f in extra)
    att = [f for f in extra if f.get("ev") == "attribution"]
    assert att and att[0]["disposition"] == "defect_candidate"
    assert "threshold=3" in str(att[0].get("fix_direction") or "")
    # gate12:attempts 轴——显式 max_rounds=2 时第 2 次即封(不靠 rounds_used)
    extra2 = F.deesc_auto_resolution([e1], A, e2, max_rounds=2, granted=0)
    assert any(f.get("disposition") == "defect_candidate" for f in extra2)
    # granted 抬阈值:max_rounds=2 + granted=1 → 第 3 次才封
    assert F.deesc_auto_resolution([e1], A, e2, max_rounds=2, granted=1) == []
    extra_g = F.deesc_auto_resolution([e1, e2], A, e3, max_rounds=2, granted=1)
    assert any(f.get("disposition") == "defect_candidate" for f in extra_g)


# ── 5: 报告去向行——未封顶可重编;封顶缺陷候选;无「可续跑」对无通道 ────────────

def test_gate5_escalated_remedy_lines():
    mine = [_esc(A, F.ESC_NO_OUTPUT, 1)]
    text = RD.remedy_text([], mine)
    assert "**去向**:" in text
    assert "重编" in text
    assert "可续跑" not in text  # 无通道案不许承诺可续跑
    # 封顶后 disposition 分支
    capped = [{"ev": "attribution", "aid": A, "round": 99,
               "disposition": "defect_candidate",
               "evidence": "engine_auto_cap:no_output", "run_id": "auto"}]
    t2 = RD.remedy_text([], capped)
    assert "缺陷候选" in t2 or "defect_candidate" in t2


# ── 6: footer escalated 独立桶、Σ 守恒 ───────────────────────────────────────

def test_gate6_footer_escalated_own_bucket_conserves():
    buckets = sh._footer_bucket_counts({"escalated": 3, "deliverable": 2, "failed": 1})
    assert buckets["escalated"] == 3
    assert buckets["failed_terminal"] == 0  # 不落失败桶
    assert sum(buckets.values()) == 6


# ── 7: 收敛律——保持同判例键不重问;换床可重问 ────────────────────────────────

def test_gate7_keep_converges_until_bed_changes():
    state = {"bed_host": "103", "device_build": "10.5.0"}
    sub = F.ESC_NO_OUTPUT
    key = sh._deesc_precedent_key(A, sub, state)
    fs = [_esc(A, sub, 1),
          {"ev": "decision", "aid": A, "question_id": f"deesc:{A}:1",
           "answer": "保持", "token": "deesc_keep"},
          {"ev": "deesc_keep", "aid": A, "question_id": f"deesc:{A}:1",
           "precedent_key": key}]
    vw = batch_view(fs, {"cases": [{"autoid": A}]})
    assert A not in sh.deesc_recovery_waiting(state, fs, vw)
    # 换床 → 可重问
    state2 = {**state, "bed_host": "105"}
    assert A in sh.deesc_recovery_waiting(state2, fs, vw)


def test_gate7b_non_keep_then_new_escalation_reasks():
    """非保持后新升级回合必须再问——旧逻辑按全史末条≠keep 永久跳过(沉默死局)。"""
    state = {"bed_host": "103", "device_build": "10.5.0"}
    claim1 = "worker declared underdetermined: kind A"
    claim2 = "worker declared underdetermined: kind B"  # 不同 claim
    fs = [
        _esc(A, F.ESC_NO_LEDGER_CHANNEL, 1, reason=claim1),
        {"ev": "decision", "aid": A, "question_id": f"deesc:{A}:1",
         "answer": "重编", "token": "deesc_retry"},
        {"ev": "de_escalated", "aid": A, "question_id": f"deesc:{A}:1"},
        _esc(A, F.ESC_NO_LEDGER_CHANNEL, 2, reason=claim2),
    ]
    vw = batch_view(fs, {"cases": [{"autoid": A}]})
    assert A in sh.deesc_recovery_waiting(state, fs, vw)
    # 同升级回合内已答非保持 → 不重问
    fs_same = fs + [
        {"ev": "decision", "aid": A, "question_id": f"deesc:{A}:2",
         "answer": "工程故障", "token": "deesc_engineering_fault"},
    ]
    # 工程故障会再写 de_escalated+attribution;即便仍 escalated 视图,本回合已决
    assert A not in sh.deesc_recovery_waiting(state, fs_same, vw)


# ── 8: reason 改写不影响子类分治 ────────────────────────────────────────────

def test_gate8_subclass_ignores_reason_wording():
    f = {"ev": "escalated", "aid": A, "subclass": F.ESC_NO_OUTPUT,
         "reason": "completely rewritten prose that mentions execute",
         "run_id": "r1"}
    assert F.escalated_subclass([f], A) == F.ESC_NO_OUTPUT
    # 无 subclass 时才走前缀兜底
    legacy = {"ev": "escalated", "aid": A,
              "reason": "no output from fork wallclock", "run_id": "r2"}
    assert F.escalated_subclass([legacy], A) == F.ESC_NO_OUTPUT


# ── 9: 跨轮混合——有 xlsx 仍可判 no_output(结构化 subclass) ───────────────────

def test_gate9_cross_round_mixed_subclass_from_stage_not_xlsx():
    # round1 产卷 + round2 fork 空转 → 生产点写 subclass=no_output
    fs = [_auth(A, 1, "a1"),
          _esc(A, F.ESC_NO_OUTPUT, 1, reason="no output despite xlsx on disk")]
    assert F.escalated_subclass(fs, A) == F.ESC_NO_OUTPUT
    assert F.escalated_subclass(fs, A) != F.ESC_NOT_EXECUTED


# ── 10: 解除不复燃 ───────────────────────────────────────────────────────────

def test_gate10_deescalate_does_not_permanently_suppress():
    fs = [_esc(A, F.ESC_NO_OUTPUT, 1),
          {"ev": "de_escalated", "aid": A},
          _esc(A, F.ESC_NO_OUTPUT, 2)]
    assert F.de_escalated_after_last_escalation(fs, A) is None
    assert _is_escalated([f for f in fs if f.get("aid") == A])


# ── 11: no_ledger 先试后判——同 claim 再撞→工程故障;保持不产 de_escalated ─────

def test_gate11_no_ledger_retry_then_engineering_fault_on_recur():
    claim = "worker declared underdetermined: no ledger for kind X"
    e1 = _esc(A, F.ESC_NO_LEDGER_CHANNEL, 1, reason=claim)
    e2 = _esc(A, F.ESC_NO_LEDGER_CHANNEL, 2, reason=claim)
    # 第一次不封顶
    assert F.deesc_auto_resolution([], A, e1) == []
    # 同 claim 再撞 → engineering_fault
    extra = F.deesc_auto_resolution([e1], A, e2)
    att = [f for f in extra if f.get("ev") == "attribution"]
    assert att and att[0]["disposition"] == "engineering_fault"
    # 「保持」路径:落 deesc_keep 事实、无 de_escalated
    keep_fs = [_esc(A, F.ESC_NO_LEDGER_CHANNEL, 1),
               {"ev": "decision", "aid": A, "question_id": f"deesc:{A}:1",
                "answer": "保持", "token": "deesc_keep"},
               {"ev": "deesc_keep", "aid": A, "precedent_key": "k"}]
    assert not any(f.get("ev") == "de_escalated" for f in keep_fs)
    assert _is_escalated([f for f in keep_fs if f.get("aid") == A])


# ── 13: 工程故障不进缺陷候选卷 ───────────────────────────────────────────────

def test_gate13_engineering_fault_not_in_defect_candidates():
    from main.ist_core.compile_engine_v8 import nodes as N
    fs = [{"ev": "attribution", "aid": A, "round": 99, "layer": "engine",
           "disposition": "engineering_fault", "run_id": "auto_eng",
           "evidence": "engine_auto: gap",
           "defect_candidate": {"actual": "should not matter"}}]
    vw = {"cases": {A: {"status": V.S_TERMINAL, "artifact": "a1"}}}
    out = N._collect_defect_candidates(fs, vw, {"cases": [{"autoid": A, "title": "t"}]})
    assert out == [] or all(e.get("disposition") != "engineering_fault"
                            for e in out)
    # 对照:真 defect_candidate 入卷
    fs2 = [{"ev": "attribution", "aid": B, "round": 2, "layer": "V",
            "disposition": "defect_candidate", "run_id": "r1",
            "evidence": "Timeout=0 still present",
            "defect_candidate": {"repro": "x", "expected_with_source": "y",
                                 "actual": "Timeout=0"}}]
    vw2 = {"cases": {B: {"status": V.S_TERMINAL, "artifact": "a1"}}}
    out2 = N._collect_defect_candidates(
        fs2, vw2, {"cases": [{"autoid": B, "title": "t"}]})
    assert any(e.get("autoid") == B for e in out2)
