"""V8 宪法测试(事实台账层):INV-3/8/10 + 权威序 + 矛盾/冻结/瞬态派生谓词。

这些不变量是 yzg 双回合实证的直接固化:
- 终验 3 fail 被吞(#10)→ deliverable 三重匹配 + reconcile 全射结局枚举;
- 子集轮 frozen 失活(#7)→ frozen 按 aid 派生,与路径无关;
- 凭证 mtime 教训 → 旧卷面裁决不为新卷面背书。
"""
from __future__ import annotations

import itertools

import pytest

from main.ist_core.compile_engine_v8.facts import (
    CTX_DELIVERY, CTX_SUBSET,
    append_facts, load_facts, dedup, idem_key,
    latest_verdict, deliverable, subset_verified,
    frozen, transient_recur, contradictions, rounds_used, reconcile,
)

A = "203600000000000001"


def V(run, ctx, result, artifact="art1", volume="vol1", sigs=None, aid=A):
    return {"ev": "verdict", "aid": aid, "run_id": run, "ctx": ctx, "result": result,
            "artifact": artifact, "volume": volume, "signatures": sigs or [],
            "bed": "10.4.127.93", "build": "10.5.0.585"}


# ── INV-8:裁决-卷面/卷组成绑定 ──────────────────────────────────────────────

def test_inv8_old_artifact_delivery_pass_never_certifies_new_artifact():
    facts = [V("r1", CTX_DELIVERY, "pass", artifact="old")]
    assert deliverable(facts, A, current_artifact="old", current_volume="vol1")
    assert not deliverable(facts, A, current_artifact="new", current_volume="vol1")


def test_inv8_volume_composition_change_invalidates_delivery_pass():
    facts = [V("r1", CTX_DELIVERY, "pass", volume="26cases")]
    assert not deliverable(facts, A, current_artifact="art1", current_volume="27cases")


def test_subset_pass_is_never_a_delivery_credential():
    facts = [V("r1", CTX_SUBSET, "pass")]
    assert subset_verified(facts, A, "art1")
    assert not deliverable(facts, A, "art1", "vol1")


# ── 权威序:高权威语境的后到裁决必须改写视图(#10 场景本体) ────────────────────

def test_authority_delivery_fail_overrides_earlier_subset_pass():
    """yzg #10 场景:子集 pass 锁死后终验 fail 被吞——V8 里终验 fail 必须翻转视图。"""
    facts = [
        V("r1", CTX_DELIVERY, "fail"),
        V("r2", CTX_SUBSET, "pass"),
        V("r3", CTX_DELIVERY, "fail", sigs=["listener miss"]),
    ]
    assert not deliverable(facts, A, "art1", "vol1")
    assert subset_verified(facts, A, "art1") is False  # 最新同卷裁决是 fail(r3)
    assert contradictions(facts, A) == 1


def test_delivery_pass_then_nothing_stays_deliverable():
    facts = [V("r1", CTX_SUBSET, "pass"), V("r2", CTX_DELIVERY, "pass")]
    assert deliverable(facts, A, "art1", "vol1")


# ── 矛盾计数(第三条 ask 边输入):卷面变更重置窗口 ────────────────────────────

def test_contradiction_counter_and_reset_on_recompile():
    facts = [
        V("r1", CTX_SUBSET, "pass"),
        V("r2", CTX_DELIVERY, "fail"),            # 矛盾 1
        V("r3", CTX_SUBSET, "pass"),
        V("r4", CTX_DELIVERY, "fail"),            # 矛盾 2 → 按裁决进 ask
    ]
    assert contradictions(facts, A) == 2
    # 重编换卷面:新窗口从零计
    facts2 = facts + [V("r5", CTX_SUBSET, "pass", artifact="art2"),
                      V("r6", CTX_DELIVERY, "fail", artifact="art2")]
    assert contradictions(facts2, A) == 3  # 全史仍可查
    only_new = [f for f in facts2 if f.get("artifact") == "art2"]
    assert contradictions(only_new, A) == 1


# ── frozen:按 aid 派生,与路径无关(#7 根治);换卷面即解冻 ─────────────────────

