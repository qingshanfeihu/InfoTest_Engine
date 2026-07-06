"""命中归属锚点断言辅助（membership_assertion）单测：成员集正则 / 校验门 / 展开。"""

from __future__ import annotations

import re

import pytest

from main.case_compiler.membership_assertion import (
    member_regex_for_ips,
    validate_membership,
    expand_membership_step,
    expand_membership_steps,
)


# ── member_regex_for_ips：alternation + 词边界 ───────────────────────────────────

def test_member_regex_single_ip_matches_and_boundary():
    g = member_regex_for_ips(["172.16.35.226"])
    assert re.search(g, "resolved to 172.16.35.226 ok")
    assert not re.search(g, "172.16.35.2264")   # 前缀重叠不误配
    assert not re.search(g, "172.16.35.22")     # 子串不误配


def test_member_regex_multi_ip_alternation():
    g = member_regex_for_ips(["172.16.35.226", "172.16.35.232"])
    assert re.search(g, "172.16.35.226")
    assert re.search(g, "172.16.35.232")
    assert not re.search(g, "172.16.35.233")


def test_member_regex_ipv6_boundary():
    g = member_regex_for_ips(["3ffd::104"])
    assert re.search(g, "ANSWER: 3ffd::104")
    assert not re.search(g, "3ffd::1044")       # 前缀重叠不误配
    assert not re.search(g, "23ffd::104")       # 前面粘连不误配


def test_member_regex_escapes_dots_not_colons():
    g = member_regex_for_ips(["1.2.3.4"])
    assert r"1\.2\.3\.4" in g
    g6 = member_regex_for_ips(["::1"])
    assert "::1" in g6 and "\\:" not in g6      # 冒号不是正则元字符，不应被转义


# ── validate_membership：结构校验门 ──────────────────────────────────────────────

def test_validate_ok():
    assert validate_membership(["172.16.35.226"], True) is None
    assert validate_membership(["172.16.35.226", "3ffd::104"], False) is None


def test_validate_rejects_empty_ips():
    err = validate_membership([], True)
    assert err and "非空列表" in err


def test_validate_rejects_non_list_ips():
    err = validate_membership("172.16.35.226", True)
    assert err and "非空列表" in err


def test_validate_rejects_non_ip_item():
    err = validate_membership(["p4"], True)
    assert err and "不像一个 IP 地址字面量" in err


def test_validate_rejects_non_bool_present():
    err = validate_membership(["172.16.35.226"], "yes")
    assert err and "present" in err


# ── expand_membership_step：1 步 → 1 条 found/not_found ──────────────────────────

def test_expand_present_true_yields_found():
    step = {"E": "check_point", "F": "member",
            "member": {"ips": ["172.16.35.226", "172.16.35.232"], "present": True}}
    out, err = expand_membership_step(step)
    assert err is None
    assert out["E"] == "check_point" and out["F"] == "found"
    assert re.search(out["G"], "172.16.35.226")


def test_expand_present_false_yields_not_found():
    step = {"E": "check_point", "F": "member",
            "member": {"ips": ["172.16.35.226"], "present": False}}
    out, err = expand_membership_step(step)
    assert err is None
    assert out["F"] == "not_found"


def test_expand_bad_step_returns_error():
    step = {"E": "check_point", "F": "member", "member": {"ips": [], "present": True}}
    out, err = expand_membership_step(step)
    assert out is None and err is not None


def test_expand_custom_desc_preserved():
    step = {"E": "check_point", "F": "member",
            "member": {"ips": ["1.1.1.1"], "present": True, "desc": "自定义描述"}}
    out, err = expand_membership_step(step)
    assert err is None and out["desc"] == "自定义描述"


# ── expand_membership_steps：混合列表，member 步 1:1 展开、其余原样通过 ────────────

def test_expand_steps_mixed_passthrough_and_expand():
    steps = [
        {"E": "test_env", "F": "routera", "G": "dig ..."},
        {"E": "check_point", "F": "member", "member": {"ips": ["1.1.1.1"], "present": True}},
        {"E": "APV_0", "F": "cmd_config", "G": "show version"},
    ]
    new_steps, err = expand_membership_steps(steps)
    assert err is None
    assert len(new_steps) == 3          # 1:1，长度不变
    assert new_steps[0] is steps[0]     # 非 member 步原样通过
    assert new_steps[1]["F"] == "found"
    assert new_steps[2] is steps[2]


def test_expand_steps_propagates_error():
    steps = [{"E": "check_point", "F": "member", "member": {"ips": ["not_an_ip"], "present": True}}]
    new_steps, err = expand_membership_steps(steps)
    assert new_steps is None and err is not None


def test_expand_steps_no_member_declarations_unchanged():
    steps = [{"E": "test_env", "F": "routera", "G": "dig ..."}]
    new_steps, err = expand_membership_steps(steps)
    assert err is None and new_steps == steps
