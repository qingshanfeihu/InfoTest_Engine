"""health.py 离线单测——首跑通过率趋势 + 连续 K 轮低于基线降级判定。

不依赖设备/网络/schema.py（health 纯 stdlib）。为不被 skill_lib/__init__.py 对
schema 的导入耦合（schema 由兄弟 dev 并行构建，可能尚未落地），本测试用
importlib 从文件路径直接加载 health.py 模块。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# 直接按文件路径加载 health.py，绕开 package __init__（其 import schema）。
_HEALTH_PATH = (Path(__file__).resolve().parents[1]
                / "main" / "case_compiler" / "skill_lib" / "health.py")
_spec = importlib.util.spec_from_file_location("_skill_lib_health_under_test", _HEALTH_PATH)
health = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(health)
health_report = health.health_report


# ── 测试夹具：构造 registry / history（dict 形态 + 对象形态）─────────────

def _skill(baseline=None, version=1, ab_with=None, state=None, degraded=False,
           explicit_baseline=None):
    """构造一条技能 spec（dict 形态）。baseline 走 ab_test.with。"""
    ev: dict = {"version": version}
    if ab_with is not None:
        ev["ab_test"] = {"with": ab_with}
    if explicit_baseline is not None:
        ev["admission_baseline"] = explicit_baseline
    if degraded:
        ev["degraded"] = True
    spec: dict = {"evidence": ev}
    if state is not None:
        spec["state"] = state
    return spec


class _ObjSpec:
    """对象形态 spec（验证 duck-typing 兼容 dataclass / 普通对象）。"""

    def __init__(self, name, ab_with, version=1):
        self.name = name
        self.evidence = type("Ev", (), {
            "ab_test": {"with": ab_with}, "version": version})()


# ── 正常路径 ───────────────────────────────────────────────────────────

def test_healthy_skill_not_demoted():
    """通过率稳定在基线之上 → 不降级。"""
    reg = {"settle-wait": _skill(ab_with=0.8)}
    hist = {"settle-wait": [0.8, 0.9, 0.85, 0.9]}
    rep = health_report(reg, hist)
    s = rep["skills"]["settle-wait"]
    assert s["demote_candidate"] is False
    assert s["reason"] == "within_baseline"
    assert s["admission_baseline"] == 0.8
    assert s["latest"] == 0.9
    assert s["direction"] == "improving"
    assert rep["demote_candidates"] == []
    assert rep["summary"]["with_history"] == 1


def test_consecutive_decline_below_baseline_demotes():
    """连续 3 轮低于入库基线 → demote 候选。"""
    reg = {"rr-skill": _skill(ab_with=0.9)}
    hist = {"rr-skill": [0.9, 0.5, 0.4, 0.3]}  # 末 3 轮 < 0.9
    rep = health_report(reg, hist)
    s = rep["skills"]["rr-skill"]
    assert s["demote_candidate"] is True
    assert s["consecutive_below"] == 3
    assert s["reason"] == "below_baseline_for_3_rounds"
    assert s["direction"] == "declining"
    assert rep["demote_candidates"] == ["rr-skill"]
    assert rep["summary"]["demote_count"] == 1


def test_recovery_breaks_consecutive_streak():
    """最近一轮回到基线之上 → 连续计数清零，不降级。"""
    reg = {"s": _skill(ab_with=0.8)}
    hist = {"s": [0.5, 0.4, 0.3, 0.9]}  # 最后一轮回升
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["consecutive_below"] == 0
    assert s["demote_candidate"] is False


def test_explicit_admission_baseline_overrides_ab_test():
    """evidence.admission_baseline 显式覆盖 ab_test.with。"""
    reg = {"s": _skill(ab_with=0.5, explicit_baseline=0.95)}
    hist = {"s": [0.9, 0.9, 0.9]}  # 高于 0.5 但低于 0.95
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["admission_baseline"] == 0.95
    assert s["consecutive_below"] == 3
    assert s["demote_candidate"] is True


def test_configurable_k():
    """consecutive_k 可调：K=5 时 3 轮低于不够格。"""
    reg = {"s": _skill(ab_with=0.9)}
    hist = {"s": [0.9, 0.3, 0.3, 0.3]}
    rep = health_report(reg, hist, consecutive_k=5)
    s = rep["skills"]["s"]
    assert s["demote_candidate"] is False
    # 历史只有 4 轮 < K=5
    assert s["reason"] == "insufficient_history"
    assert rep["summary"]["consecutive_k"] == 5


# ── 边界 ───────────────────────────────────────────────────────────────

def test_no_admission_baseline_not_demoted():
    """技能给不出基线（无 ab_test）→ 不臆造，标 no_admission_baseline，不降级。"""
    reg = {"s": _skill()}  # evidence 无 ab_test 无 admission_baseline
    hist = {"s": [0.1, 0.1, 0.1]}
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["admission_baseline"] is None
    assert s["demote_candidate"] is False
    assert s["reason"] == "no_admission_baseline"


def test_no_history_not_demoted():
    """无历史轮次 → no_history，不降级。"""
    reg = {"s": _skill(ab_with=0.9)}
    rep = health_report(reg, {})
    s = rep["skills"]["s"]
    assert s["rounds"] == 0
    assert s["reason"] == "no_history"
    assert s["demote_candidate"] is False
    assert s["direction"] == "unknown"


def test_insufficient_history_not_demoted():
    """历史不足 K 轮 → insufficient_history，即便全低于基线也不降级。"""
    reg = {"s": _skill(ab_with=0.9)}
    hist = {"s": [0.1, 0.1]}  # 2 < default K=3
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["reason"] == "insufficient_history"
    assert s["demote_candidate"] is False


def test_already_off_skill_skipped():
    """已 off 的技能不再列入 demote 候选（保留 evidence 供复盘）。"""
    reg = {"s": _skill(ab_with=0.9, state="off")}
    hist = {"s": [0.1, 0.1, 0.1, 0.1]}
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["reason"] == "already_off"
    assert s["demote_candidate"] is False


def test_degraded_flag_skipped():
    """evidence.degraded 为真同样视为已降级。"""
    reg = {"s": _skill(ab_with=0.9, degraded=True)}
    hist = {"s": [0.1, 0.1, 0.1, 0.1]}
    rep = health_report(reg, hist)
    assert rep["skills"]["s"]["reason"] == "already_off"


def test_empty_registry():
    """空 registry → 空报告，不崩。"""
    rep = health_report({}, {})
    assert rep["skills"] == {}
    assert rep["demote_candidates"] == []
    assert rep["summary"]["total_skills"] == 0


def test_none_inputs():
    """registry/history 为 None → 不崩，空报告。"""
    rep = health_report(None, None)
    assert rep["summary"]["total_skills"] == 0


# ── 多形态解析 ─────────────────────────────────────────────────────────

def test_rate_parsing_n_over_m_and_dict():
    """通过率支持 'N/M' 字符串与 {passed,total} dict。"""
    reg = {"s": _skill(ab_with="9/10")}  # 基线 0.9
    hist = {"s": [{"passed": 3, "total": 10},
                  "4/10",
                  {"pass_rate": 0.2}]}  # 三轮均 < 0.9
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["admission_baseline"] == 0.9
    assert s["trend"] == [0.3, 0.4, 0.2]
    assert s["consecutive_below"] == 3
    assert s["demote_candidate"] is True


def test_unparseable_records_skipped():
    """无法解析的轮次记录被跳过，不污染趋势。"""
    reg = {"s": _skill(ab_with=0.8)}
    hist = {"s": ["garbage", None, 0.3, {"nope": 1}, 0.2, 0.1]}
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["trend"] == [0.3, 0.2, 0.1]  # 仅 3 个有效
    assert s["rounds"] == 3


def test_object_form_registry_and_history():
    """duck-typing：对象形态 spec + 对象形态 history 容器同样工作。"""
    specs = [_ObjSpec("alpha", 0.9), _ObjSpec("beta", 0.8)]

    class _Hist:
        history = {"alpha": [0.2, 0.2, 0.2], "beta": [0.85, 0.9, 0.88]}

    rep = health_report(specs, _Hist())
    assert rep["skills"]["alpha"]["demote_candidate"] is True
    assert rep["skills"]["beta"]["demote_candidate"] is False
    assert rep["skills"]["alpha"]["version"] == 1


# ── 确定性 ─────────────────────────────────────────────────────────────

def test_deterministic_same_input_same_output():
    """同输入同输出（确定性红线）。"""
    reg = {"b": _skill(ab_with=0.9), "a": _skill(ab_with=0.8)}
    hist = {"b": [0.9, 0.3, 0.3, 0.3], "a": [0.8, 0.85, 0.9]}
    r1 = health_report(reg, hist)
    r2 = health_report(reg, hist)
    assert r1 == r2
    # 输出键有序（demote 候选排序去重）
    assert r1["demote_candidates"] == sorted(r1["demote_candidates"])


def test_float_baseline_epsilon_no_jitter():
    """0.999999 vs 1.0 epsilon 容差，不抖动误判为低于基线。"""
    reg = {"s": _skill(ab_with=1.0)}
    hist = {"s": [0.999999999, 1.0, 1.0]}
    rep = health_report(reg, hist)
    s = rep["skills"]["s"]
    assert s["consecutive_below"] == 0
    assert s["demote_candidate"] is False


# ── 反模式被拒绝（红线 1：禁逐 case 硬编码）──────────────────────────────

def test_no_per_skill_hardcoding_in_source():
    """护栏：health.py 源码内不得出现逐 autoid/逐技能名硬编码分支。

    判定必须是通用数值规则（换一批技能仍成立）。检测的是真正的反模式——
    对具体数字 id（如 778012）或具体技能名做相等分支，而非「autoid」这个词
    （docstring 里说明「本模块不看 autoid」是合法的）。
    """
    import re as _re
    src = _HEALTH_PATH.read_text(encoding="utf-8")
    # 反模式 1：分支条件等于一个具体数字 id（逐 case 硬编码的典型形态）。
    assert not _re.search(r'==\s*["\']?\d{4,}["\']?', src), \
        "发现对具体数字 id 的相等分支（疑似逐 case 硬编码）"
    # 反模式 2：对具体技能名做相等分支。
    lowered = src.lower()
    for banned in ('== "settle', "== 'settle", '== "rr', "== 'rr",
                   '== "counter', '== "assertion'):
        assert banned not in lowered, f"发现逐技能硬编码分支：{banned}"


def test_generic_rule_holds_for_arbitrary_skill_names():
    """同一规则换一批任意技能名仍成立（证明非逐 case 硬编码）。"""
    reg = {f"feat_{i}_xyz": _skill(ab_with=0.7) for i in range(5)}
    hist = {f"feat_{i}_xyz": [0.7, 0.2, 0.2, 0.2] for i in range(5)}
    rep = health_report(reg, hist)
    # 全部命中同一通用降级规则
    assert sorted(rep["demote_candidates"]) == sorted(reg.keys())
    for name in reg:
        assert rep["skills"][name]["reason"] == "below_baseline_for_3_rounds"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
