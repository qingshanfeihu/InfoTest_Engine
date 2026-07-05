"""工具结果剪枝回归(2026-07-05,MiMo-Code prune 移植)。

守:确定性(同入同出)、保护面(最近轮/invoke_skill/ask_user/小结果)、
非破坏性(原消息对象不动)、起剪门槛(小收益不破缓存)、头部保留(指针幸存)。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import main.ist_core.middleware.tool_result_prune as trp


def _tm(name: str, text: str, tid: str = "t") -> ToolMessage:
    return ToolMessage(content=text, name=name, tool_call_id=tid)


def _history(old_tool: ToolMessage) -> list:
    """[旧轮(含被测工具结果)] + [两个近轮(受保护)]"""
    return [
        HumanMessage(content="第一轮请求"),
        AIMessage(content="做事"),
        old_tool,
        HumanMessage(content="第二轮请求"),
        AIMessage(content="继续"),
        _tm("fs_read", "近轮结果" * 8000, "t2"),
        HumanMessage(content="第三轮请求(当前)"),
    ]


def test_old_big_result_pruned_head_kept(monkeypatch):
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "5000")
    big = "指针:workspace/outputs/x/last_run.json\n" + "明细行\n" * 10000
    msgs = _history(_tm("dev_run_batch", big, "t1"))
    out = trp.prune_messages(msgs)
    assert out is not msgs
    pruned = out[2].content
    assert pruned.startswith("指针:workspace/outputs/x/last_run.json")   # 头部指针幸存
    assert "已剪枝" in pruned and len(pruned) < 600
    # 非破坏:原对象没动;近轮结果原样
    assert msgs[2].content == big
    assert out[5] is msgs[5]


def test_recent_turns_protected(monkeypatch):
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "5000")
    msgs = [
        HumanMessage(content="当前轮"),
        AIMessage(content="干"),
        _tm("dev_run_batch", "x" * 50_000, "t1"),   # 属最近 2 轮内
    ]
    assert trp.prune_messages(msgs) is msgs


def test_protected_tools_never_pruned(monkeypatch):
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "5000")
    msgs = _history(_tm("invoke_skill", "skill 正文" * 20000, "t1"))
    assert trp.prune_messages(msgs) is msgs


def test_small_results_exempt(monkeypatch):
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "100")
    msgs = _history(_tm("fs_grep", "短结果" * 100, "t1"))   # < _MIN_PRUNE_CHARS
    assert trp.prune_messages(msgs) is msgs


def test_prune_minimum_gate(monkeypatch):
    # 可剪总量 < 20k → 不动手(不值得破缓存)
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "1000")
    msgs = _history(_tm("fs_grep", "y" * 3000, "t1"))   # 超预算但仅 3k 可剪
    assert trp.prune_messages(msgs) is msgs


def test_deterministic(monkeypatch):
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "5000")
    msgs = _history(_tm("dev_run_batch", "z" * 40_000, "t1"))
    a = trp.prune_messages(msgs)
    b = trp.prune_messages(msgs)
    assert [m.content for m in a] == [m.content for m in b]


def test_pruned_envelope_stays_balanced(monkeypatch):
    # 中间件交互(2026-07-05):ToolEnvelope 包的 <tool_result> 被剪枝后,闭标签必须补回。
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "5000")
    from main.ist_core.middleware.tool_envelope import envelope_text
    big = envelope_text("dev_run_batch", "指针:workspace/x/last_run.json\n" + "日志\n" * 10000)
    msgs = _history(_tm("dev_run_batch", big, "t1"))
    out = trp.prune_messages(msgs)
    pruned = out[2].content
    assert pruned.count("<tool_result") == 1 and pruned.count("</tool_result>") == 1
    assert pruned.startswith("<tool_result") and pruned.rstrip().endswith("</tool_result>")


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("IST_PRUNE_TOOL_OUTPUTS", "0")
    monkeypatch.setenv("IST_PRUNE_PROTECT_CHARS", "5000")
    msgs = _history(_tm("dev_run_batch", "z" * 40_000, "t1"))

    class _Req:
        def __init__(self, messages):
            self.messages = messages
        def override(self, **kw):
            raise AssertionError("禁用时不应 override")

    out = trp.ToolResultPruneMiddleware()._pruned(_Req(msgs))
    assert out.messages is msgs
