"""终验幂等闸纯判定(_delivery_verify_skippable)——断批例外回归。

2026-07-16 zhaiyq 续跑实证:被杀 run 的断批 delivery 裁决(17 过+27 not_run)带同卷
指纹入流,续跑幂等闸误吸收 → 27 案钉死 broken → delivery_incomplete 收口。修=组成内
存在 broken 三态时闸不吸收(重跑非零信息);既有 subset_verified 待升格例外语义不动。
"""
from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8.nodes import _delivery_verify_skippable


def _vw(statuses: dict[str, str]) -> dict:
    return {"cases": {a: {"status": s} for a, s in statuses.items()}}


_VERDICT = [{"ev": "verdict", "ctx": "delivery", "volume": "vol-1"}]


def test_stable_composition_with_prior_verdict_skips():
    """四稳态(组成/卷面/无待升格/无断批)+同卷裁决在流 → 吸收(不重跑)。"""
    vw = _vw({"a1": V.S_DELIVERABLE, "a2": V.S_DELIVERABLE})
    assert _delivery_verify_skippable(vw, ["a1", "a2"], "vol-1", _VERDICT) is True


def test_no_prior_verdict_never_skips():
    vw = _vw({"a1": V.S_DELIVERABLE})
    assert _delivery_verify_skippable(vw, ["a1"], "vol-1", []) is False
    # 裁决在流但卷指纹不同 → 不吸收
    assert _delivery_verify_skippable(vw, ["a1"], "vol-2", _VERDICT) is False


def test_subset_verified_upgrade_breaks_idempotency():
    """待升格例外(既有语义,redline 实证回归):必须重跑拿 delivery-pass。"""
    vw = _vw({"a1": V.S_DELIVERABLE, "a2": V.S_SUBSET_VERIFIED})
    assert _delivery_verify_skippable(vw, ["a1", "a2"], "vol-1", _VERDICT) is False


def test_broken_composition_breaks_idempotency():
    """断批例外(本修):组成内任一 broken 三态 → 那次裁决是断批快照,重跑有信息。"""
    for broken in (V.S_BROKEN, V.S_BROKEN_ERRORED, V.S_BROKEN_BLOCKED):
        vw = _vw({"a1": V.S_DELIVERABLE, "a2": broken})
        assert _delivery_verify_skippable(vw, ["a1", "a2"], "vol-1", _VERDICT) is False, broken
