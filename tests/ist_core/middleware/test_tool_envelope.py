"""工具结果统一信封 + fork 中间件对齐 + 框架真相一致性门(2026-07-05 三坑修复回归)。

坑1:XML 散在单工具手改(3/36 覆盖,fork 全漏)→ wrap_tool_call 横切层统一信封;
坑2:fork 只挂 LoopGuard → 三件套对齐;
坑4(APV_1 事故的机械化):手写参考文档与框架源码漂移 → 一致性门。
"""

from __future__ import annotations

import re
from pathlib import Path

from langchain_core.messages import ToolMessage

import main.ist_core.middleware.tool_envelope as te

_ROOT = Path(__file__).resolve().parents[3]


class _Req:
    def __init__(self, name):
        self.tool_call = {"name": name, "args": {}, "id": "t1"}


def test_envelope_ok_and_error_status():
    ok = te.envelope_text("dev_probe", "APV# show version\nOK")
    assert ok.startswith('<tool_result name="dev_probe" status="ok">')
    assert ok.rstrip().endswith("</tool_result>")
    err = te.envelope_text("compile_emit", "error: case X 步骤载荷为空")
    assert 'status="error"' in err


def test_envelope_idempotent_and_nested_tags_kept():
    once = te.envelope_text("invoke_skill", "<skill_content name=\"x\">正文</skill_content>")
    assert once.count("<tool_result") == 1 and "<skill_content" in once   # 内层自标签保留
    twice = te.envelope_text("invoke_skill", once)
    assert twice == once   # 幂等


def test_parse_envelope_roundtrip_and_multiline():
    body = "APV# show version\n第 2 行\n第 3 行"
    name, status, parsed = te.parse_tool_result_envelope(te.envelope_text("dev_probe", body))
    assert (name, status, parsed) == ("dev_probe", "ok", body)
    # error status 往返
    err_body = "error: case X 步骤载荷为空"
    _, st, pb = te.parse_tool_result_envelope(te.envelope_text("compile_emit", err_body))
    assert st == "error" and pb == err_body


def test_parse_envelope_missing_close_tag():
    """ToolResultPrune 剪过的旧消息可能只剩前半段——缺闭标签取开标签后全部。"""
    truncated = '<tool_result name="fs_read" status="ok">\n前 160 字符…[已剪枝]'
    name, status, body = te.parse_tool_result_envelope(truncated)
    assert name == "fs_read" and status == "ok"
    assert body == "前 160 字符…[已剪枝]"


def test_parse_envelope_nested_inner_tags():
    """内层嵌套节保留在 body;闭标签取最后一个(rfind)。"""
    inner = '<skill_content name="x">正文</skill_content>'
    wrapped = te.envelope_text("invoke_skill", inner)
    _, _, body = te.parse_tool_result_envelope(wrapped)
    assert body == inner


def test_parse_envelope_non_envelope_returns_none():
    assert te.parse_tool_result_envelope("普通文本 <tool_result 不在开头") is None
    assert te.parse_tool_result_envelope("") is None
    assert te.parse_tool_result_envelope(None) is None  # type: ignore[arg-type]
    # 开头像信封但 header 结构不符 → None(调用方按原文用)
    assert te.parse_tool_result_envelope("<tool_result 坏标签没有属性>x") is None


def test_wrap_toolmessage_and_passthrough(monkeypatch):
    msg = ToolMessage(content="设备回显…", name="dev_probe", tool_call_id="t1")
    out = te._wrap(_Req("dev_probe"), msg)
    assert isinstance(out, ToolMessage)
    assert out.content.startswith('<tool_result name="dev_probe"')
    assert msg.content == "设备回显…"          # 原对象不动
    # 非 ToolMessage(Command 等控制流)原样返回
    sentinel = object()
    assert te._wrap(_Req("x"), sentinel) is sentinel
    # 关闭开关 → 原样
    monkeypatch.setenv("IST_TOOL_ENVELOPE", "0")
    assert te._wrap(_Req("dev_probe"), msg) is msg


def test_fork_middleware_aligned():
    from main.ist_core.skills.loader import _build_fork_middleware
    names = {type(m).__name__ for m in _build_fork_middleware()}
    assert {"LoopGuardMiddleware", "ToolResultPruneMiddleware", "ToolEnvelopeMiddleware"} <= names
    assert "ToolGatingMiddleware" not in names   # fork 白名单已显式,不挂 gating


def test_reference_doc_covers_framework_dut_slots():
    """框架真相一致性门:EXCEL_FUNCTIONS 的 E 表必须覆盖框架源码的全部被测设备槽。

    APV_1 事故(2026-07-05):框架原生双机,参考文档只写了 APV_0——worker 无据可依
    退 steps 通道硬凑。文档漂移从此机械捕捉。
    """
    fw = (_ROOT / "knowledge" / "framework" / "mirror" / "lib" / "test_xlsx.py")
    if not fw.is_file():
        import pytest
        pytest.skip("框架 mirror 不在盘上")
        return
    src = fw.read_text(encoding="utf-8", errors="replace")
    duts = set(re.findall(r"'(APV_\d+)':\s*None", src))
    assert duts, "框架源码未解析出设备槽(结构变了?更新本门)"
    doc = (_ROOT / "knowledge" / "data" / "compile_ref" / "EXCEL_FUNCTIONS.md").read_text(encoding="utf-8")
    missing = [d for d in duts if d not in doc]
    assert not missing, f"EXCEL_FUNCTIONS.md 漏了框架设备槽: {missing}(参考文档又漂移了)"


def test_blocks_apv1_dual_device():
    """blocks 组合子的双机表达(坑修复):CONFIG.host/观测 host 支持 APV_1。"""
    from main.case_compiler.blocks import expand_blocks
    steps, _, err = expand_blocks([
        {"kind": "CONFIG", "host": "APV_1", "cmds": ["sdns on", "sdns listener 172.16.34.71"], "desc": "bAPV 基线"},
        {"kind": "OBSERVE_ASSERT", "host": "APV_1", "cmd": "show sdns listener",
         "asserts": [{"op": "found", "pattern": "172\\.16\\.34\\.71", "desc": "监听在位"}]},
    ])
    assert err is None
    assert steps[0]["E"] == "APV_1" and steps[0]["F"] == "cmds_config"
    assert steps[1]["E"] == "APV_1" and steps[1]["F"] == "cmd_config"
    # 非法 host 拒绝
    _, _, err2 = expand_blocks([{"kind": "CONFIG", "host": "APV_9", "cmds": ["x"]}])
    assert err2 and "APV_9" in err2
