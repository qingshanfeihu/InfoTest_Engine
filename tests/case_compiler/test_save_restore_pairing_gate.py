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
    assert msg is not None and "baseline pollution" in msg


# ── P0b 紧邻配对(668015 维度二)──────────────────────────────────────
def test_adjacent_pairing_cross_family_rejected():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write file test_config.cfg",
        "no sdns listener 172.16.34.70",
        "config memory",                        # 紧邻前一个 save 是 file,却用 memory 恢复
    )
    msg = gate("668015", steps)
    assert msg is not None and "different families" in msg


# ── P1a 清除步缺失 ──────────────────────────────────────────────────
def test_missing_clear_step_rejected():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write memory",
        "config memory",                        # 没有 no/clear → 恢复空操作
        "show sdns listener",
    )
    msg = gate("c", steps)
    assert msg is not None and "missing clear step" in msg


# ── P1b 参数完整(668044 维度)────────────────────────────────────────
def test_bare_write_net_param_incomplete_rejected():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write net",                            # 缺 协议+ip+文件
        "no sdns listener 172.16.34.70",
        "config net",
    )
    msg = gate("668044", steps)
    assert msg is not None and "missing argument" in msg


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
    assert msg is not None and "intent variant" in msg


def test_intent_variant_correct_passes():
    steps = _mk(
        "sdns listener 172.16.34.70 53",
        "write all ftp 172.16.35.231 backup.tgz",
        "clear sdns listener",
        "config all ftp 172.16.35.231 backup.tgz",
        "show sdns listener",
    )
    assert gate("c", steps, expected_save_variant="all") is None


# ── P1c 证据源修正(2026-07-14 run20 实弹):expected 从引擎盖章的 intent.json 推导 ──
# 此前仅 worker 自我申报——漂移的 worker 恰恰不会申报(668030 write all→memory 静默
# 换机制,P1c no-op 放行)。现 emit 消费端从 outputs/<autoid>/intent.json(author 派发
# 时从 manifest 原文盖章)用闭集词表自行推导,申报降级为兜底。

import json as _json
import shutil as _shutil
from pathlib import Path as _Path

from main.ist_core.tools.device.emit_xlsx_tool import _intent_save_variant

_OUT = _Path(__file__).resolve().parents[2] / "workspace" / "outputs"


def _stamp(autoid: str, title: str):
    d = _OUT / autoid
    d.mkdir(parents=True, exist_ok=True)
    (d / "intent.json").write_text(_json.dumps(
        {"autoid": autoid, "title": title, "step_intents": [],
         "source": "manifest", "stamped_by": "engine.author"}, ensure_ascii=False),
        encoding="utf-8")
    return d


def test_intent_variant_derived_from_stamped_manifest_cjk():
    """668030 形态:标题「执行write all后重启」(族词后紧邻 CJK)→ 推导 all。"""
    aid = "t_intent_all"
    d = _stamp(aid, "1.配置port 为53.执行write all后重启设备\n2.查看sdns listener  [check1]")
    try:
        assert _intent_save_variant(aid) == "all"
        # 卷面用 memory(漂移)→ P1c 必须拦(即便 worker 不申报 expected)
        steps = _mk("sdns listener 172.16.34.70 53", "show sdns listener",
                    "write memory", "no sdns listener 172.16.34.70",
                    "config memory", "show sdns listener")
        err = gate(aid, steps, expected_save_variant=_intent_save_variant(aid))
        assert err and "intent variant mismatch" in err and "write all" in err
    finally:
        _shutil.rmtree(d, ignore_errors=True)


def test_intent_variant_mem_abbrev_normalized():
    """668000 形态:「执行write mem后重启」→ 推导 memory;卷面 memory → 放行。"""
    aid = "t_intent_mem"
    d = _stamp(aid, "1.配置port 为53.执行write mem后重启设备")
    try:
        assert _intent_save_variant(aid) == "memory"
        steps = _mk("sdns listener 172.16.34.70 53", "show sdns listener",
                    "write memory", "no sdns listener 172.16.34.70",
                    "config memory", "show sdns listener")
        assert gate(aid, steps, expected_save_variant=_intent_save_variant(aid)) is None
    finally:
        _shutil.rmtree(d, ignore_errors=True)


def test_intent_variant_absent_falls_back_noop():
    """无盖章文件 → 推导空 → P1c 维持既有 no-op(非引擎路径/存量零回归)。"""
    assert _intent_save_variant("t_intent_absent_xyz") == ""


def test_intent_variant_no_save_word_is_empty():
    """意图无保存族词(如 668059 全域名案)→ 推导空,不误伤。"""
    aid = "t_intent_nosave"
    d = _stamp(aid, "1.配置sdns listener,使用全域名功能  [check1]")
    try:
        assert _intent_save_variant(aid) == ""
    finally:
        _shutil.rmtree(d, ignore_errors=True)


# ── P1c 提门(2026-07-14 §18.11 评审 D2):变体核对不再以 restore 存在为前提 ──────

def test_p1c_fires_without_restore_on_variant_swap():
    """F6 正解卷形态(write→clear→断言,无回放):expected=all 而卷面 write memory
    → 漂移被拦(旧触发条件下 P1c 对此形态永不运行)。"""
    steps = _mk("sdns on", "sdns listener 172.16.34.70 53", "show sdns listener",
                "write memory", "clear sdns listener", "show sdns listener")
    err = gate("t_p1c_lift", steps, expected_save_variant="all")
    assert err and "intent variant mismatch" in err and "write all" in err


def test_p1c_no_save_cmd_skips():
    """卷面无保存命令 → 不查(负向意图「不执行保存」合法存在,缺席检查会误杀)。"""
    steps = _mk("sdns on", "sdns listener 172.16.34.70 53", "show sdns listener",
                "clear sdns listener", "show sdns listener")
    assert gate("t_p1c_nosave", steps, expected_save_variant="all") is None


def test_p1c_matching_variant_without_restore_passes():
    """expected=file 且卷面 write file(F6 正解形态)→ 放行。"""
    steps = _mk("sdns on", "sdns listener 172.16.34.70 53", "show sdns listener",
                "write file sdns_save_x", "clear sdns listener", "show sdns listener")
    assert gate("t_p1c_ok", steps, expected_save_variant="file") is None
