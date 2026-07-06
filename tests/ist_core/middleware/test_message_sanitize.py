"""悬空 tool_calls 消毒回归(2026-07-05 dongkl 重测:截断历史锁死会话在供应商 400)。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from main.ist_core.middleware.message_sanitize import sanitize_messages


def _ai_with_calls(*ids):
    return AIMessage(content="", tool_calls=[
        {"id": i, "name": "ask_user", "args": {}} for i in ids])


def test_dangling_call_gets_stub():
    msgs = [HumanMessage(content="q"), _ai_with_calls("c1"), HumanMessage(content="next")]
    out = sanitize_messages(msgs)
    assert out is not msgs
    assert out[2].type == "tool" and out[2].tool_call_id == "c1" and "截断" in out[2].content
    assert out[3].content == "next"


def test_partial_answers_only_missing_stubbed():
    msgs = [_ai_with_calls("a", "b"), ToolMessage(content="ok", name="x", tool_call_id="a"),
            HumanMessage(content="next")]
    out = sanitize_messages(msgs)
    stubs = [m for m in out if m.type == "tool" and m.tool_call_id == "b"]
    assert len(stubs) == 1
    # 插在 tool 段之后、human 之前(保持连续 tool 段)
    assert out[2].tool_call_id == "b" and out[3].content == "next"


def test_complete_history_untouched():
    msgs = [_ai_with_calls("a"), ToolMessage(content="ok", name="x", tool_call_id="a")]
    assert sanitize_messages(msgs) is msgs


def test_multiple_dangling_spots():
    msgs = [_ai_with_calls("a"), HumanMessage(content="m"), _ai_with_calls("b"), HumanMessage(content="n")]
    out = sanitize_messages(msgs)
    ids = [getattr(m, "tool_call_id", None) for m in out if m.type == "tool"]
    assert ids == ["a", "b"] and len(out) == 6


def test_payload_level_sanitize_dict_messages():
    # 最终 payload 层(dict 形态)消毒——摘要在中间件内层切断时唯一兜底位置
    from main.ist_core.agents._llm import _sanitize_dangling_tool_calls
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "ask_user", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "fs_read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
        {"role": "user", "content": "next"},
    ]
    fixed = _sanitize_dangling_tool_calls(msgs)
    assert fixed == 1
    assert msgs[3] == {"role": "tool", "tool_call_id": "c2",
                       "content": "[该工具调用被会话历史截断,没有产生结果;如果它仍然必要,重新发起。]"}
    assert msgs[4]["role"] == "user"
    assert _sanitize_dangling_tool_calls(msgs) == 0   # 幂等
