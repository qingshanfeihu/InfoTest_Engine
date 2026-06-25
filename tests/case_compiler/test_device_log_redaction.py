"""device_mcp_client._redact 守护：设备/task 日志回灌 agent 上下文前必须脱敏凭据，
但**保留 IP**（dig 真实输出里的 IP 是 agent 填 <RUNTIME> 断言的必需信息，脱了就废功能）。
"""

from __future__ import annotations

import importlib

mod = importlib.import_module("main.case_compiler.device_mcp_client")
_redact = mod._redact


def test_masks_password_space_separated():
    """网络设备 CLI 的 `password <值>`（空格分隔）必须被 mask。"""
    out = _redact("Router(config)# password click1\nset secret S3cr3t!")
    assert "click1" not in out
    assert "S3cr3t!" not in out
    assert "****" in out


def test_masks_kv_forms():
    for raw, leaked in [
        ("password=hunter2", "hunter2"),
        ("passwd: topsecret", "topsecret"),
        ('api_key = "tp-abcdef123456"', "tp-abcdef123456"),
        ("auth-token foobar987", "foobar987"),
    ]:
        out = _redact(raw)
        assert leaked not in out, f"未脱敏: {raw!r} -> {out!r}"


def test_masks_snmp_community():
    """SNMP community string(`show running-config` 等设备回显可能含)必须被 mask。"""
    out = _redact("snmp-server community public RO\ncommunity: s3cr3tComm")
    assert "public" not in out
    assert "s3cr3tComm" not in out
    assert "****" in out


def test_preserves_ip_and_dig_output():
    """IP / dig ANSWER SECTION 必须原样保留（核心功能依赖）。"""
    dig = "ANSWER SECTION:\nwww.test.com. 60 IN A 10.4.127.105\nserver 10.4.127.93 admin"
    out = _redact(dig)
    assert "10.4.127.105" in out
    assert "10.4.127.93" in out
    # "admin" 不是 password 关键字后的值，且是诊断必需的用户名/提示，不应被误 mask
    assert "admin" in out


def test_empty_and_none_safe():
    assert _redact("") == ""
    assert _redact(None) == ""
