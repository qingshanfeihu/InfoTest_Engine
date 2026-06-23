"""_MainAgentProgressHandler 工具回调 run_id 去重与 stack 一致性."""

from __future__ import annotations

from main.ist_core.graph import _MainAgentProgressHandler


def test_on_tool_error_skips_second_duplicate_callback() -> None:
    """嵌套传播：第二次 on_tool_error 不得再 pop（与 on_tool_end 对称）。"""
    h = _MainAgentProgressHandler()
    run_id = "run-dup-error"

    h.on_tool_start({"name": "fs_grep"}, "query", run_id=run_id)
    h.on_tool_start({"name": "fs_grep"}, "query", run_id=run_id)
    assert h._tool_name_stack == ["fs_grep"]

    h.on_tool_error(ValueError("first"), run_id=run_id)
    assert h._tool_name_stack == []

    h.on_tool_error(ValueError("duplicate"), run_id=run_id)
    assert h._tool_name_stack == []


def test_on_tool_error_after_dedup_start_only_pops_once() -> None:
    """去重掉的 on_tool_start 未 push；单次 on_tool_error 只 pop 一次。"""
    h = _MainAgentProgressHandler()
    run_id = "run-single-err"

    h.on_tool_start({"name": "fs_read"}, "path", run_id=run_id)
    h.on_tool_start({"name": "fs_read"}, "path", run_id=run_id)

    h.on_tool_error(IOError("read failed"), run_id=run_id)
    assert h._tool_name_stack == []


def test_on_tool_error_clears_task_parent_on_main_agent_fork_skill() -> None:
    h = _MainAgentProgressHandler()
    run_id = "run-fork-err"
    h.on_tool_start(
        {"name": "invoke_skill"},
        '{"skill": "review-verification"}',
        run_id=run_id,
        metadata={"lc_agent_name": "main_agent"},
    )
    assert h._current_task_tool_use_id == run_id

    h.on_tool_error(RuntimeError("fork failed"), run_id=run_id, metadata={"lc_agent_name": "main_agent"})
    assert h._current_task_tool_use_id == ""
    assert h._tool_name_stack == []
