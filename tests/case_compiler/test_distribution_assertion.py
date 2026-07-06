"""分布区间断言辅助（distribution_assertion）单测：区间正则 / 守恒门 / 反恒真门 / 展开。"""

from __future__ import annotations

import re

import pytest

from main.case_compiler.distribution_assertion import (
    int_range_to_regex,
    range_regex_for_count,
    validate_distribution,
    expand_distribution_step,
    expand_distribution_steps,
    expand_provenance_steps_with_plan,
)


# ── int_range_to_regex：跨位边界全覆盖 + 两端排除 ──────────────────────────────────

@pytest.mark.parametrize("lo,hi", [
    (8, 12), (18, 22), (95, 105), (8, 8), (98, 103), (0, 2), (7, 9), (1, 1), (0, 30), (89, 110),
])
def test_int_range_to_regex_covers_exactly(lo, hi):
    pat = re.compile(r"^(?:" + int_range_to_regex(lo, hi) + r")$")
    # 区间内全匹配
    for n in range(lo, hi + 1):
        assert pat.match(str(n)), f"{n} 应在 [{lo},{hi}] 内却不匹配"
    # 区间外两端不匹配
    if lo > 0:
        assert not pat.match(str(lo - 1)), f"{lo-1} 不该匹配 [{lo},{hi}]"
    assert not pat.match(str(hi + 1)), f"{hi+1} 不该匹配 [{lo},{hi}]"


def test_int_range_to_regex_rejects_inverted():
    with pytest.raises(ValueError):
        int_range_to_regex(12, 8)


def test_int_range_to_regex_rejects_negative():
    with pytest.raises(ValueError):
        int_range_to_regex(-1, 3)


def test_range_regex_boundary_blocks_superstring():
    """带数字边界：[8,12] 区间正则不该误配 120 里的 12、18 里的 8。"""
    g = "anchor[^\\n]*Hit:\\s*" + range_regex_for_count(8, 12)
    assert re.search(g, "anchor x Hit: 10")      # 区间内
    assert re.search(g, "anchor x Hit: 12")
    assert not re.search(g, "anchor x Hit: 120")  # 120 ∉ [8,12]，边界防误配
    assert not re.search(g, "anchor x Hit: 18")   # 18 ∉ [8,12]
    assert not re.search(g, "anchor x Hit: 7")    # 7 < 8


# ── validate_distribution：守恒门 + 反恒真门 ──────────────────────────────────────

def _b(anchor, expected, tol):
    return {"anchor": anchor, "expected": expected, "tol": tol}


def test_validate_ok_rr_even():
    assert validate_distribution(30, [_b("a", 10, 2), _b("b", 10, 2), _b("c", 10, 2)]) is None


def test_validate_ok_wrr_skew():
    # wrr 倾斜：主桶大、小桶可低至 0，仍合法（上界都 < total，守恒可行）
    assert validate_distribution(10, [_b("a", 8, 1), _b("b", 1, 1), _b("c", 1, 1)]) is None


def test_validate_rejects_single_bucket():
    err = validate_distribution(30, [_b("a", 30, 0)])
    assert err and "至少需 2 个桶" in err


def test_validate_rejects_tautology_wide_bucket():
    # 单桶区间宽到上界≥total → 恒真
    err = validate_distribution(30, [_b("a", 15, 20), _b("b", 15, 20)])
    assert err and ("恒真" in err or "上界" in err)


def test_validate_rejects_conservation_break():
    # Σ上界=8 容纳不下 total=30
    err = validate_distribution(30, [_b("a", 3, 1), _b("b", 3, 1)])
    assert err and "守恒" in err


def test_validate_rejects_center_offset():
    # 上界都 < total 且区间能容纳，但 Σexpected 远离 total（中心偏移）
    # a,b,c each expected 3 tol 5 → lo 0 hi 8(<30 ok), Σhi=24<30 → 先触守恒；构造 Σhi>=30 但 Σexpected 偏
    err = validate_distribution(30, [_b("a", 3, 12), _b("b", 3, 12), _b("c", 3, 12), _b("d", 3, 12)])
    # Σhi=60>=30, Σlo=0<=30 守恒过；Σexpected=12，|12-30|=18>4 → 中心偏移
    assert err and ("中心" in err or "偏移" in err)


