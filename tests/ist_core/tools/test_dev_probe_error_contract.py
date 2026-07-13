"""_do_probe 失败契约:失败必须返回 'error:' 前缀裸文本(不包来源横幅)。

2026-07-13 实弹:fastmcp 服务端把设备 SSH 失败以 "error: SSH to X failed" 文本返回,
_do_probe 曾照常包横幅(=== dev_probe (fastmcp apv_ssh) ===\nerror: ...)——下游床态
_probe_failed 按首行契约识别工具级失败,包了横幅就穿门:105 床 SSH 挂死被报成
"分区配置残留"+「版本不匹配:设备(空)」,93 床账入 4 条垃圾 created。
"""
from __future__ import annotations

import main.ist_core.tools.device.run_case as rc
import main.case_compiler.device_mcp_client as mcp


def test_fastmcp_error_text_returned_bare(monkeypatch):
    """fastmcp 返回 error 契约文本 → 原样裸返(首行即 error,零横幅)。"""
    monkeypatch.setattr(
        mcp, "probe_via_fastmcp",
        lambda *a, **k: {"text": "error: SSH to 1.2.3.4 failed: [Errno None] "
                                 "Unable to connect to port 22 on 1.2.3.4"})
    out = rc._do_probe("show version")
    assert out.startswith("error:")
    assert "===" not in out


def test_fastmcp_normal_text_keeps_banner(monkeypatch):
    """正常回显仍带来源横幅(契约只对失败文本生效)。"""
    monkeypatch.setattr(
        mcp, "probe_via_fastmcp",
        lambda *a, **k: {"text": "command: show version\nstatus: success\n"
                                 " Software Version : InfosecOS Beta.APV-HG-K.10.5.0.585"})
    out = rc._do_probe("show version")
    assert out.startswith("=== dev_probe (fastmcp apv_ssh) ===")
    assert "Software Version" in out
