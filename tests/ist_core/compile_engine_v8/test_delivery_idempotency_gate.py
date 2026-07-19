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


# ── ①A 缝合语境等价三条件(THEORY 公式(15)补注,用户裁 2026-07-19):任一破坏→拒吸收回整卷 ──


def _verdict(bed="", build="", volume="vol-1"):
    return [{"ev": "verdict", "ctx": "delivery", "volume": volume,
             "bed": bed, "build": build}]


def test_bed_drift_breaks_idempotency_1A():
    """⒈同床:被依赖裁决床≠当前床(换床/断点续跑到别的床)→非同一 ctx_delivery,拒吸收。"""
    vw = _vw({"a1": V.S_DELIVERABLE})
    assert _delivery_verify_skippable(
        vw, ["a1"], "vol-1", _verdict(bed="10.4.127.103"),
        cur_bed="10.4.127.93") is False


def test_build_drift_breaks_idempotency_1A():
    """⒈同版本:被依赖裁决 build≠当前 build(设备升级)→非同一 ctx_delivery,拒吸收。"""
    vw = _vw({"a1": V.S_DELIVERABLE})
    assert _delivery_verify_skippable(
        vw, ["a1"], "vol-1", _verdict(build="APV-5.8.5"),
        cur_build="APV-5.8.6") is False


def test_same_bed_build_still_skips_1A():
    """⒈满足(同床同版本)+无 ⒉⒊破坏 → 仍吸收(不误伤合法幂等跳过)。"""
    vw = _vw({"a1": V.S_DELIVERABLE})
    assert _delivery_verify_skippable(
        vw, ["a1"], "vol-1", _verdict(bed="b1", build="v1"),
        cur_bed="b1", cur_build="v1") is True


def test_missing_bed_build_conservative_skips_1A():
    """⒈缺字段保守视同(旧账无 bed/build,或当前无 bed):不拒(同 _s0_parked 床锚容错)。"""
    vw = _vw({"a1": V.S_DELIVERABLE})
    assert _delivery_verify_skippable(          # 旧裁决无 bed/build
        vw, ["a1"], "vol-1", _verdict(), cur_bed="b1", cur_build="v1") is True
    assert _delivery_verify_skippable(          # 当前无 bed(裁决有)
        vw, ["a1"], "vol-1", _verdict(bed="b1", build="v1")) is True


def test_coexist_violation_breaks_idempotency_1A():
    """⒉断点两侧独立:通道④共存违例=保存族反例的静态 config 形态(δ(c)≠∅ 残留风险,
    persistence 纯形态检测、不看运行结果)→ 拒吸收回整卷连跑。"""
    vw = _vw({"a1": V.S_DELIVERABLE, "a2": V.S_DELIVERABLE})
    assert _delivery_verify_skippable(
        vw, ["a1", "a2"], "vol-1", _verdict(bed="b1", build="v1"),
        cur_bed="b1", cur_build="v1",
        coexist=[{"family": "save", "aids": ["a1", "a2"]}]) is False
    assert _delivery_verify_skippable(          # 无共存违例 → 三条件齐 → 吸收
        vw, ["a1", "a2"], "vol-1", _verdict(bed="b1", build="v1"),
        cur_bed="b1", cur_build="v1", coexist=[]) is True
