"""单调门回归(2026-07-09,理论 §2.4 守恒律的可判定投影)。

事故:035644/644 在 frozen override 压力下重编时删掉会 fail 的 AAAA 断言——意图
「请求 A 或 AAAA」的 AAAA 半边被静默砍掉,真 fail 变假 PASS 还写回毒先例。
门语义:重编(outputs/<autoid>/case.xlsx 已存在)不得静默移除旧卷的观测维度
(观测动词类 / DNS 记录类型);改断言文本/期望值自由;显式声明
coverage_reduction_reason 放行(用户改需求缩范围是合法路径)。
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from main.ist_core.tools.device import compile_emit

AID = "203031750000000202"

_BASE_CONFIG = {
    "D": "配置基线", "E": "APV_0", "F": "cmds_config",
    "G": "sdns on\nsdns listener 172.16.34.70\nsdns host name t.com\nsdns service ip s1 172.16.35.213\nsdns pool name p1\nsdns pool service p1 s1\nsdns host pool t.com p1",
}

_STEPS_A_AAAA = [
    _BASE_CONFIG,
    {"D": "触发A", "E": "test_env", "F": "routera", "G": "dig @172.16.34.70 t.com A"},
    {"D": "断言A", "E": "check_point", "F": "found", "G": r"\b172\.16\.35\.213\b"},
    {"D": "触发AAAA", "E": "test_env", "F": "routera", "G": "dig @172.16.34.70 t.com AAAA"},
    {"D": "断言AAAA", "E": "check_point", "F": "found", "G": "ANSWER"},
]

_STEPS_A_ONLY = [
    _BASE_CONFIG,
    {"D": "触发A", "E": "test_env", "F": "routera", "G": "dig @172.16.34.70 t.com A"},
    {"D": "断言A", "E": "check_point", "F": "found", "G": r"\b172\.16\.35\.213\b"},
]


@pytest.fixture()
def volume_with_aaaa():
    out = compile_emit.invoke({"autoid": AID, "steps": _STEPS_A_AAAA, "out_name": AID})
    assert "produced structurally-correct" in out, out
    yield Path("workspace/outputs") / AID / "case.xlsx"
    shutil.rmtree(Path("workspace/outputs") / AID, ignore_errors=True)


def test_fresh_emit_not_gated(volume_with_aaaa):
    # fixture 本身即首发(无旧卷)成功——门只作用于重编
    assert volume_with_aaaa.is_file()


def test_recompile_dropping_record_type_blocked(volume_with_aaaa):
    out = compile_emit.invoke({"autoid": AID, "steps": _STEPS_A_ONLY, "out_name": AID})
    assert out.startswith("error: monotonicity gate"), out
    assert "AAAA" in out


def test_declared_reduction_allowed(volume_with_aaaa):
    out = compile_emit.invoke({
        "autoid": AID, "steps": _STEPS_A_ONLY, "out_name": AID,
        "coverage_reduction_reason": "user re-scoped the case to A-only per ask_user decision"})
    assert "produced structurally-correct" in out, out


def test_assertion_text_change_allowed(volume_with_aaaa):
    steps = [dict(s) for s in _STEPS_A_AAAA]
    steps[2] = dict(steps[2], G=r"\b172\.16\.35\.21[34]\b")  # 修期望值,观测维度不变
    out = compile_emit.invoke({"autoid": AID, "steps": steps, "out_name": AID})
    assert "produced structurally-correct" in out, out


def test_config_mechanism_swap_allowed(volume_with_aaaa):
    # 配置段换法(非观测步)不触发门
    steps = [dict(s) for s in _STEPS_A_AAAA]
    steps[0] = dict(steps[0], G=steps[0]["G"] + "\nsdns host method t.com rr")
    out = compile_emit.invoke({"autoid": AID, "steps": steps, "out_name": AID})
    assert "produced structurally-correct" in out, out


def test_adding_dimension_allowed(volume_with_aaaa):
    # 先声明缩到 A-only,再把 AAAA 加回来——增维方向永远放行
    out = compile_emit.invoke({
        "autoid": AID, "steps": _STEPS_A_ONLY, "out_name": AID,
        "coverage_reduction_reason": "narrowing for test"})
    assert "produced structurally-correct" in out, out
    out2 = compile_emit.invoke({"autoid": AID, "steps": _STEPS_A_AAAA, "out_name": AID})
    assert "produced structurally-correct" in out2, out2
