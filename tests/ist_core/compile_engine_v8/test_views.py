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
