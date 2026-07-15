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


def test_annotate_flag_gates_empty_probe_note(monkeypatch):
    """回归#3 修法A(分离关注点):空探针的时机语义 note 是**给 worker 的便利**,
    机器消费者(bed 残留检测)不该吃它——`annotate=False` 返回原始设备事实、不拼 note。

    worker 侧(默认 annotate=True)保留 note(不回归 OBS-15);bed 侧(annotate=False)无 note。"""
    # body 为空的成功回显(仅 command/status 头,无设备内容)——clean 床上 show segment 恒此形态
    monkeypatch.setattr(
        mcp, "probe_via_fastmcp",
        lambda *a, **k: {"text": "command: show segment name\nstatus: success\n"})
    worker = rc._do_probe("show segment name")                    # 默认 annotate=True
    bed = rc._do_probe("show segment name", annotate=False)
    assert "re-probing emptiness" in worker                       # worker 便利提示保留
    assert "re-probing emptiness" not in bed                      # bed 拿原始事实,零 note
    assert bed.startswith("=== dev_probe (fastmcp apv_ssh) ===")  # 仍是探针原文(banner 在)


def test_annotate_default_true_preserves_worker_behavior(monkeypatch):
    """默认(不传 annotate)＝旧行为:空探针仍附 note——现存 worker 调用点零回归。"""
    monkeypatch.setattr(
        mcp, "probe_via_fastmcp",
        lambda *a, **k: {"text": "command: show statistics sdns pool\nstatus: success\n"})
    assert "re-probing emptiness" in rc._do_probe("show statistics sdns pool")