def test_frozen_same_signature_two_fails_same_artifact():
    facts = [
        V("r1", CTX_DELIVERY, "fail", sigs=["\\b172\\.16\\.35\\.231\\b"]),
        V("r2", CTX_SUBSET, "fail", sigs=["\\b172\\.16\\.35\\.231\\b", "extra"]),
    ]
    assert frozen(facts, A, "art1")


def test_frozen_lifts_on_new_artifact_or_new_signature():
    same = [V("r1", CTX_SUBSET, "fail", sigs=["s1"]), V("r2", CTX_SUBSET, "fail", sigs=["s2"])]
    assert not frozen(same, A, "art1")            # 签名不交=换法已生效
    recompiled = [V("r1", CTX_SUBSET, "fail", sigs=["s1"]),
                  V("r2", CTX_SUBSET, "fail", sigs=["s1"], artifact="art2")]
    assert not frozen(recompiled, A, "art2")      # 新卷面只有一条 fail


def test_transient_recur_guard_is_alive():
    facts = [
        V("r1", CTX_SUBSET, "fail"),
        {"ev": "attribution", "aid": A, "round": 1, "layer": "transient", "disposition": "env_blocked"},
        V("r2", CTX_SUBSET, "fail"),
    ]
    assert transient_recur(facts, A)
    assert not transient_recur(facts[:2], A)


# ── INV-3:fold 全函数(乱序/重复/矛盾序列均有定义结果,未知事实不炸) ───────────

def test_inv3_fold_total_under_permutation_dup_and_unknown_events():
    base = [
        V("r1", CTX_SUBSET, "pass"),
        V("r2", CTX_DELIVERY, "fail"),
        {"ev": "attribution", "aid": A, "round": 1, "layer": "V", "disposition": "reflow"},
        {"ev": "mystery_future_event", "aid": A, "x": 1},   # 前向兼容
    ]
    for perm in itertools.permutations(base):
        seq = dedup(list(perm) + list(perm))                # 重复注入
        # 全部谓词必须有定义结果,不抛
        deliverable(seq, A, "art1", "vol1")
        frozen(seq, A, "art1")
        transient_recur(seq, A)
        contradictions(seq, A)
        rounds_used(seq, A)


# ── INV-10:崩溃重放幂等(盘上双写=零重复语义) ────────────────────────────────

def test_inv10_replay_append_is_idempotent(tmp_path):
    p = tmp_path / "facts.jsonl"
    batch = [V("r1", CTX_SUBSET, "pass"),
             {"ev": "authored", "aid": A, "round": 1, "artifact": "art1"}]
    assert append_facts(p, batch) == 2
    assert append_facts(p, batch) == 0             # 重放:一条不写
    facts = load_facts(p)
    assert len(facts) == 2
    assert rounds_used(facts, A) == 1


def test_load_facts_salvages_torn_lines(tmp_path):
    p = tmp_path / "facts.jsonl"
    append_facts(p, [V("r1", CTX_SUBSET, "pass")])
    with p.open("a", encoding="utf-8") as f:
        f.write('{"ev":"verdict","aid":"20360000000')   # 被杀进程的半行
    facts = load_facts(p)
    assert len(facts) == 1                          # 坏行跳过,好账保全


# ── reconcile:全射结局枚举(oracle 残差公理执行体;INV-2 的结构化形态) ─────────

def test_reconcile_every_verdict_gets_exactly_one_outcome():
    facts = [V("r1", CTX_SUBSET, "pass")]
    incoming = [
        V("r2", CTX_DELIVERY, "fail"),              # transition(视图翻转)
        V("r2", CTX_DELIVERY, "fail"),              # duplicate(同 run 幂等)
        V("r1", CTX_SUBSET, "pass"),                # duplicate(重放)
        V("r3", CTX_DELIVERY, "fail", aid=A),       # confirm(与 r2 同结果)
    ]
    r = reconcile(facts, incoming)
    total = len(r["transition"]) + len(r["confirm"]) + len(r["duplicate"])
    assert total == len(incoming)                   # 全射:每条恰一个结局
    assert r["transition"] == [A] and r["duplicate"] == [A, A] and r["confirm"] == [A]
    assert len(r["append"]) == 2                    # 两条新事实入流


