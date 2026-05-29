"""规则抽取（hot path）。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from main.ist_core.memory.extractor import extract_working_entry, format_extraction_input





def test_extract_form_2_text_after_tool():
    msgs = [
        HumanMessage(content="评审 21100"),
        AIMessage(
            content="先 grep",
            tool_calls=[{"id": "tc1", "name": "qa_grep", "args": {"q": "cookie"}}],
        ),
        ToolMessage(content="cookie__1.md:33", name="qa_grep", tool_call_id="tc1"),
        AIMessage(content="找到 SameSite", tool_calls=[]),
    ]
    entry = extract_working_entry(msgs)
    assert "thought: 找到 SameSite" in entry
    assert "tool: qa_grep" in entry
    assert "cookie__1.md:33" in entry


def test_extract_form_1_pending_tool_call_only():
    msgs = [
        HumanMessage(content="查 chi"),
        AIMessage(
            content="grep 一下",
            tool_calls=[{"id": "tc2", "name": "qa_grep", "args": {"q": "chi"}}],
        ),
    ]
    entry = extract_working_entry(msgs)
    assert "pending tool_call: qa_grep" in entry


def test_extract_returns_empty_for_empty_messages():
    assert extract_working_entry([]) == ""


def test_extract_returns_empty_when_no_ai_message():
    msgs = [HumanMessage(content="hi")]
    assert extract_working_entry(msgs) == ""


def test_extract_truncates_long_thought():
    long_text = "x" * 1000
    msgs = [
        AIMessage(content=long_text, tool_calls=[]),
    ]
    entry = extract_working_entry(msgs)
    
    assert "..." in entry
    assert len(entry) < len(long_text) + 200


def test_extract_truncates_long_tool_output():
    long_out = "y" * 5000
    msgs = [
        AIMessage(
            content="",
            tool_calls=[{"id": "tc1", "name": "qa_grep", "args": {}}],
        ),
        ToolMessage(content=long_out, name="qa_grep", tool_call_id="tc1"),
        AIMessage(content="done"),
    ]
    entry = extract_working_entry(msgs)
    assert "..." in entry





def test_format_extraction_input_skips_reminder_messages():
    msgs = [
        HumanMessage(content="<system-reminder>skill listing</system-reminder>"),
        HumanMessage(content="<memory-context>L2 hits</memory-context>"),
        HumanMessage(content="real user input"),
        AIMessage(content="reply"),
    ]
    out = format_extraction_input(msgs)
    assert "real user input" in out
    assert "skill listing" not in out
    assert "L2 hits" not in out


def test_format_extraction_input_handles_empty():
    assert "no recent" in format_extraction_input([])
