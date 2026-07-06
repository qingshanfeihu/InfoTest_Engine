"""device_errors —— 设备 CLI 错误识别的行为契约。

纯标准库模块，可安全 import。覆盖：
  - 正向：设备真实报错回显（含新增措辞 + 孤立 ^ 行）→ has_cli_error True。
  - 反向（防误杀）：正常 show 回显 → has_cli_error False。
  - has_caret_error 单独覆盖。
"""

from __future__ import annotations

import pytest

from main.ist_core.tools.device.device_errors import (
    DEVICE_CLI_ERROR_MARKERS,
    has_caret_error,
    has_cli_error,
)


# —— 正向：应判为错误 ——
@pytest.mark.parametrize(
    "text",
    [
        "Failed to execute the command",
        # 实测完整回显：具体原因行 + 设备统一失败裁决行；靠通用 "failed to execute" 识别，不穷举业务措辞
        "Query type not support.\nFailed to execute the command",
        "Domain name or network or query type not found.\nFailed to execute the command",
        "% Invalid input: command 'x' is invalid",
        "show foo\n          ^\n% Unknown command",  # 孤立 ^ 行
        "% Error: bad argument",
        "syntax error near token",
    ],
)
def test_has_cli_error_positive(text):
    assert has_cli_error(text) is True


# —— 反向：正常回显，不得误杀 ——
@pytest.mark.parametrize(
    "text",
    [
        'sdns host persistence 3600 "www.zyq.com" enable',
        "0 sessions",
        "Total 3 entries\nname: www.example.com  ip: 10.4.127.103",
        "interface port1 up\nspeed 1000Mbps",
        "",  # 空串不报错
        "OK",
    ],
)
def test_has_cli_error_negative(text):
    assert has_cli_error(text) is False


# —— has_caret_error 单独覆盖 ——
def test_has_caret_error_isolated_line():
    assert has_caret_error("dig www.x.com\n   ^\n% error") is True


def test_has_caret_error_short_line_with_caret():
    assert has_caret_error("cmd\n ^^\nfoo") is True


def test_has_caret_error_no_caret():
    assert has_caret_error("show host persistence\n0 sessions") is False


def test_has_caret_error_caret_inside_long_line_not_flagged():
    # 长行内含 ^（如说明文字），不视为孤立报错行
    assert has_caret_error("the regex pattern ^abc matches the start of line") is False


def test_has_caret_error_empty():
    assert has_caret_error("") is False


# —— marker 表完整性：历史 + 新增措辞均在表内 ——
def test_markers_contain_legacy_and_new():
    for legacy in (
        "% invalid", "% error", "% unknown", "% unrecognized",
        "syntax error", "invalid input", "command not found",
    ):
        assert legacy in DEVICE_CLI_ERROR_MARKERS
    # 新增只有一条「设备统一失败裁决」——不穷举各业务命令的具体措辞
    assert "failed to execute" in DEVICE_CLI_ERROR_MARKERS
    # 业务具体短语刻意不进表（靠 "failed to execute" 通用裁决覆盖；防回退到穷举措辞）
    for absent in ("query type not support", "not supported",
                   "query type not found", "% invalid input"):
        assert absent not in DEVICE_CLI_ERROR_MARKERS
    # 全小写
    assert all(m == m.lower() for m in DEVICE_CLI_ERROR_MARKERS)
