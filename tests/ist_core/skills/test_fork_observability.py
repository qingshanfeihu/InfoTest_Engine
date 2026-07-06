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
            {"name": "compile_precedent", "args": {}, "id": "1"},
            {"name": "fs_grep", "args": {}, "id": "2"},
        ]),
        ToolMessage(content="r1", tool_call_id="1"),
        ToolMessage(content="r2", tool_call_id="2"),
        AIMessage(content="", tool_calls=[{"name": "fs_grep", "args": {}, "id": "3"}]),
        ToolMessage(content="r3", tool_call_id="3"),
        AIMessage(content="done"),
    ]
    s = _summarize_fork_messages(msgs)
    assert s["ai_rounds"] == 3
    assert s["tool_results"] == 3
    # 慢在哪一步可见：grep 调了 2 次，lookup 1 次
    assert s["tool_calls"] == {"fs_grep": 2, "compile_precedent": 1}


def test_trace_fork_writes_line(tmp_path, monkeypatch):
    monkeypatch.setenv("IST_FORK_TRACE_LOG", str(tmp_path / "fork_trace.log"))
    import main.ist_core.skills.loader as L
    importlib.reload(L)
    L._trace_fork(
        "ist-compile-draft",
        "Case X: 配置 zone forward\n第二行被截断",
        42.5,
        {"ai_rounds": 12, "tool_results": 11, "tool_calls": {"fs_grep": 8, "compile_precedent": 2}},
    )
    content = (tmp_path / "fork_trace.log").read_text(encoding="utf-8")
    assert "fork=ist-compile-draft" in content
    assert "elapsed=42.5s" in content
    assert "ai_rounds=12" in content
    assert "fs_grep=8" in content
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
    L._trace_fork("ist-compile-grade", "brief", 1.0, {"ai_rounds": 1, "tool_results": 0, "tool_calls": {}})


def test_execute_fork_skill_populates_summary_sink(monkeypatch):
    """execute_fork_skill 经 summary_sink 把 fork 的工具调用/轮数回传给调用方
    （compile_pipeline 据此聚合 LLM/查找成本，验证预检索是否真减少调用）。
    mock 掉真实 subagent 构建 + LLM 流式调用，不需 LLM/设备。"""
    import main.ist_core.skills.loader as L

    monkeypatch.setattr(L, "get_subagent_runnable", lambda name: object())
    canned = {"messages": [
        HumanMessage(content="task"),
        AIMessage(content="", tool_calls=[
            {"name": "dev_probe", "args": {"command": "show x"}, "id": "1"},
            {"name": "kb_footprint", "args": {"command": "sdns"}, "id": "2"},
        ]),
        ToolMessage(content="r1", tool_call_id="1"),
        ToolMessage(content="r2", tool_call_id="2"),
        AIMessage(content="最终草稿路径 workspace/outputs/x/case.xlsx"),
    ]}
    monkeypatch.setattr(L, "_invoke_fork_streamed", lambda *a, **k: canned)

    sink: dict = {}
    out = L.execute_fork_skill("ist-compile-draft", "some brief", summary_sink=sink)
    assert "case.xlsx" in out
    assert sink.get("ai_rounds") == 2                      # 2 个 AIMessage
    assert sink.get("tool_calls") == {"dev_probe": 1, "kb_footprint": 1}


def test_execute_fork_skill_summary_sink_cleared_on_error(monkeypatch):
    """fork 异常 → summary_sink 被清空，不把上一次的统计串味给调用方。"""
    import main.ist_core.skills.loader as L

    monkeypatch.setattr(L, "get_subagent_runnable", lambda name: object())

    def _boom(*a, **k):
        raise RuntimeError("fork blew up")

    monkeypatch.setattr(L, "_invoke_fork_streamed", _boom)
    sink: dict = {"stale": "data"}
    out = L.execute_fork_skill("ist-compile-draft", "brief", summary_sink=sink)
    assert out.startswith("ERROR:")
    assert sink == {}                                      # 清空防污染


def test_execute_fork_skill_marks_recursion_limit(monkeypatch):
    """Fix E：GraphRecursionError → 返回串带确定性 [recursion-limit] 标记，
    让 compile_pipeline 据此立即 escalate（不做 3 轮等价重做）。"""
    import main.ist_core.skills.loader as L

    monkeypatch.setattr(L, "get_subagent_runnable", lambda name: object())

    class GraphRecursionError(Exception):   # 按类名匹配（loader 用 __class__.__name__）
        pass

    def _recurse(*a, **k):
        raise GraphRecursionError("Recursion limit of 200 reached")

    monkeypatch.setattr(L, "_invoke_fork_streamed", _recurse)
    traced: dict = {}
    monkeypatch.setattr(L, "_trace_fork",
                        lambda skill, brief, el, summ, error="": traced.update({"error": error}))
    out = L.execute_fork_skill("ist-compile-draft", "brief")
    assert out.startswith("ERROR:")
    assert "[recursion-limit]" in out                      # 上层据此分流
    assert "[recursion-limit]" in traced.get("error", "")   # trace 也带标记
