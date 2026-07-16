"""B1' · 文法层 co-required 参数类型（类型+空数据；数据待 C7 上机钉死后回填）。

验收语义：①类型解析（accessor fail-open）②空数据零行为变化③检测器对合成 rule
的判定行为锁定（572708 双响应未钉死 → 真实 json rules=[] 空置，本测试用合成 rule
锁检测器语义，不写死未证实文法）。
"""

from __future__ import annotations

import main.case_compiler.domain_grammar as dg
from main.case_compiler.domain_grammar import co_required_params, missing_co_required

# 合成规则（仅测检测器语义；trigger 复用文法表已注册语句 method_algorithm_line）。
_RULE = {
    "id": "wrr-weight-test",
    "trigger_statement": "method_algorithm_line",
    "condition": {"param": "method", "values": ["wrr", "ga"]},  # 组名 method 不存在→回退 name 组
    "requires_pattern": r"\b(weight|priority)\s+\d+",
    "scope": "synthetic",
    "provenance": {"source": "synthetic test rule", "confirmed_on_device": False},
}


def test_empty_rules_noop():
    """真实 json 首发 rules=[] 空置（572708 未钉死）→ accessor 空、检测器零报。"""
    assert co_required_params() == []
    lines = ["sdns host method example.com wrr", "sdns pool method p1 ga"]
    assert missing_co_required([], lines) == []
    assert missing_co_required(co_required_params(), lines) == []


def test_missing_key_failopen(monkeypatch):
    """键整体缺失（旧版本 json）→ accessor fail-open 返回 []，不炸。"""
    real_mtime = dg.GRAMMAR_PATH.stat().st_mtime_ns
    monkeypatch.setattr(dg, "_cache",
                        {"mtime": real_mtime, "data": {"statements": {}}, "compiled": {}})
    assert dg.co_required_params() == []


def test_detector_flags_missing_param():
    """trigger 命中 ∧ 条件值命中 ∧ 同行无 requires_pattern → 报 {rule_id, line, provenance}。"""
    hits = missing_co_required([_RULE], ["sdns host method example.com wrr"])
    assert len(hits) == 1
    assert hits[0]["rule_id"] == "wrr-weight-test"
    assert hits[0]["line"] == "sdns host method example.com wrr"
    assert hits[0]["provenance"]["confirmed_on_device"] is False
    # 同行带了共需参数 → 不报
    assert missing_co_required([_RULE], ["sdns host method example.com wrr weight 3"]) == []
    assert missing_co_required([_RULE], ["sdns host method example.com ga priority 1"]) == []


def test_detector_condition_not_met_no_flag():
    """条件参数值不命中（rr 不在 {wrr,ga}）/非 trigger 语句行 → 不报（非分布类不误杀）。"""
    assert missing_co_required([_RULE], ["sdns host method example.com rr"]) == []
    assert missing_co_required([_RULE], ["sdns pool service p1 s1"]) == []


def test_bad_rule_failopen():
    """坏规则（trigger 未注册/正则不编译/requires_pattern 空）整条跳过，不炸不误报。"""
    bad_trigger = {**_RULE, "trigger_statement": "nonexistent_stmt"}
    bad_regex = {**_RULE, "requires_pattern": "[unclosed"}
    empty_req = {**_RULE, "requires_pattern": ""}
    lines = ["sdns host method example.com wrr"]
    assert missing_co_required([bad_trigger, bad_regex, empty_req], lines) == []
    # 坏规则与好规则混排：好规则照常生效
    assert len(missing_co_required([bad_trigger, _RULE], lines)) == 1
