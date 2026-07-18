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


def _drive_ask_decision(monkeypatch, facts):
    """驱动 ask_decision 捕获呈报题面(隔离判例店防采纳抢先;interrupt 返空不落)。"""
    import tempfile, pathlib
    from main.ist_core.tools.knowledge import adjudication_store as adj
    monkeypatch.setattr(adj, "adjudications_root",
                        lambda: pathlib.Path(tempfile.mkdtemp()) / "adj")
    asked = []
    monkeypatch.setattr(sh, "load_facts", lambda st: facts)
    monkeypatch.setattr(sh, "append", lambda st, fx: None)
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "counts_update", lambda st, f=None: {})
    monkeypatch.setattr(N, "interrupt", lambda p: (asked.append(p.get("questions", [])) or {}))
    N.ask_decision({"product_version": "10.5", "out_name": "t_d19"})
    return asked[0][0]["question"] if asked and asked[0] else ""


def test_d19_recompile_reask_prefix(monkeypatch):
    """D19:round≥1 重编产生的新欠定(案有前序 decision、无 reopened)→题面前缀「按上次 X 重编后
    遇新情况」;与 ⓐ resume 场景二分不混。"""
    _mk_ledger()
    facts = [
        {"ev": "decision", "aid": A, "question_id": f"nd:{A}:1:verification_path_absent",
         "answer": "改过程"},
        {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:2:verification_path_absent"},
    ]
    q = _drive_ask_decision(monkeypatch, facts)
    assert "重编后" in q and "改过程" in q          # D19 前缀(动态取上次 decision)
    assert "未能落地" not in q                       # 非 ⓐ 恢复前缀(二分不混)


def test_a5_resume_reask_prefix_distinct_from_d19(monkeypatch):
    """ⓐ resume:needs_decision 带 reopened 载荷 → 「上次裁决未能落地」前缀,不走 D19。"""
    _mk_ledger()
    facts = [
        {"ev": "decision", "aid": A, "question_id": f"nd:{A}:1:verification_path_absent",
         "answer": "改描述"},
        {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:2:verification_path_absent",
         "reopened": {"prev_decision": "改描述"}},
    ]
    q = _drive_ask_decision(monkeypatch, facts)
    assert "未能落地" in q and "改描述" in q         # ⓐ 前缀
    assert "重编后" not in q                          # 非 D19(reopened 优先,二分不混)


def test_theory_provenance_anchor_adopted_vs_human(monkeypatch):
    """Theory ◇ 血统分锚(D15 同源):前序 decision 若 adopted:*(机生判例采信)→措辞「沿用判例」;
    人源→「你上次裁过」。防判例被误标用户亲裁(D15 反向病)。"""
    _mk_ledger()
    # 前序=adopted(机生判例采信)→「上次沿用判例」,不出现「你上次」
    q_adopt = _drive_ask_decision(monkeypatch, [
        {"ev": "decision", "aid": A, "question_id": f"nd:{A}:1:verification_path_absent",
         "answer": "改描述", "provenance": "adopted:eq--forbidden-mechanism--10-5"},
        {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:2:verification_path_absent"}])
    assert "沿用" in q_adopt and "你上次" not in q_adopt and "按你上次的" not in q_adopt
    # 对照:前序=人源(无 adopted provenance)→「你上次」,不出现「沿用」
    q_human = _drive_ask_decision(monkeypatch, [
        {"ev": "decision", "aid": A, "question_id": f"nd:{A}:1:verification_path_absent",
         "answer": "改过程"},
        {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:2:verification_path_absent"}])
    assert "你" in q_human and "沿用" not in q_human
