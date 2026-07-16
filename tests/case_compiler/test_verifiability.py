"""用例可验性证伪（verifiability）单测：三类真实欠定用例 + 复用 distribution_assertion 的路径。"""

from __future__ import annotations

from main.case_compiler.verifiability import (
    check_verifiability,
    check_sequence_periodicity,
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


# ── E10a 跨客户端落点（777976 实证驱动）───────────────────────────────────────────

def test_cross_client_landing_underdetermined_for_distribution():
    """分布类算法下「客户端N→池M」：计数器共享/独立由设备实现决定，数学推不出 → 改预期。"""
    v = check_verifiability("rr", n_requests=2, n_pools=2, claim_kind="cross_client_landing")
    assert v.verifiable is False and v.suggested_fix == FIX_EXPECT
    assert "设备实现" in v.reason
    # 请求数再大也不改判（不是样本量问题，是主张本身不可证伪）
    v2 = check_verifiability("wrr", n_requests=100, n_pools=2, weights=[2, 1],
                             claim_kind="cross_client_landing")
    assert v2.verifiable is False
    # notes 给可验等价（worker 可改写而非必问，防 ask 泛滥）
    assert any("relation" in n for n in v.notes)
    assert any("distribution" in n for n in v.notes)


def test_cross_client_landing_non_distribution_defers_to_manual():
    """非分布算法（确定性映射，如地址族过滤）不误杀；固定落点是否可写留手册/判例。"""
    v = check_verifiability("ga", n_requests=1, n_pools=2, claim_kind="cross_client_landing")
    assert v.verifiable is True
    assert any("手册" in n or "先例" in n for n in v.notes)


# ── E10b 序列↔周期自洽（778012 实证形态；cycle_kind 语义类参，advisory）──────────────
# 通用性红线（2026-07-16 返工）：纯函数参数是**周期语义类**非算法名——「算法名→cycle_kind」
# 映射在调用方（工具壳 grammar 现查/worker 语义抽取），.py 内零算法语义。

def test_sequence_periodicity_contradiction_778012_shape():
    """778012 恒假形态：前 3 次 not_found + 后 5 次全 found、P=4——found 落两个剩余类。"""
    v = check_sequence_periodicity("uniform_rotation", 4, found_idx=[3, 4, 5, 6, 7],
                                   notfound_idx=[0, 1, 2])
    assert v.verifiable is False and v.suggested_fix == FIX_EXPECT
    assert "恒假" in v.reason


def test_sequence_periodicity_satisfiable():
    """合法排布：found 全落同一剩余类且 not_found 避开它 → 可满足。"""
    # P=3，成员在 r=1：found@{1,4,7}，not_found@{0,2}
    v = check_sequence_periodicity("uniform_rotation", 3, found_idx=[1, 4, 7],
                                   notfound_idx=[0, 2])
    assert v.verifiable is True
    # 起点未知的平移不变性：整体 +1 仍可满足
    v2 = check_sequence_periodicity("uniform_rotation", 3, found_idx=[2, 5, 8],
                                    notfound_idx=[1, 3])
    assert v2.verifiable is True


def test_sequence_periodicity_weighted_and_none_not_applicable():
    """weighted（剩余类占位依赖调度器交织）与 none（确定性映射无周期）→ 中性放行不判。"""
    v = check_sequence_periodicity("weighted", 4, found_idx=[3, 4, 5], notfound_idx=[0])
    assert v.verifiable is True and "不判" in v.reason
    vnone = check_sequence_periodicity("none", 4, found_idx=[0, 1], notfound_idx=[])
    assert vnone.verifiable is True and "不适用" in vnone.reason


def test_sequence_periodicity_unknown_failopen_zero_suggestion():
    """未知语义类/None/未声明 period → fail-open 平凡可满足、零建议（未知不误杀红线）。"""
    for ck in (None, "", "bogus_kind"):
        v = check_sequence_periodicity(ck, 4, found_idx=[3, 4], notfound_idx=[0])
        assert v.verifiable is True and v.suggested_fix == "", ck
    # period 未声明/无效同样 fail-open（矛盾排布也不判——周期未知剩余类模型无从建立）
    for bad_p in (None, 0, -1, "x"):
        v = check_sequence_periodicity("uniform_rotation", bad_p, [3, 4], [0])
        assert v.verifiable is True and v.suggested_fix == "", bad_p


def test_sequence_periodicity_algo_only_in_prose():
    """algo 参数只进呈报文案，不参与判定：同参数任意 algo 名判定结果一致。"""
    a = check_sequence_periodicity("uniform_rotation", 4, [3, 4, 5, 6, 7], [0, 1, 2])
    b = check_sequence_periodicity("uniform_rotation", 4, [3, 4, 5, 6, 7], [0, 1, 2],
                                   algo="whatever_new_algo")
    assert a.verifiable is b.verifiable is False
    assert "whatever_new_algo" in b.reason      # 进文案
    assert "whatever_new_algo" not in a.reason  # 不传不出现


def test_sequence_periodicity_period_one_edge():
    """P=1 边界：全 found 可满足；出现任一 not_found 即恒假（唯一剩余类必被命中）。"""
    assert check_sequence_periodicity("uniform_rotation", 1, [0, 1, 2], []).verifiable is True
    assert check_sequence_periodicity("uniform_rotation", 1, [0, 1], [2]).verifiable is False


def test_sequence_periodicity_boundaries():
    """空序列平凡可满足；同号 found∧not_found 自然恒假（枚举吸收，不需特判）。"""
    assert check_sequence_periodicity("uniform_rotation", 3, [], []).verifiable is True
    both = check_sequence_periodicity("uniform_rotation", 3, [1], [1])
    assert both.verifiable is False


# ── 单一事实源（DISTRIBUTION_ALGOS 合流 grammar，lexicon 单源纪律）────────────────────

def test_distribution_algos_single_source():
    """判定处走 grammar 现查；回退快照与 grammar 数据一致（防双源漂移）。"""
    from main.case_compiler.verifiability import DISTRIBUTION_ALGOS, _distribution_algos
    from main.case_compiler.domain_grammar import distribution_methods
    assert set(_distribution_algos()) == set(distribution_methods())
    assert set(DISTRIBUTION_ALGOS) == set(distribution_methods()), \
        "回退快照与 grammar 漂移——同步 DISTRIBUTION_ALGOS 或修 grammar"


def test_uniform_rotation_methods_accessor():
    """E10b cycle_kind 映射数据源：uniform_rotation 类现含 rr（wrr/grr/gwrr 未钉死不入）；
    accessor 对缺键 fail-open。"""
    from main.case_compiler.domain_grammar import uniform_rotation_methods, distribution_methods
    ur = set(uniform_rotation_methods())
    assert "rr" in ur
    assert ur <= set(distribution_methods()), "等权轮转类应是分布类子集"


def test_unknown_algo_failopen_all_consumers():
    """通用性红线③（2026-07-16 用户裁决）：未知算法名在全部算法分类消费点中性放行——
    「不在分布清单」≠「非分布」（封闭世界假设是误杀源；新算法可能是未入数据的分布变体）。
    确认确定性映射（ga，grammar deterministic_mapping 数据）语义保留：weight_ratio 下仍改描述。"""
    UNKNOWN = "wlc_future_algo"
    # E10a：未知 → 放行且措辞不说"非分布类"（fail-open 语义诚实）
    v = check_verifiability(UNKNOWN, 2, 2, claim_kind="cross_client_landing")
    assert v.verifiable is True and "未在文法数据中分类" in v.reason
    # 旧消费点 absolute_position：未知 → 放行
    v2 = check_verifiability(UNKNOWN, 1, 3, claim_kind="absolute_position")
    assert v2.verifiable is True and "未在文法数据中分类" in v2.reason
    # 旧消费点 weight_ratio/distribution：未知 → fail-open 放行（原 FIX_DESC 误杀已除）
    v3 = check_verifiability(UNKNOWN, 10, 3, weights=[3, 2, 1], claim_kind="weight_ratio")
    assert v3.verifiable is True and v3.suggested_fix == ""
    v4 = check_verifiability(UNKNOWN, 30, 3, claim_kind="distribution")
    assert v4.verifiable is True
    # 数据确认的确定性映射（ga）：既有「预期与算法不符→改描述」语义保留
    vga = check_verifiability("ga", 10, 3, weights=[3, 2, 1], claim_kind="weight_ratio")
    assert vga.verifiable is False and vga.suggested_fix == FIX_DESC
    assert "确定性映射" in vga.reason
    # ga 在 absolute_position/cross_client_landing 的放行文案标「数据确认」非「未知」
    vga2 = check_verifiability("ga", 1, 3, claim_kind="absolute_position")
    assert vga2.verifiable is True and "文法数据确认" in vga2.reason
    # E10b：未知语义类已由 test_sequence_periodicity_unknown_failopen_zero_suggestion 锁


def test_deterministic_mapping_methods_accessor():
    """确定性映射数据源（provenance 散文的机读提升）：与分布类不相交，含 ga。"""
    from main.case_compiler.domain_grammar import (deterministic_mapping_methods,
                                                   distribution_methods)
    det = set(deterministic_mapping_methods())
    assert "ga" in det
    assert not (det & set(distribution_methods())), "确定性映射与分布类必须不相交"
