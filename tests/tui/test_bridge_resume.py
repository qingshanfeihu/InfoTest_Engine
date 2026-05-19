"""Stage 3 GraphBridge.resume_with 协议测试。

Plan 风险 #8：HIL 续跑必须用 ``Command(resume=decision)``，不能用普通 dict；
thread_id 必须保持。这两点都是 LangGraph 1.1 协议硬约束。

不实跑 graph——用 mock graph_factory 截获 invoke / astream_to_bus 入参。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from main.qa_agent.tui.bridge import GraphBridge
from main.qa_agent.tui.sink import IstUiEvent


def _capture_post(captured: list[IstUiEvent]):
    def _post(ev: IstUiEvent) -> None:
        captured.append(ev)
    return _post


def test_bridge_thread_id_persisted_through_init():
    captured: list[IstUiEvent] = []
    bridge = GraphBridge(
        graph_factory=lambda: object(),
        post=_capture_post(captured),
        thread_id="run-abc123",
    )
    assert bridge.thread_id == "run-abc123"


def test_bridge_resume_with_uses_langgraph_command_class():
    """关键：resume_with 必须把 decision 包成 langgraph.types.Command(resume=...)。"""
    captured: list[IstUiEvent] = []
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
        # 等后台线程跑完
        if bridge._worker is not None:
            bridge._worker.join(timeout=2.0)

    # 至少一次 astream_to_bus 调用
    assert invoked_args, "astream_to_bus should have been called by resume_with"
    call = invoked_args[0]
    # state 参数应是 Command 实例（resume=decision）
    state = call["state"]
    # 用类型名而不是 isinstance 避免重复 import
    assert type(state).__name__ == "Command", f"expected Command instance, got {type(state).__name__}"
    # thread_id 必须延续
    assert call["config"]["configurable"]["thread_id"] == "run-xyz"


def test_bridge_resume_with_emits_run_done_event():
    """正常完成时应 post 一个 run_done 事件。"""
    captured: list[IstUiEvent] = []

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

    kinds = [e.kind for e in captured]
    assert "run_done" in kinds


def test_bridge_resume_with_handles_exception_as_run_error():
    captured: list[IstUiEvent] = []

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

    kinds = [e.kind for e in captured]
    assert "run_error" in kinds
    err_event = next(e for e in captured if e.kind == "run_error")
    assert "boom" in (err_event.extra or {}).get("error", "")
