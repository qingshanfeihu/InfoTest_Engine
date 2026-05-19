"""TUI ↔ LangGraph 桥接：在后台线程跑 ``stream_and_collect``，UI 线程只消费事件。

设计要点：
- ``stream_and_collect`` 是同步 API（内部包了 asyncio.run），所以直接放后台线程
- TuiSink 在该后台线程被回调，必须用 ``post`` 回调跨线程投递到 UI
- HIL 续跑：UI 收到 hil_request 后让用户决策，把 decision 通过
  ``resume_with(decision)`` 传回，bridge 用 ``Command(resume=decision)`` 续跑
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from main.qa_agent.events import EventBus
from main.qa_agent.streaming import stream_and_collect
from main.qa_agent.tui.sink import IstUiEvent, TuiSink

logger = logging.getLogger(__name__)


class GraphBridge:
    """桥接 IstApp 与 LangGraph。

    用法::

        bridge = GraphBridge(graph_factory=lambda: build_qa_agent_graph(...),
                             post=app.dispatch_ui_event,
                             thread_id="run-xxx")
        bridge.start({"messages": [...]})
        # ... user interactions ...
        bridge.resume_with({"approved": True})  # HIL 决策
    """

    def __init__(
        self,
        *,
        graph_factory: Callable[[], Any],
        post: Callable[[IstUiEvent], None],
        thread_id: str,
        extra_sinks: list[Callable] | None = None,
    ) -> None:
        self._graph_factory = graph_factory
        self._post = post
        self._thread_id = thread_id
        self._extra_sinks = list(extra_sinks or [])
        self._sink = TuiSink(post=post)
        self._worker: threading.Thread | None = None
        self._pending_resume: Any = None  # 存放 HIL 决策，由 resume_with 写入

    @property
    def thread_id(self) -> str:
        return self._thread_id

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def start(self, initial_state: dict[str, Any]) -> None:
        """启动后台 worker 跑 graph。同一 bridge 实例不重入——is_running 检查。"""
        if self.is_running:
            logger.warning("GraphBridge already running; ignored start()")
            return
        self._sink.reset()
        self._worker = threading.Thread(
            target=self._run_in_thread,
            args=(initial_state,),
            name=f"ist-bridge-{self._thread_id}",
            daemon=True,
        )
        self._worker.start()

    def _run_in_thread(self, initial_state: dict[str, Any]) -> None:
        try:
            graph = self._graph_factory()
            config = {"configurable": {"thread_id": self._thread_id}}
            sinks: list[Callable] = [self._sink, *self._extra_sinks]
            final_state = stream_and_collect(graph, initial_state, config=config, sinks=sinks)
            self._post(IstUiEvent(kind="run_done", extra={"final_state": final_state, "thread_id": self._thread_id}))
        except Exception as exc:  # noqa: BLE001
            logger.exception("GraphBridge worker crashed")
            self._post(IstUiEvent(kind="run_error", extra={"error": str(exc)}))

    def resume_with(self, decision: dict[str, Any]) -> None:
        """HIL 续跑入口。

        LangGraph 1.1 续跑协议：用 ``Command(resume=decision)`` 作为新 invoke 的输入，
        config 里的 thread_id 必须与首跑一致——checkpointer 据此恢复 state。
        """
        if self.is_running:
            logger.warning("Bridge still running; resume_with stored as pending")
            self._pending_resume = decision
            return
        try:
            from langgraph.types import Command  # langgraph>=1.1
        except ImportError:
            self._post(IstUiEvent(kind="run_error", extra={"error": "langgraph.types.Command not available"}))
            return

        graph = self._graph_factory()
        config = {"configurable": {"thread_id": self._thread_id}}
        # 续跑用 stream_and_collect 同接口，输入是 Command(resume=...)
        self._worker = threading.Thread(
            target=self._resume_in_thread,
            args=(Command(resume=decision), config),
            name=f"ist-bridge-resume-{self._thread_id}",
            daemon=True,
        )
        self._worker.start()

    def _resume_in_thread(self, command: Any, config: dict[str, Any]) -> None:
        try:
            graph = self._graph_factory()
            sinks: list[Callable] = [self._sink, *self._extra_sinks]
            final_state = stream_and_collect(graph, command, config=config, sinks=sinks)
            self._post(IstUiEvent(kind="run_done", extra={"final_state": final_state, "thread_id": self._thread_id}))
        except Exception as exc:  # noqa: BLE001
            logger.exception("GraphBridge resume worker crashed")
            self._post(IstUiEvent(kind="run_error", extra={"error": str(exc)}))
