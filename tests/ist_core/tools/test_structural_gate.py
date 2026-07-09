"""v2 结构约束门测试（命题3.18 correct-by-construction）。

验证：命令 allowlist + 断言非悬空确定性可判；v1（strict_structural=False）行为不变。
"""

from __future__ import annotations

from main.ist_core.tools.device.structural_gate import (
    _command_head_tokens,
    check_structural_constraints,
)


def test_command_head_tokens_strips_prefix_and_values():
    # 含记法/具体值 token 处截断；模块头（首 token）必准——allowlist 只用首 token。
    assert _command_head_tokens("sdns listener 172.16.34.70 53") == ["sdns", "listener"]
    assert _command_head_tokens("show sdns service status") == ["sdns", "service", "status"]
    assert _command_head_tokens("clear sdns listener") == ["sdns", "listener"]
    # 前缀剥离后首 token 即模块名
    assert _command_head_tokens("no slb real http rs1")[0] == "slb"


def test_dangling_assertion_detected_when_no_observation():
    # check_point 紧跟在 cmds_config(多条配置,框架遍历不收返回 → result=None)后 → found(None)
    # 抛 TypeError 崩整份文件 = 真 dangling。(单条 cmd_config 返回 output 非 None、不崩,见下方正向用例)
    steps = [
        {"E": "APV_0", "F": "cmds_config", "G": "sdns listener 172.16.34.70"},
        {"E": "check_point", "F": "found", "G": "172.16.34.70"},
    ]
    res = check_structural_constraints("c1", steps)
    assert not res.ok
    assert any(v.code == "dangling_assertion" for v in res.violations)


def test_single_cmd_config_failure_echo_not_dangling():
    # 单条 cmd_config(apv_ssh.py:151 `return output`)即使失败也回显错误文字(非 None)——框架 result
    # 可被 found re.search、不抛 TypeError、不崩。994957「10 pool 上限」断言 found "A maximum of 10"
    # 正挂在失败 cmd_config 回显上,合法、非 dangling(锁住 problem12 修复不被回退)。
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns host pool autotest.com p11"},
        {"E": "check_point", "F": "found", "G": "A maximum of 10"},
    ]
    res = check_structural_constraints("c1", steps)
    assert not any(v.code == "dangling_assertion" for v in res.violations)


def test_assertion_ok_when_preceded_by_observation():
    # show 产出回显 → 后续断言有值域可挂
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 172.16.34.70"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
        {"E": "check_point", "F": "found", "G": "172.16.34.70"},
    ]
    res = check_structural_constraints("c2", steps)
    dangling = [v for v in res.violations if v.code == "dangling_assertion"]
    assert not dangling


def test_assertion_ok_when_test_env_triggers():
    # test_env 触发（dig）天然产出回显
    steps = [
        {"E": "test_env", "F": "clientc", "G": "dig @172.16.34.70 www.example.com"},
        {"E": "check_point", "F": "found", "G": "1.2.3.4"},
    ]
    res = check_structural_constraints("c3", steps)
    dangling = [v for v in res.violations if v.code == "dangling_assertion"]
    assert not dangling


def test_open_assertion_at_start_is_dangling():
    steps = [
        {"E": "check_point", "F": "found", "G": "anything"},
    ]
    res = check_structural_constraints("c4", steps)
    assert not res.ok
    assert res.violations[0].code == "dangling_assertion"
    assert res.violations[0].step_index == 0


def test_render_is_human_readable():
    steps = [{"E": "check_point", "F": "found", "G": "x"}]
    res = check_structural_constraints("c5", steps)
    text = res.render("c5")
    assert "c5" in text
    assert "structural constraints" in text