def test_reconcile_yzg_hash10_scenario_cannot_swallow():
    """终验 3 fail 场景:reconcile 后视图必须显示不可交付——名义/实测分叉在此不可能。"""
    facts = []
    # R1 整卷:pass
    r = reconcile(facts, [V("r1", CTX_DELIVERY, "pass")])
    facts += r["append"]
    assert deliverable(facts, A, "art1", "vol1")
    # 终验:fail —— V6 在此吞掉;V8 必须翻转
    r = reconcile(facts, [V("r2", CTX_DELIVERY, "fail", sigs=["s"])])
    facts += r["append"]
    assert r["transition"] == [A]
    assert not deliverable(facts, A, "art1", "vol1")


def test_reconcile_ignores_stale_records_outside_composition(tmp_path, monkeypatch):
    """语境锚回归(2026-07-10 第5轮实证):last_run.json 按 autoid 跨轮 merge,卷外案的
    陈腐记录不得被 reconcile 记成本卷裁决(终态案 655173 的上轮记录曾被记入终验卷)。"""
    import json as _json
    from main.ist_core.compile_engine_v8 import _shared as sh
    from main.ist_core.compile_engine_v8 import nodes as N
    outputs = tmp_path / "outputs"; (outputs / "b").mkdir(parents=True)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "emit_tick", lambda *a, **k: None)
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(N, "_writeback_one", lambda aid, lr, provisional=False: None)
    A, B = "209030000000000001", "209030000000000002"
    (outputs / "b" / "manifest.json").write_text(_json.dumps(
        {"cases": [{"autoid": A}, {"autoid": B}]}), encoding="utf-8")
    facts_p = outputs / "b" / "facts.jsonl"
    facts_p.write_text("\n".join(_json.dumps(f) for f in [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "authored", "aid": B, "round": 1, "artifact": "b1"},
        {"ev": "merged", "aid": "", "volume": "volX", "ctx": "delivery",
         "composition": [A], "run_id": "m1"},          # 本卷只有 A
    ]) + "\n", encoding="utf-8")
    (outputs / "b" / "last_run.json").write_text(_json.dumps([
        {"autoid": A, "verdict": "pass"},
        {"autoid": B, "verdict": "fail"},               # B 的陈腐记录(跨轮 merge 遗留)
    ]), encoding="utf-8")
    state = {"out_name": "b", "manifest_ref": "outputs/b/manifest.json",
             "facts_ref": "outputs/b/facts.jsonl",
             "merged_ref": "outputs/b/case.xlsx", "run_ctx": "delivery",
             "last_run_ref": "outputs/b/last_run.json"}
    N.reconcile(state)
    fs2 = [_json.loads(l) for l in facts_p.read_text().splitlines() if l.strip()]
    vs = [f for f in fs2 if f["ev"] == "verdict"]
    assert [v["aid"] for v in vs] == [A]                # B 的幽灵裁决被拒之门外


def test_pid_stamp_excluded_from_idempotency(tmp_path):
    """写入者审计字段 _pid 不入幂等键——跨进程续跑重放同一事实仍去重(僵尸跨写取证 #61)。"""
    import os
    from main.ist_core.compile_engine_v8.facts import append_facts, load_facts, idem_key
    p = tmp_path / "facts.jsonl"
    f = {"ev": "bed_checked", "aid": "", "host": "h", "findings": []}
    assert append_facts(p, [dict(f)]) == 1
    assert append_facts(p, [dict(f)]) == 0            # 同内容重放:去重
    got = load_facts(p)
    assert len(got) == 1 and got[0].get("_pid") == os.getpid()
    other = {**f, "_pid": 99999}                       # 模拟另一进程写的同一事实
    assert idem_key(other) == idem_key(got[0])         # 键不含 _pid


# ── P0 修复回归族(批3 yzg 668 族:二次欠定 qid 碰撞被吞) ─────────────────────────

