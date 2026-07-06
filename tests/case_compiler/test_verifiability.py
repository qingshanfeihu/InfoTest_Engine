"""用例可验性证伪（verifiability）单测：三类真实欠定用例 + 复用 distribution_assertion 的路径。"""

from __future__ import annotations

from main.case_compiler.verifiability import (
    check_verifiability,
    render_needs_user_decision,
    _implied_buckets,
    FIX_DESC, FIX_PROCESS, FIX_EXPECT,
)


# ── 三类真实欠定用例（dongkl rr/wrr）──────────────────────────────────────────────

def test_absolute_position_unverifiable_at_any_n():
    """「第N次必中第N个pool」绝对位置：rr 起点非确定，任何请求数都不可证伪 → 改预期。"""
    v = check_verifiability("rr", n_requests=1, n_pools=3, claim_kind="absolute_position")
    assert v.verifiable is False
    assert v.suggested_fix == FIX_EXPECT
    # 即使请求数很大，绝对位置仍不可证伪
    v2 = check_verifiability("rr", n_requests=100, n_pools=3, claim_kind="absolute_position")
    assert v2.verifiable is False and v2.suggested_fix == FIX_EXPECT


def test_absolute_position_not_rejected_for_non_distribution_algo():
    """非分布算法的绝对映射不套 rr 起点模型；是否可写固定期望留给手册/先例来源判断。"""
    v = check_verifiability("ga", n_requests=1, n_pools=3, claim_kind="absolute_position")
    assert v.verifiable is True
    assert any("手册/先例" in note for note in v.notes)


def test_rotation_order_needs_full_cycle():
    """依次轮转：需走完整一轮 = n_pools 次。"""
    assert check_verifiability("rr", 2, 3, claim_kind="rotation_order").verifiable is False
    bad = check_verifiability("rr", 2, 3, claim_kind="rotation_order")
    assert bad.min_requests == 3 and bad.suggested_fix == FIX_PROCESS
    assert check_verifiability("rr", 3, 3, claim_kind="rotation_order").verifiable is True
    assert check_verifiability("rr", 5, 3, claim_kind="rotation_order").verifiable is True


def test_new_member_last_needs_existing_plus_one():
    """新增 pool 最后命中：需原pool数+1，且不能降级成“新增pool有命中”。"""
    bad = check_verifiability("rr", n_requests=1, n_pools=4, claim_kind="new_member_last", existing_pools=3)
    assert bad.verifiable is False and bad.min_requests == 4 and bad.suggested_fix == FIX_PROCESS
    assert "物理上看不到" in bad.reason
    good = check_verifiability("rr", n_requests=4, n_pools=4, claim_kind="new_member_last", existing_pools=3)
    assert good.verifiable is True and good.min_requests == 4
    assert any("顺序语义" in note for note in good.notes)
    assert any("不等价于最后命中" in note for note in good.notes)
    # existing_pools 缺省 → 按 n_pools-1 推
    d = check_verifiability("rr", n_requests=1, n_pools=4, claim_kind="new_member_last")
    assert d.min_requests == 4


def test_new_member_participates_is_weaker_than_last_order():
    """新增 pool 参与轮转是较弱 claim，不能替代“最后才命中”。"""
    bad = check_verifiability("rr", n_requests=1, n_pools=4, claim_kind="new_member_participates", existing_pools=3)
    assert bad.verifiable is False and bad.min_requests == 4
    v = check_verifiability("rr", n_requests=4, n_pools=4, claim_kind="new_member_participates", existing_pools=3)
    assert v.verifiable is True and v.min_requests == 4
    assert any("不证明" in note and "最后" in note for note in v.notes)


def test_weight_ratio_needs_sum_of_weights():
    """wrr 按权重比例：需 ≥Σ权重 次才能体现比例。"""
    bad = check_verifiability("wrr", 3, 3, weights=[3, 2, 1], claim_kind="weight_ratio")
    assert bad.verifiable is False and bad.min_requests == 6 and bad.suggested_fix == FIX_PROCESS
    good = check_verifiability("wrr", 6, 3, weights=[3, 2, 1], claim_kind="weight_ratio")
    assert good.verifiable is True


# ── 复用 distribution_assertion 的路径 ───────────────────────────────────────────

def test_distribution_reuses_validate_distribution_conservation():
    """distribution claim：复用 validate_distribution（守恒+反恒真）；够请求数 → 可验。"""
    v = check_verifiability("rr", n_requests=30, n_pools=3, claim_kind="distribution")
    assert v.verifiable is True


def test_implied_buckets_conserve_total():
    """_implied_buckets：各桶期望和严格==总请求数（守恒），余数补到最大权重桶。"""
    for n, w in [(30, [1, 1, 1]), (10, [3, 2, 1]), (7, [1, 1, 1]), (6, [3, 2, 1])]:
        buckets = _implied_buckets(n, w)
        assert sum(b["expected"] for b in buckets) == n, (n, w, buckets)
        assert len(buckets) == len(w)


def test_weight_ratio_wrong_algo_is_change_description():
    """claim=weight_ratio 但算法非分布类（ga）→ 预期与算法不符 → 改描述。"""
    v = check_verifiability("ga", 10, 3, weights=[3, 2, 1], claim_kind="weight_ratio")
    assert v.verifiable is False and v.suggested_fix == FIX_DESC


# ── 关系 / 边界 ───────────────────────────────────────────────────────────────

def test_relation_needs_two_requests():
    assert check_verifiability("rr", 1, 3, claim_kind="relation_diff").verifiable is False
    assert check_verifiability("rr", 2, 3, claim_kind="relation_diff").verifiable is True
    assert check_verifiability("rr", 2, 3, claim_kind="relation_same").verifiable is True


def test_unknown_and_empty_claim_kind_change_description():
    assert check_verifiability("rr", 5, 3, claim_kind="bogus").suggested_fix == FIX_DESC
    v = check_verifiability("rr", 5, 3, claim_kind="")
    assert v.verifiable is False and v.suggested_fix == FIX_DESC


def test_render_needs_user_decision_format():
    v = check_verifiability("rr", 1, 4, claim_kind="new_member_last", existing_pools=3)
    text = render_needs_user_decision("203031753342778012", v)
    assert text.startswith("NEEDS_USER_DECISION autoid=203031753342778012")
    assert "原因：" in text and "最小可验请求数：4" in text
    assert "改描述 / 改过程 / 改预期" in text
