"""安全门:拒绝 reboot/reload/shutdown 等破坏性设备生命周期命令。

理由(与意图无关、确定性):①共享设备会被真重启/关停;②框架单连接无重连,重启后必 fail。
持久化测试应走 clear→恢复 范式(不重启),本门**不得误伤** clear/config(范式要用)。
"""
from __future__ import annotations

import pytest

from main.ist_core.tools.device.emit_xlsx_tool import _gate_destructive_commands as gate


@pytest.mark.parametrize("cmd", [
    "system reboot noninteractive",
    "system reboot",
    "reboot",
    "system shutdown",
    "shutdown",
    "reload",
    "halt",
    "poweroff",
])
def test_blocks_destructive(cmd):
    msg = gate("c", [{"E": "APV_0", "F": "cmd_config", "G": cmd}])
    assert msg is not None
    assert "destructive" in msg


def test_passes_clear_restore_pattern():
    """clear→restore 持久化范式必须放行(不能被误伤)。"""
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "write memory"},
        {"E": "APV_0", "F": "cmd_config", "G": "clear sdns all"},
        {"E": "APV_0", "F": "cmd_config", "G": "config memory"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
    ]
    assert gate("c", steps) is None


def test_catches_in_init_and_multiline():
    steps = [{"E": "APV_0", "F": "cmds_config", "G": "sdns on\nsystem reboot\nsdns listener 1.2.3.4"}]
    assert gate("c", steps) is not None
    # init 里也查
    assert gate("c", [], init="write memory\nreload") is not None


def test_ignores_nonconfig_and_substrings():
    """非 APV 配置步不查;'reboot' 作为子串(如 prebooting)不应误伤命令词匹配。"""
    # check_point 文本里出现 reboot 字样(断言期望,不是要执行的命令)→ 不拦
    assert gate("c", [{"E": "check_point", "F": "found", "G": "system is rebooting"}]) is None
    # 词边界:reboothack 不是 reboot 命令词
    assert gate("c", [{"E": "APV_0", "F": "cmd_config", "G": "show reboothack"}]) is None
