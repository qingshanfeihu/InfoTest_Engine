"""批视图派生状态:全函数标签 + yzg 场景状态序列。"""
from __future__ import annotations

from main.ist_core.compile_engine_v8.views import (
    case_status, batch_view, all_settled,
    S_PENDING, S_AUTHORED, S_FAILED, S_SUBSET_VERIFIED, S_DELIVERABLE,
    S_CONTRADICTED, S_ESCALATED, S_AWAITING_USER,
)

A = "203600000000000001"


def _authored(art="art1", rnd=1):
    return {"ev": "authored", "aid": A, "round": rnd, "artifact": art}


def _v(run, ctx, result, art="art1", vol="vol1"):
    return {"ev": "verdict", "aid": A, "run_id": run, "ctx": ctx, "result": result,
            "artifact": art, "volume": vol, "signatures": []}


def test_lifecycle_labels_in_order():
    fs: list[dict] = []
    assert case_status(fs, A, "", "") == S_PENDING
    fs.append(_authored())
    assert case_status(fs, A, "art1", "") == S_AUTHORED
    fs.append(_v("r1", "subset", "fail"))
    assert case_status(fs, A, "art1", "") == S_FAILED
    fs.append(_authored("art2", 2))
    fs.append(_v("r2", "subset", "pass", art="art2"))
    assert case_status(fs, A, "art2", "vol1") == S_SUBSET_VERIFIED
    fs.append(_v("r3", "delivery", "pass", art="art2", vol="vol1"))
    assert case_status(fs, A, "art2", "vol1") == S_DELIVERABLE


def test_contradiction_label_yzg_shape():
    fs = [_authored(), _v("r1", "subset", "pass"), _v("r2", "delivery", "fail")]
    assert case_status(fs, A, "art1", "vol1") == S_CONTRADICTED


def test_contradicted_resets_on_new_artifact_m19():
    """M-19:S_CONTRADICTED 跟当前卷面——art1 矛盾史不得贴到 art2。"""
    fs = [_authored(),
          _v("r1", "subset", "pass"), _v("r2", "delivery", "fail"),
          _authored("art2", 2),
          _v("r3", "delivery", "fail", art="art2")]  # art2 仅 fail@delivery,无先 pass
    assert case_status(fs, A, "art2", "vol1") == S_FAILED
    assert case_status(fs, A, "art1", "vol1") == S_CONTRADICTED
    # batch_view 计数也按当前 artifact
    view = batch_view(fs, {"cases": [{"autoid": A}]})
    assert view["cases"][A]["status"] == S_FAILED
    assert view["cases"][A]["contradictions"] == 0


def test_awaiting_user_until_decision():
    fs = [{"ev": "needs_decision", "aid": A, "question_id": "q1"}]
    assert case_status(fs, A, "", "") == S_AWAITING_USER
    fs.append({"ev": "decision", "aid": A, "question_id": "q1", "answer": "改描述"})
    assert case_status(fs, A, "", "") == S_PENDING   # 决策已答,回到待编


def test_escalated_wins():
    fs = [_authored(), _v("r1", "subset", "pass"), {"ev": "escalated", "aid": A}]
    assert case_status(fs, A, "art1", "vol1") == S_ESCALATED


def test_batch_view_and_settlement():
    manifest = {"cases": [{"autoid": A}]}
    fs = [_authored(),
          {"ev": "merged", "volume": "vol1"},
          _v("r1", "delivery", "pass")]
    view = batch_view(fs, manifest)
    assert view["cases"][A]["status"] == S_DELIVERABLE
    assert view["counts"] == {S_DELIVERABLE: 1}
    assert all_settled(view)
    # 组成变更(新 merge 事实)→ 旧 delivery-pass 失效 → 不再 settled
    fs.append({"ev": "merged", "volume": "vol2"})
    view2 = batch_view(fs, manifest)
    assert view2["cases"][A]["status"] != S_DELIVERABLE
    assert not all_settled(view2)


def test_awaiting_pairs_by_question_id_h2():
    """H2(§18.11 横切):同案第二次欠定(新 question_id 未答)必须仍是 AWAITING——
    旧谓词「有任意 decision 即非等待」会把它误放行(重派/漏停车)。"""
    A = "203600000000000048"
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:1"},
          {"ev": "decision", "aid": A, "question_id": f"nd:{A}:1", "answer": "改过程"},
          {"ev": "needs_decision", "aid": A, "question_id": f"nd:{A}:2"}]
    assert case_status(fs, A, "", "") == S_AWAITING_USER
    fs.append({"ev": "decision", "aid": A, "question_id": f"nd:{A}:2", "answer": "改描述"})
    assert case_status(fs, A, "", "") != S_AWAITING_USER


# ── H-16:delivery_blocked 入 fold——G3 封堵案回 S_PENDING 重进 author(不再 limbo) ──

def _blocked(aid=A):
    return {"ev": "delivery_blocked", "aid": aid,
            "reason": "missing in-case teardown for network-layer writes",
            "run_id": f"g3:{aid}"}


def test_delivery_blocked_after_pass_returns_pending_H16():
    """H-16 红绿:最后 delivery pass 之后被 G3 封堵 → fold 消费 delivery_blocked →
    S_PENDING(重进 author 重编补自清);修前 fold 不消费该事实,下批派生回
    S_DELIVERABLE→终验闸跳过→closing 再封堵(limbo 循环 + 第 13 状态)。"""
    fs = [_authored(), _v("r1", "delivery", "pass"), _blocked()]
    assert case_status(fs, A, "art1", "vol1") == S_PENDING


def test_delivery_blocked_recovered_by_recompile_and_new_pass_H16():
    """兑现「重编补自清后可交付」:封堵后重编(新 authored 在其后)→ 打回支不再命中
    (封堵已消费,不烧重复轮);新卷面再拿 delivery pass → S_DELIVERABLE。"""
    fs = [_authored(), _v("r1", "delivery", "pass"), _blocked(),
          _authored("art2", 2)]
    assert case_status(fs, A, "art2", "vol1") == S_AUTHORED   # 新卷待验,非重复打回
    fs.append(_v("r2", "delivery", "pass", art="art2"))
    assert case_status(fs, A, "art2", "vol1") == S_DELIVERABLE


def test_delivery_blocked_terminal_still_wins_H16():
    """优先级同层不越位:封堵后用户止损(round=99 user_stop)→ 终态判定先于打回支。"""
    from main.ist_core.compile_engine_v8.views import S_TERMINAL
    fs = [_authored(), _v("r1", "delivery", "pass"), _blocked(),
          {"ev": "attribution", "aid": A, "round": 99, "layer": "user",
           "disposition": "user_stop"}]
    assert case_status(fs, A, "art1", "vol1") == S_TERMINAL