def test_validate_rejects_non_int():
    assert validate_distribution(30, [_b("a", 10.5, 2), _b("b", 10, 2)]) is not None
    assert validate_distribution("30", [_b("a", 10, 2), _b("b", 10, 2)]) is not None


def test_validate_rejects_missing_anchor():
    err = validate_distribution(20, [{"expected": 10, "tol": 2}, _b("b", 10, 2)])
    assert err and "anchor" in err


# ── expand：dist 步 → N 条 found ────────────────────────────────────────────────

def test_expand_distribution_step_ok():
    step = {"E": "check_point", "F": "dist", "dist": {
        "total": 30, "field": "Hit:\\s*",
        "buckets": [_b("m1", 10, 2), _b("m2", 10, 2), _b("m3", 10, 2)]}}
    out, err = expand_distribution_step(step)
    assert err is None
    assert len(out) == 3
    for s in out:
        assert s["E"] == "check_point" and s["F"] == "found"
        assert "Hit:" in s["G"] and "(?<!\\d)" in s["G"]


def test_expand_distribution_step_custom_pattern():
    step = {"E": "check_point", "F": "dist", "dist": {
        "total": 20, "buckets": [
            {"anchor": "m1", "expected": 10, "tol": 2, "pattern": "pool1 .* count={range}"},
            {"anchor": "m2", "expected": 10, "tol": 2, "pattern": "pool2 .* count={range}"}]}}
    out, err = expand_distribution_step(step)
    assert err is None and len(out) == 2
    assert out[0]["G"].startswith("pool1 .* count=")
    assert "{range}" not in out[0]["G"]


def test_expand_distribution_step_bad_returns_error():
    step = {"E": "check_point", "F": "dist", "dist": {
        "total": 30, "buckets": [_b("a", 3, 1), _b("b", 3, 1)]}}
    out, err = expand_distribution_step(step)
    assert out is None and err and "守恒" in err


def test_expand_distribution_step_pattern_missing_placeholder():
    step = {"E": "check_point", "F": "dist", "dist": {
        "total": 20, "buckets": [
            {"anchor": "m1", "expected": 10, "tol": 2, "pattern": "no placeholder"},
            {"anchor": "m2", "expected": 10, "tol": 2}]}}
    out, err = expand_distribution_step(step)
    assert out is None and err and "{range}" in err


# ── expand_distribution_steps + provenance 同步 ──────────────────────────────────

def test_expand_steps_mixed_and_plan():
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "show statistics sdns pool p1"},
        {"E": "check_point", "F": "dist", "dist": {
            "total": 20, "field": "Hit:\\s*", "buckets": [_b("m1", 10, 2), _b("m2", 10, 2)]}},
    ]
    new_steps, plan, err = expand_distribution_steps(steps)
    assert err is None
    assert len(new_steps) == 3          # 1 普通 + 2 展开
    assert plan == [("normal", 1), ("dist", 2)]
    assert all(s["F"] == "found" for s in new_steps[1:])


def test_expand_steps_propagates_error():
    steps = [{"E": "check_point", "F": "dist", "dist": {
        "total": 30, "buckets": [_b("a", 3, 1), _b("b", 3, 1)]}}]
    new_steps, plan, err = expand_distribution_steps(steps)
    assert new_steps is None and err is not None


def test_expand_provenance_with_plan_aligned():
    plan = [("normal", 1), ("dist", 2)]
    prov = [
        {"E": "APV_0", "F": "cmd_config", "G": "show", "layer": "G", "source": {"kind": "footprint", "ref": "x"}},
        {"E": "check_point", "F": "dist", "G": "", "layer": "V", "source": {"kind": "distribution_derived", "ref": "rr"}},
    ]
    out = expand_provenance_steps_with_plan(prov, plan)
    assert len(out) == 3
    assert out[0]["source"]["kind"] == "footprint"
    assert out[1]["source"]["kind"] == "distribution_derived"
    assert out[2]["source"]["kind"] == "distribution_derived"
    assert out[1]["layer"] == "V" and out[2]["layer"] == "V"


def test_expand_provenance_length_mismatch_returned_unchanged():
    plan = [("normal", 1), ("dist", 2)]
    prov = [{"E": "x", "F": "y", "G": "z"}]  # 长度对不上 plan
    assert expand_provenance_steps_with_plan(prov, plan) is prov