def test_p0_a_distinct_kinds_persist():
    """a) 复现锚:同案两轮不同 kind 的 needs_decision 都入账(修前碰撞被吞)。
    round1(0 decision,forbidden_mechanism)/round2(1 decision=adopted 后,
    verification_path_absent)。"""
    from main.ist_core.compile_engine_v8.nodes import _needs_decision_qid
    nd_f = {"claim_kind": "forbidden_mechanism", "claims": [{"claim_kind": "forbidden_mechanism"}]}
    nd_v = {"claim_kind": "verification_path_absent", "claims": [{"claim_kind": "verification_path_absent"}]}
    q1 = _needs_decision_qid("A", [], nd_f)
    q2 = _needs_decision_qid("A", [{"ev": "decision", "aid": "A"}], nd_v)
    assert q1 != q2
    n1 = {"ev": "needs_decision", "aid": "A", "question_id": q1}
    n2 = {"ev": "needs_decision", "aid": "A", "question_id": q2}
    assert idem_key(n1) != idem_key(n2)
    assert len(dedup([n1, n2])) == 2


def test_p0_b_replay_same_round_deduped_inv10():
    """b) 幂等回归锚(INV-10):同轮崩溃重放→decision 数不变→nd_seq 稳定→同 qid→去重。
    判别子用 decision-count 而非 needs_decision-count:后者会被重放已落盘的 nd 抬高
    →新 qid→重复破 INV-10。本测试锁 decision-count 的重放稳定性。"""
    from main.ist_core.compile_engine_v8.nodes import _needs_decision_qid
    nd_f = {"claim_kind": "forbidden_mechanism", "claims": [{"claim_kind": "forbidden_mechanism"}]}
    q_first = _needs_decision_qid("A", [], nd_f)
    # 重放:fs 现含首次已落盘的 needs_decision,但 decision 仍 0
    mine_replay = [{"ev": "needs_decision", "aid": "A", "question_id": q_first}]
    assert _needs_decision_qid("A", mine_replay, nd_f) == q_first
    n = {"ev": "needs_decision", "aid": "A", "question_id": q_first}
    assert len(dedup([n, dict(n)])) == 1


def test_p0_c_second_underdetermination_routes_awaiting():
    """c) 路由锚:首轮欠定被 decision 配对 answered 后,二次不同 kind 欠定入账→
    case_status=S_AWAITING_USER(gather 会问),非被首轮 decision 误配对→S_PENDING→closing。"""
    from main.ist_core.compile_engine_v8 import views as V
    q1, q2 = "nd:A:1:forbidden_mechanism", "nd:A:2:verification_path_absent"
    fs = [
        {"ev": "needs_decision", "aid": "A", "question_id": q1},
        {"ev": "decision", "aid": "A", "question_id": q1, "answer": "改过程"},
        {"ev": "needs_decision", "aid": "A", "question_id": q2},
    ]
    assert V.case_status(fs, "A", "", "") == V.S_AWAITING_USER


def test_p0_d_cross_round_same_kind_new_question():
    """d) 设计语义锚(leader 令):跨轮同 kind→decision+1→nd_seq+1→新 qid→入账新问题。
    宪法优先级:上轮裁决没解决该 kind 的问题就该再问——宁可重复问询,不可吞裁决
    (吞裁决在结构上不可能=宪法承诺)。"""
    from main.ist_core.compile_engine_v8.nodes import _needs_decision_qid
    nd = {"claim_kind": "forbidden_mechanism", "claims": [{"claim_kind": "forbidden_mechanism"}]}
    q1 = _needs_decision_qid("A", [], nd)
    q2 = _needs_decision_qid("A", [{"ev": "decision", "aid": "A"}], nd)  # 同 kind,轮次推进
    assert q1 != q2
    n1 = {"ev": "needs_decision", "aid": "A", "question_id": q1}
    n2 = {"ev": "needs_decision", "aid": "A", "question_id": q2}
    assert len(dedup([n1, n2])) == 2


