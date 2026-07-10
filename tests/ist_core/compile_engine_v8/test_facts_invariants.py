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
