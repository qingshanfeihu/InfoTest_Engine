"""rr/wrr 命中计数 checker 回放实证回归(V4 步骤5,linalg §8)。

设备探针回放(2026-07-05,dongkl 测试床):
- 单段连续查询 6/6 池级样本命中:6次/3池→2/2/2(整除精确);7次/3池→3/2/2(区间[2,3]
  且恰 1 池取上界)。
- 分段(show 插入后):11 次分两段实测 5/3/3——理想区间 [3,4] 外,轮转态漂移。
- wrr:两轮实测配比与配置权重不符(疑似产品缺陷在案)。
"""
from __future__ import annotations

from main.case_compiler.checkers.rr_hit import (
    rr_hit_range,
    rr_hit_range_segmented,
    wrr_hit_range,
)
from main.ist_core.tools.device.checker_tool import compile_expected_hits


def test_rr_exact_when_divisible():
    r = rr_hit_range(6, 3)
    assert (r.lo, r.hi, r.confidence) == (2, 2, "exact")   # 探针实测 2/2/2


def test_rr_interval_with_remainder():
    r = rr_hit_range(7, 3)
    assert (r.lo, r.hi, r.confidence) == (2, 3, "high")    # 探针实测 3/2/2 ∈ [2,3]


def test_rr_segmented_degrades():
    r = rr_hit_range_segmented(11, 3, uninterrupted=False)
    assert r.confidence == "low" and r.hi == 11            # 实测 5/3/3 超理想区间→降级


def test_rr_nonparticipating_pool_zero():
    r = rr_hit_range(6, 2, pool_participates=False)
    assert (r.lo, r.hi) == (0, 0)                          # v6-only 池对 A 查询恒 0(上轮实证)


def test_wrr_participation_only():
    r = wrr_hit_range(12, 3, weight=3)
    assert r.confidence == "low" and (r.lo, r.hi) == (1, 12)


def test_tool_rejects_deterministic_algorithms():
    out = compile_expected_hits.invoke({"algorithm": "ga", "n_requests": 3, "n_pools": 3})
    assert out.startswith("error") and "capture-compare" in out


def test_tool_low_confidence_warns():
    out = compile_expected_hits.invoke({"algorithm": "rr", "n_requests": 11, "n_pools": 3,
                                        "uninterrupted": False})
    assert "confidence=low" in out and "do not write an exact-interval" in out
