"""TUI ↔ LangGraph 桥接：在后台线程跑 ``astream_to_bus``，UI 线程只消费事件。

设计要点：
- ``astream_to_bus`` 是 async；bridge 自己起 asyncio loop 跑在后台线程。
- 这样能拿到 task 句柄，cancel 能走 ``loop.call_soon_threadsafe(task.cancel)``——
  避免老版用 ``asyncio.run`` 时 ctrl+c 只能等 graph 自己结束（结果就是
  daemon 线程在主进程 shutdown 后还在 submit 新 future，触发
  ``cannot schedule new futures after shutdown``）。
- TuiSink 在该后台线程被回调，必须用 ``post`` 回调跨线程投递到 UI。
- HIL 续跑：UI 收到 hil_request 后让用户决策，把 decision 通过
  ``resume_with(decision)`` 传回，bridge 用 ``Command(resume=decision)`` 续跑。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from main.qa_agent.events import EventBus
from main.qa_agent.streaming import astream_to_bus
from main.qa_agent.tui.message_model import MessageSnapshot
from main.qa_agent.tui.sink import TuiSink

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

    _shared_loop: asyncio.AbstractEventLoop | None = None
    _loop_lock = threading.Lock()

    def __init__(
        self,
        *,
        graph_factory: Callable[[], Any],
        post: Callable[[MessageSnapshot], None],
        thread_id: str,
        extra_sinks: list[Callable] | None = None,
    ) -> None:
        self._graph_factory = graph_factory
        self._post = post
        self._thread_id = thread_id
        self._extra_sinks = list(extra_sinks or [])
        self._sink = TuiSink(post=post)
        self._worker: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._cancelled = False
        self._pending_resume: Any = None  # 存放 HIL 决策，由 resume_with 写入
        self._graph: Any = None
        # bridge 维护最近一次 final_state，供 IstApp 在 run_done 时读取做总结。
        # MessageSnapshot 本身不包含 LangGraph state，所以这里独立存。
        self._last_final_state: dict[str, Any] = {}

    @property
    def thread_id(self) -> str:
        return self._thread_id

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def last_final_state(self) -> dict[str, Any]:
        """最近一次 run 的 LangGraph final_state；UI 用它取 final_answer 等
        非渲染信息（如 CLI 模式总结）。"""
        return self._last_final_state

    def _get_shared_loop(self) -> asyncio.AbstractEventLoop:
        """获取或创建共享的 event loop，避免重复创建导致 Lock 绑定问题。"""
        with GraphBridge._loop_lock:
            if GraphBridge._shared_loop is None or GraphBridge._shared_loop.is_closed():
                GraphBridge._shared_loop = asyncio.new_event_loop()
        return GraphBridge._shared_loop

    def start(self, initial_state: dict[str, Any]) -> None:
        """启动后台 worker 跑 graph。同一 bridge 实例不重入——is_running 检查。"""
        if self.is_running:
            logger.warning("GraphBridge already running; ignored start()")
            return
        self._sink.reset()
        self._cancelled = False
        self._last_final_state = {}
        self._worker = threading.Thread(
            target=self._run_in_thread,
            args=(initial_state, False),
            name=f"ist-bridge-{self._thread_id}",
            daemon=True,
        )
        self._worker.start()

    def cancel(self) -> None:
        """请求取消运行中的 graph。线程安全——可在 UI 线程 / 信号处理里调。"""
        self._cancelled = True
        loop = self._loop
        task = self._task
        if loop is None or task is None or task.done():
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            # loop 已经关了——忽略
            pass

    def join(self, timeout: float | None = None) -> None:
        """等 worker 线程结束。给 app shutdown 用，避免 daemon 线程在
        interpreter 关闭后继续 submit future。"""
        worker = self._worker
        if worker is None:
            return
        worker.join(timeout=timeout)

    def _get_graph(self) -> Any:
        if self._graph is None:
            self._graph = self._graph_factory()
        return self._graph

    def _run_in_thread(self, payload: Any, is_resume: bool) -> None:
        loop = self._get_shared_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            graph = self._get_graph()
            config = {"configurable": {"thread_id": self._thread_id}}
            sinks: list[Callable] = [self._sink, *self._extra_sinks]
            from main.qa_agent.events import reset_default_bus
            import uuid as _uuid
            bus = reset_default_bus(run_id=_uuid.uuid4().hex[:12])
            for sink in sinks:
                bus.subscribe(sink)

            coro = astream_to_bus(graph, payload, config=config, bus=bus)
            self._task = loop.create_task(coro)
            try:
                final_state = loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                self._last_final_state = {}
                # 通过 reducer 切换 status —— UI 端看到 snapshot.status 变 done 后
                # 触发完成回调（仿 cc-haha：终态切换走单一渠道）
                self._sink.reducer.set_run_status("done")
                return
            self._last_final_state = final_state if isinstance(final_state, dict) else {}
            self._sink.reducer.set_run_status("done")
        except Exception as exc:  # noqa: BLE001
            if self._cancelled:
                # 取消触发的级联异常不当作错误
                self._last_final_state = {}
                self._sink.reducer.set_run_status("done")
            else:
                logger.exception("GraphBridge worker crashed")
                self._sink.reducer.dispatch({
                    "kind": "run_error",
                    "run_id": self._thread_id,
                    "seq": 0,
                    "ts": "",
                    "payload": {"error": str(exc)},
                })
        finally:
            try:
                # 清理悬挂任务，避免 "Task was destroyed but it is pending"
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                pass
            self._task = None

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
            self._sink.reducer.dispatch({
                "kind": "run_error",
                "run_id": self._thread_id,
                "seq": 0,
                "ts": "",
                "payload": {"error": "langgraph.types.Command not available"},
            })
            return

        self._cancelled = False
        self._worker = threading.Thread(
            target=self._run_in_thread,
            args=(Command(resume=decision), True),
            name=f"ist-bridge-resume-{self._thread_id}",
            daemon=True,
        )
        self._worker.start()
