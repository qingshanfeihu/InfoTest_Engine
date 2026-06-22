"""持久化测试结构门(升级为按执行顺序的有限状态校验,P0+P1)。

仅在 case 含 config 恢复命令(memory/file/all/net)时触发——回归护栏:非持久化用例 no-op。
覆盖:基线污染 / 紧邻配对 / 清除步 / 参数完整 / 意图变体 + log_backup 金标准正向 + 非持久化放行。
"""
from __future__ import annotations

import pytest

from main.ist_core.tools.device.emit_xlsx_tool import _gate_save_restore_pairing as gate


def _mk(*cmds):
    """按顺序的 APV 配置步。"""
    return [{"E": "APV_0", "F": "cmd_config", "G": c} for c in cmds]


# ── 回归护栏:非恢复类用例一律 no-op(99% 用例不进闸)──────────────────────
def test_no_restore_command_is_noop():
    # 纯 listener+dig,无 config 恢复
    assert gate("c", _mk("sdns on", "sdns listener 172.16.34.70 53", "show sdns listener")) is None


def test_write_without_restore_is_noop():
    """有 write memory(如 ssl 同步场景)但无 config 恢复 → 不进闸(治 sdns_ssl_conn 类不被误伤)。"""
    assert gate("c", _mk("sdns on", "write memory", "sdns listener 172.16.34.70 53")) is None


# ── 668000 正确范式:放行 ─────────────────────────────────────────────
def test_valid_memory_persistence_passes():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "show sdns listener",
        "write memory",
        "no sdns listener 172.16.34.70",
        "config memory",
        "show sdns listener",
    )
    assert gate("668000", steps) is None
    assert gate("668000", steps, expected_save_variant="memory") is None


# ── log_backup 金标准:必须放行(零回归的关键)──────────────────────────
def test_log_backup_pattern_passes():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "sdns host name autotest.com",
        'write all ftp "172.16.35.231" "test" "log_backup.tgz" "click1"',
        "clear sdns all",
        'config all url "ftp://test@172.16.35.231/log_backup.tgz" "click1"',
        "show sdns all",
    )
    assert gate("logbackup", steps) is None


# ── P0a 基线污染(668015 维度一)──────────────────────────────────────
def test_baseline_pollution_rejected():
    steps = _mk(
        "write memory",                         # 配 listener 之前预存盘 → 污染
        "sdns listener 172.16.34.70 53",
        "write file test_config.cfg",
        "no sdns listener 172.16.34.70",
        "config file test_config.cfg",
    )
    msg = gate("668015", steps)
    assert msg is not None and "基线污染" in msg


# ── P0b 紧邻配对(668015 维度二)──────────────────────────────────────
def test_adjacent_pairing_cross_family_rejected():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write file test_config.cfg",
        "no sdns listener 172.16.34.70",
        "config memory",                        # 紧邻前一个 save 是 file,却用 memory 恢复
    )
    msg = gate("668015", steps)
    assert msg is not None and "不同族" in msg


# ── P1a 清除步缺失 ──────────────────────────────────────────────────
def test_missing_clear_step_rejected():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write memory",
        "config memory",                        # 没有 no/clear → 恢复空操作
        "show sdns listener",
    )
    msg = gate("c", steps)
    assert msg is not None and "清除步" in msg


# ── P1b 参数完整(668044 维度)────────────────────────────────────────
def test_bare_write_net_param_incomplete_rejected():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write net",                            # 缺 协议+ip+文件
        "no sdns listener 172.16.34.70",
        "config net",
    )
    msg = gate("668044", steps)
    assert msg is not None and "缺参数" in msg


# ── P1c 意图变体(668030 维度;manifest 透传)────────────────────────────
def test_intent_variant_swap_rejected():
    # 意图测 write all,draft 偷换成 write memory(内部自洽但变体错)
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write memory",
        "clear sdns listener",
        "config memory",
        "show sdns listener",
    )
    assert gate("668030", steps) is None                              # 不传 expected → no-op 放行
    msg = gate("668030", steps, expected_save_variant="all")          # 传了 → 抓出偷换
    assert msg is not None and "意图变体" in msg


def test_intent_variant_correct_passes():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write all ftp 172.16.35.231 backup.tgz",
        "clear sdns listener",
        "config all ftp 172.16.35.231 backup.tgz",
        "show sdns listener",
    )
    assert gate("c", steps, expected_save_variant="all") is None