def test_p0_compat_old_qid_coexists_batch3_resume():
    """兼容专项(leader 令,批3续跑不炸账):已交付 facts 的旧 qid(nd:aid:1)与新格式并存——
    旧 needs_decision 仍被旧 decision 配对(不受影响);续跑产的新格式 needs_decision
    (decision-count→nd:aid:2:kind)未答→案 awaiting→被问。旧答案不误清,新问题不被吞。"""
    from main.ist_core.compile_engine_v8.nodes import _needs_decision_qid
    from main.ist_core.compile_engine_v8 import views as V
    old_q = "nd:A:1"   # 旧格式(已交付批)
    mine = [
        {"ev": "needs_decision", "aid": "A", "question_id": old_q},
        {"ev": "decision", "aid": "A", "question_id": old_q, "answer": "改过程"},
    ]
    nd_v = {"claim_kind": "verification_path_absent", "claims": [{"claim_kind": "verification_path_absent"}]}
    new_q = _needs_decision_qid("A", mine, nd_v)   # decision 数=1 → nd_seq=2,新格式
    assert new_q != old_q and new_q == "nd:A:2:verification_path_absent"
    fs = mine + [{"ev": "needs_decision", "aid": "A", "question_id": new_q}]
    assert V.case_status(fs, "A", "", "") == V.S_AWAITING_USER


def test_p0_g_long_multikind_qid_truncation_keeps_nd_seq_no_collision():
    """g) M-1 结构锚(leader 令):超长多 kind qid 在 `[:120]` 截断窗内仍保差异化。
    截断归属精确化(redline 勘定):needs_decision 自身走内容键不截断;`[:120]` 是
    **decision 事实**幂等键对 question_id 的截断——nd_seq 置于 aid 后、ck 前,保证
    两轮 decision 引用的 qid 前 120 字符即已不同。对照锁死:同数据按旧序
    `nd:aid:ck:nd_seq` 时 ck 撑长会把 nd_seq 挤出 120→decision 键截断成同键(批3
    蒸发在长 qid 的复发面)。M-1 把锚放截断安全区,比「确认恒<120」的假设更硬。"""
    from main.ist_core.compile_engine_v8.nodes import _needs_decision_qid
    aid = "203601753067668000"
    kinds = ["forbidden_mechanism", "verification_path_absent", "distribution_algorithm",
             "position_algorithm", "rotation_algorithm", "zero_information_assertion"]
    nd = {"claims": [{"claim_kind": k} for k in kinds]}
    q1 = _needs_decision_qid(aid, [], nd)                                # nd_seq=1
    q2 = _needs_decision_qid(aid, [{"ev": "decision", "aid": aid}], nd)  # nd_seq=2
    assert len(q1) > 120 and len(q2) > 120           # 截断确实发生(否则测不到 M-1)
    # 承重点:配对 decision 事实走 [:120] 截断键(facts.py decision 分支)——M-1 后两轮差异化
    d1 = {"ev": "decision", "aid": aid, "question_id": q1}
    d2 = {"ev": "decision", "aid": aid, "question_id": q2}
    assert idem_key(d1) != idem_key(d2)              # decision 截断键差异化(M-1 保护点)
    assert len(dedup([d1, d2])) == 2                 # 两轮裁决都落账,无蒸发
    # 对照锁死:同数据旧序 decision 经 idem_key [:120] 截断成同键→碰撞(nd_seq 被 ck 挤出
    # 窗)——M-1 必要性。这里走真 idem_key(非裸切片),锁的正是 decision 幂等键退化。
    ck = "+".join(sorted(kinds))
    old1, old2 = f"nd:{aid}:{ck}:1", f"nd:{aid}:{ck}:2"
    assert idem_key({"ev": "decision", "aid": aid, "question_id": old1}) == \
           idem_key({"ev": "decision", "aid": aid, "question_id": old2})
    # 正交层:needs_decision 自身走内容键(不截断)→ P0 nd_seq 差异化已足,与截断无关
    assert idem_key({"ev": "needs_decision", "aid": aid, "question_id": q1}) != \
           idem_key({"ev": "needs_decision", "aid": aid, "question_id": q2})
