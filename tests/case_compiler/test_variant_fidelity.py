"""B 层变体保真:需求点名某枚举维度的变体,产出必须真用那个,不许偷换/缺配。

维度:sdns_method(rr/wrr/ga/…)+ save_variant(memory/file/all/net)。需求没点名 → no-op(零回归)。
三态:满足/换族(偷换)/缺配(点名却没配该类命令)。全局变体 grr/gwrr 算满足基础 rr/wrr(防误杀)。
(覆盖对抗审计找出的 P0-A 空配静默放行、P0-B no/show/clear 污染、P1-B grr 误杀、P3 词边界)
"""
from __future__ import annotations

import importlib

cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")


# ── 意图抽取(title+desc,不含 expected;findall 全取;词边界)─────────────
def test_intent_extracts_named_algorithms():
    assert cp._intent_methods({"title": "sdns host 选择服务池ga算法", "step_intents": []}) == {"ga"}
    assert cp._intent_methods({"title": "gwrr算法测试", "step_intents": []}) == {"gwrr"}
    # 多算法用例 findall 全取
    assert cp._intent_methods({"title": "先rr算法后wrr算法", "step_intents": []}) == {"rr", "wrr"}
    # 词边界:xrr算法 不命中 rr(P3)
    assert cp._intent_methods({"title": "xrr算法", "step_intents": []}) == set()
    # expected 里的对比叙述不污染 intent(P3):只从 desc 抽
    case = {"title": "ga算法", "step_intents": [{"desc": "配ga", "expected": "与rr算法不同,始终命中p1"}]}
    assert cp._intent_methods(case) == {"ga"}


# ── 实际抽取:跳过 no/show/clear(P0-B),位置抽参(防域名误命中),pool 角色可选(P2)──
def test_actual_skips_op_prefix_lines():
    cfg = "sdns host method h1 ga\nno sdns host method h2 wrr\nshow sdns host method h1 wrr"
    fams, seen = cp._actual_methods(cfg)
    assert fams == {"ga"} and seen is True       # no/show 行的 wrr 不进 actual

def test_actual_no_hostname_falsematch():
    fams, _ = cp._actual_methods("sdns host method www.ga.com wrr")
    assert fams == {"wrr"}                        # www.ga.com 的 ga 不误命中

def test_actual_pool_role_optional():
    assert cp._actual_methods('sdns pool method primary "p1" rr')[0] == {"rr"}
    assert cp._actual_methods("sdns pool method poolA wrr")[0] == {"wrr"}      # 无角色
    assert cp._actual_methods("sdns pool method default poolA ga")[0] == {"ga"}  # default 角色

def test_actual_empty_when_no_method():
    fams, seen = cp._actual_methods("sdns on\nsdns listener 172.16.34.70 53")
    assert fams == set() and seen is False


# ── 全局变体满足基础(P1-B 防误杀)────────────────────────────────────
def test_global_variant_satisfies_base():
    assert cp._method_satisfied("rr", {"grr"}) is True      # 点名 rr,用 grr 算满足
    assert cp._method_satisfied("wrr", {"gwrr"}) is True
    assert cp._method_satisfied("ga", {"wrr"}) is False     # ga 被 wrr 替 = 偷换
    assert cp._method_satisfied("grr", {"rr"}) is False     # 点名 grr 要 grr,rr 不够


# ── _check_variant_fidelity 端到端(monkeypatch xlsx)────────────────────
def _case(title, steps=None):
    return {"autoid": "x", "title": title, "step_intents": steps or []}

def _cfg(monkeypatch, text):
    monkeypatch.setattr(cp, "_read_xlsx_apv_config", lambda p: text)

def test_ga_swap_caught(monkeypatch):
    _cfg(monkeypatch, "sdns host method www.ga.com wrr")
    fb = cp._check_variant_fidelity(_case("sdns host 选择服务池ga算法"), "x.xlsx")
    assert fb and "算法变体不符" in fb

def test_ga_missing_caught(monkeypatch):   # P0-A:点名 ga 但没配任何 method → 缺配违规
    _cfg(monkeypatch, "sdns on\nsdns host name www.ga.com\nsdns listener 172.16.34.70")
    fb = cp._check_variant_fidelity(_case("ga算法"), "x.xlsx")
    assert fb and "算法缺配" in fb

def test_ga_correct_passes(monkeypatch):
    _cfg(monkeypatch, "sdns host method www.ga.com ga\nsdns pool member priority p1 s1 1")
    assert cp._check_variant_fidelity(_case("ga算法"), "x.xlsx") == ""

def test_rr_satisfied_by_grr_passes(monkeypatch):  # P1-B 防误杀
    _cfg(monkeypatch, "sdns host method h1 grr")
    assert cp._check_variant_fidelity(_case("rr算法"), "x.xlsx") == ""

def test_save_swap_and_missing(monkeypatch):
    _cfg(monkeypatch, "write memory")
    assert "保存变体不符" in cp._check_variant_fidelity(_case("执行write all后重启设备"), "x.xlsx")
    _cfg(monkeypatch, "sdns on\nsdns listener 1.2.3.4")
    assert "保存变体缺配" in cp._check_variant_fidelity(_case("执行write all后重启设备"), "x.xlsx")

def test_non_variant_case_noop(monkeypatch):
    _cfg(monkeypatch, "sdns on\nsdns listener 172.16.34.70 53\nshow sdns listener")
    assert cp._check_variant_fidelity(_case("sdns on,添加 sdns listener ipv4"), "x.xlsx") == ""
