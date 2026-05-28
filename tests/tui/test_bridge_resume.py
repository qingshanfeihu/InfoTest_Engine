"""GraphBridge.resume_with 协议测试（重构后：post 收 MessageSnapshot）。

Plan 风险 #8：HIL 续跑必须用 ``Command(resume=decision)``，不能用普通 dict；
thread_id 必须保持。这两点都是 LangGraph 1.1 协议硬约束。

重构后 bridge.post 接 ``MessageSnapshot``（reducer 输出），不再是 IstUiEvent；
run_done / run_error 通过 ``reducer.set_run_status / dispatch run_error`` 触发，
最终也走 snapshot 通路。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from main.qa_agent.tui.bridge import GraphBridge
from main.qa_agent.tui.message_model import MessageSnapshot


def _capture_post(captured: list[MessageSnapshot]):
    def _post(snap: MessageSnapshot) -> None:
        captured.append(snap)
    return _post


def test_bridge_thread_id_persisted_through_init():
    captured: list[MessageSnapshot] = []
    bridge = GraphBridge(
        graph_factory=lambda: object(),
        post=_capture_post(captured),
        thread_id="run-abc123",
    )
    assert bridge.thread_id == "run-abc123"


def test_bridge_resume_with_uses_langgraph_command_class():
    """关键：resume_with 必须把 decision 包成 langgraph.types.Command(resume=...)。"""
    captured: list[MessageSnapshot] = []
    invoked_args: list[Any] = []

    async def fake_astream_to_bus(graph, state, *, config=None, bus=None):
        invoked_args.append({"state": state, "config": config})
        return {"final_answer": "ok"}

    bridge = GraphBridge(
        graph_factory=lambda: object(),
        post=_capture_post(captured),
        thread_id="run-xyz",
    )

    decision = {"approved": True}

    with patch("main.qa_agent.tui.bridge.astream_to_bus", side_effect=fake_astream_to_bus):
        bridge.resume_with(decision)
        if bridge._worker is not None:
            bridge._worker.join(timeout=2.0)

    assert invoked_args, "astream_to_bus should have been called by resume_with"
    call = invoked_args[0]
    state = call["state"]
    assert type(state).__name__ == "Command", f"expected Command instance, got {type(state).__name__}"
    assert call["config"]["configurable"]["thread_id"] == "run-xyz"


def test_bridge_resume_with_reaches_done_status():
    """正常完成时 reducer 状态应切到 done，最后一帧 snapshot.status == 'done'。"""
    captured: list[MessageSnapshot] = []

    async def fake_astream(*_args, **_kwargs):
        return {"final_answer": "resumed-ok"}

    bridge = GraphBridge(
        graph_factory=lambda: object(),
        post=_capture_post(captured),
        thread_id="run-1",
    )

    with patch("main.qa_agent.tui.bridge.astream_to_bus", side_effect=fake_astream):
        bridge.resume_with({"approved": True})
        if bridge._worker is not None:
            bridge._worker.join(timeout=2.0)

    assert captured, "post should have been called at least once"
    statuses = [s.status for s in captured]
    assert "done" in statuses, f"expected 'done' in {statuses}"
    # final_state 通过 bridge.last_final_state 暴露给 IstApp
    assert bridge.last_final_state.get("final_answer") == "resumed-ok"


def test_bridge_resume_with_handles_exception_as_error_status():
    captured: list[MessageSnapshot] = []

    async def fake_astream(*_args, **_kwargs):
        raise RuntimeError("boom")

    bridge = GraphBridge(
        graph_factory=lambda: object(),
        post=_capture_post(captured),
        thread_id="run-1",
    )

    with patch("main.qa_agent.tui.bridge.astream_to_bus", side_effect=fake_astream):
        bridge.resume_with({"approved": True})
        if bridge._worker is not None:
            bridge._worker.join(timeout=2.0)

    statuses = [s.status for s in captured]
    assert "error" in statuses, f"expected 'error' in {statuses}"
