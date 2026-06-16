"""fork 子 agent 可观测性：execute_fork_skill 应把内部工具调用分布/轮数/耗时
落到 fork_trace.log，用于诊断「draft/grade 慢在哪一步」（fork 内部 LLM 往返不进主 stream）。"""

from __future__ import annotations

import importlib

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def test_summarize_fork_messages_counts_rounds_and_tools():
    from main.ist_core.skills.loader import _summarize_fork_messages

    msgs = [
        HumanMessage(content="task"),
        AIMessage(content="", tool_calls=[
            {"name": "qa_lookup_pattern", "args": {}, "id": "1"},
            {"name": "qa_deepagent_grep", "args": {}, "id": "2"},
        ]),
        ToolMessage(content="r1", tool_call_id="1"),
        ToolMessage(content="r2", tool_call_id="2"),
        AIMessage(content="", tool_calls=[{"name": "qa_deepagent_grep", "args": {}, "id": "3"}]),
        ToolMessage(content="r3", tool_call_id="3"),
        AIMessage(content="done"),
    ]
    s = _summarize_fork_messages(msgs)
    assert s["ai_rounds"] == 3
    assert s["tool_results"] == 3
    # 慢在哪一步可见：grep 调了 2 次，lookup 1 次
    assert s["tool_calls"] == {"qa_deepagent_grep": 2, "qa_lookup_pattern": 1}


def test_trace_fork_writes_line(tmp_path, monkeypatch):
    monkeypatch.setenv("IST_FORK_TRACE_LOG", str(tmp_path / "fork_trace.log"))
    import main.ist_core.skills.loader as L
    importlib.reload(L)
    L._trace_fork(
        "ist_compile_draft",
        "Case X: 配置 zone forward\n第二行被截断",
        42.5,
        {"ai_rounds": 12, "tool_results": 11, "tool_calls": {"qa_deepagent_grep": 8, "qa_lookup_pattern": 2}},
    )
    content = (tmp_path / "fork_trace.log").read_text(encoding="utf-8")
    assert "fork=ist_compile_draft" in content
    assert "elapsed=42.5s" in content
    assert "ai_rounds=12" in content
    assert "qa_deepagent_grep=8" in content
    # brief 只记首行、不泄露完整内容
    assert "第二行被截断" not in content


def test_trace_fork_never_raises(tmp_path, monkeypatch):
    """可观测性绝不能影响主流程：写入失败也静默。"""
    # 用一个已存在的文件当作目录前缀 → mkdir(parents=True) 会失败 → 须被静默吞掉
    blocker = tmp_path / "iam_a_file"
    blocker.write_text("x")
    monkeypatch.setenv("IST_FORK_TRACE_LOG", str(blocker / "sub" / "trace.log"))
    import main.ist_core.skills.loader as L
    importlib.reload(L)
    # 不抛异常即通过
    L._trace_fork("ist_compile_grade", "brief", 1.0, {"ai_rounds": 1, "tool_results": 0, "tool_calls": {}})
