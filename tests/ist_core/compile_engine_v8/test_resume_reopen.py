# -*- coding: utf-8 -*-
"""#37 resume 重开欠定守门（存量路由缺口修 9d59c08f）。

D18 真根因（#36 实证,facts+code 双面）：resume「恢复处理」只写 resumed 事件 → 案挂起解除变
S_PENDING,但图路由 `_after_ask_contradiction` 无 author 出口 + 案无未答欠定（旧 nd 被裁决「答过」)
→ closing、本轮零 re-author/零 needs_decision 重生成 → 旧毒 改描述 decision 原封管命运、案卡死
（668 族 7 案 decision_outcome 全 effective=false）。

修法：欠定类挂起（改描述/未获答自动挂起）的 resume 追加新 qid needs_decision → 案转
S_AWAITING_USER → 路由回 gather → shape-fix 下用户被正常问 → 采纳落。keep/env 不重开（边界①）。
红绿：修前（只 resumed）case_status=S_PENDING（路由 closing）;修后（加 fresh nd）=S_AWAITING_USER。
"""
from __future__ import annotations

import json
import shutil

import pytest

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8.facts import append_facts, load_facts

A = "203601753067668000"   # #36 实证卡死案(668000)


def _mk_ledger(aid=A, claims=None):
    d = sh.outputs_root() / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "needs_decision.json").write_text(json.dumps(
        {"autoid": aid, "claims": claims if claims is not None else
         [{"claim_kind": "verification_path_absent", "test_point": "write mem 后重启 listener 应丢失"}]},
        ensure_ascii=False), encoding="utf-8")


@pytest.fixture(autouse=True)
def _clean():
    shutil.rmtree(sh.outputs_root() / A, ignore_errors=True)
    yield
    shutil.rmtree(sh.outputs_root() / A, ignore_errors=True)


def _base(reason="user_decision:改描述"):
    """#36 668000 形态:改描述(adopted)挂起 → resumed。"""
    return [
        {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:1:verification_path_absent"},
        {"ev": "decision", "aid": A, "question_id": f"nd:{A}:1:verification_path_absent",
         "answer": "改描述", "provenance": "adopted:eq--forbidden-mechanism--10-5"},
        {"ev": "suspended", "aid": A, "reason": reason},
        {"ev": "resumed", "aid": A, "of": f"resume:{A}:2"},
    ]


def test_reopen_underdetermined_gaimiaoshu():
    """改描述挂起(欠定类)的 resume → 追加新 qid needs_decision + ⓐ 上次裁决上下文。"""
    _mk_ledger()
    nd = N._resume_reopen_needs_decision(A, _base("user_decision:改描述"))
    assert nd is not None and nd["ev"] == "needs_decision"
    assert nd["question_id"] == f"nd:{A}:2:verification_path_absent"   # nd_seq 递增(1 decision→2)
    assert nd["reopened"]["prev_decision"] == "改描述"                 # ⓐ 载荷


def test_reopen_auto_suspension():
    """未获答案自动挂起(auto: ∧ 原 kind∈{panel,cap,contra},欠定未决)也重开。"""
    _mk_ledger()
    assert N._resume_reopen_needs_decision(A, _base(f"auto:cap:{A}:1")) is not None


def test_no_reopen_for_keep_boundary():
    """边界①:keep(用户显式保持挂起)不重开。"""
    _mk_ledger()
    assert N._resume_reopen_needs_decision(A, _base("keep:resume:x:2")) is None


def test_no_reopen_without_ledger_claims():
    """无欠定账本 claims → 无处可问,不重开(不空转)。"""
    _mk_ledger(claims=[])
    assert N._resume_reopen_needs_decision(A, _base("user_decision:改描述")) is None


def test_reopen_flips_case_to_awaiting_user_RED_GREEN():
    """★红绿守门:修前(只 resumed)→S_PENDING(路由 closing、卡死);修后(加 fresh nd)→
    S_AWAITING_USER(路由回 gather)。这条断言直接锁 D18 真根因。"""
    _mk_ledger()
    base = _base()
    assert V.case_status(base, A, "", "") == V.S_PENDING              # 红:resumed 后卡 S_PENDING
    nd = N._resume_reopen_needs_decision(A, base)
    assert V.case_status(base + [nd], A, "", "") == V.S_AWAITING_USER  # 绿:重开→回 gather
    # 新 qid 确未撞已答(旧 nd:1 已被改描述答过)→ 才算「未答欠定」触发 gather
    answered = {f["question_id"] for f in base if f.get("ev") == "decision"}
    assert nd["question_id"] not in answered


def test_theory_qid_seq_increases_and_not_deduped(tmp_path):
    """Theory 审②暗礁守门:①新 nd qid seq 严格 > 旧(递增可见,否则 (48) 幂等键碰撞)
    ②新 nd 事实经真实 append_facts/load_facts **未被 (48) 静默吞**(隐式压盖的 crux)。"""
    _mk_ledger()
    base = _base()
    nd = N._resume_reopen_needs_decision(A, base)
    old_seq = int(f"nd:{A}:1:verification_path_absent".split(":")[2])   # =1
    new_seq = int(str(nd["question_id"]).split(":")[2])
    assert new_seq > old_seq, f"新 seq {new_seq} 未 > 旧 {old_seq}——会被 (48) 幂等吞"
    # ② 真实 append/load:fresh nd 未被内容键去重吞(qid+reopened 皆异于旧 nd:1)
    p = tmp_path / "facts.jsonl"
    append_facts(p, base)
    assert append_facts(p, [nd]) == 1, "fresh nd 被 (48) 幂等去重吞了(暗礁复现)"
    loaded = load_facts(p)
    assert any(f.get("ev") == "needs_decision"
               and f.get("question_id") == nd["question_id"] for f in loaded), "fresh nd 未落 facts"


def test_predicate_auto_env_bed_not_reopened():
    """Design ① 精确谓词:auto:∧{env,bed}(外部因素未变)不重开;auto:∧{panel,cap,contra}重开。"""
    _mk_ledger()
    assert N._resume_reopen_needs_decision(A, _base(f"auto:env:{A}:1")) is None      # env 不重开
    assert N._resume_reopen_needs_decision(A, _base(f"auto:bed:{A}:1")) is None      # bed 不重开
    assert N._resume_reopen_needs_decision(A, _base(f"auto:contra:{A}:1")) is not None  # contra 重开
    assert N._resume_reopen_needs_decision(A, _base(f"auto:panel:{A}:1")) is not None   # panel 重开
