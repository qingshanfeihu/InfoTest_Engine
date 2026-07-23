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
import time as _time
from pathlib import Path as _Path
from typing import Any, Callable

from main.ist_core.events import EventBus
from main.ist_core.resilience import is_transient_error
from main.ist_core.streaming import astream_to_bus
from main.ist_core.tui.message_model import MessageSnapshot
from main.ist_core.tui.sink import TuiSink

logger = logging.getLogger(__name__)




class GraphBridge:
    """桥接 IstApp 与 LangGraph。

    用法::

        bridge = GraphBridge(graph_factory=lambda: build_ist_core_graph(...),
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
        self._pending_resume: Any = None
        self._graph: Any = None
        
        
        self._last_final_state: dict[str, Any] = {}

    @property
    def thread_id(self) -> str:
        return self._thread_id

    # 【屏蔽切换对话功能】切换 thread_id 注释
    # def switch_thread(self, new_thread_id: str) -> None:
    #     """切换到另一个对话的 thread_id。重置 run 状态，下次用户消息触发新 graph run。"""
    #     if self.is_running:
    #         logger.warning("Bridge running; switch_thread deferred until run completes")
    #     self._thread_id = new_thread_id
    #     self._run = None
    #     self._last_final_state = {}
    #     logger.info("Bridge switched to thread_id=%s", new_thread_id)

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
            sinks: list[Callable] = [self._sink, *self._extra_sinks]
            from main.ist_core.events import reset_default_bus
            import uuid as _uuid
            run_id = _uuid.uuid4().hex[:12]
            bus = reset_default_bus(run_id=run_id)
            for sink in sinks:
                bus.subscribe(sink)
            import os as _os
            _session_user = _os.environ.get("IST_SSH_USER", "").strip()
            _session_id = _os.environ.get("IST_AUTH_SESSION_ID", "").strip()
            _conversation_id = _os.environ.get("IST_CONVERSATION_ID", "").strip()
            # 注入完整认证上下文到 LangGraph config（Langfuse / qa_node 消费）
            _configurable: dict[str, Any] = {"thread_id": self._thread_id}
            if _session_user:
                _configurable["auth_user"] = _session_user
            if _session_id:
                _configurable["auth_session_id"] = _session_id
            if _conversation_id:
                _configurable["auth_conversation_id"] = _conversation_id
            _configurable["run_id"] = run_id
            config = {"configurable": _configurable}
            if _session_user or _session_id:
                bus.set_default_tags({
                    "session_user": _session_user,
                    "session_id": _session_id,
                    "conversation_id": _conversation_id,
                    "thread_id": self._thread_id,
                })

            if _session_user and _session_id and _conversation_id:
                try:
                    from main.ist_core.sinks.dialog_sink import DialogueCollector
                    dialog_collector = DialogueCollector(
                        username=_session_user,
                        session_id=_session_id,
                        conversation_id=_conversation_id,
                    )
                    bus.subscribe(dialog_collector)
                except Exception as exc:
                    logger.error("DialogueCollector 注册失败: %s", exc)
                    pass

            # TraceCollector 已禁用（2026-07-23，langfuse 替代）
            # try:
            #     from main.ist_core.sinks.trace_collector import TraceCollector
            #     bus.subscribe(TraceCollector())
            # except Exception as exc:
            #     logger.debug("TraceCollector 注册失败: %s", exc)

            coro = astream_to_bus(graph, payload, config=config, bus=bus)
            self._task = loop.create_task(coro)
            try:
                final_state = loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                self._last_final_state = {}
                
                
                self._sink.reducer.set_run_status("done")
                return
            self._last_final_state = final_state if isinstance(final_state, dict) else {}
            self._sink.reducer.set_run_status("done")
        except Exception as exc:  # noqa: BLE001
            if self._cancelled:

                self._last_final_state = {}
                self._sink.reducer.set_run_status("done")
            elif is_transient_error(exc):
                # 瞬态连接抖动（RemoteProtocolError / 限流等）重试耗尽。曾 logger.debug 完全
                # 静默——用户只见 turn 空转结束、无从知晓这轮没跑成（违背如实报告）。改为
                # 前台一行简短提示（非红色 run_error 级），系统仍可继续下一轮。
                logger.warning("GraphBridge 瞬态错误(重试耗尽): %s", exc)
                self._sink.reducer.dispatch({
                    "kind": "info",
                    "run_id": self._thread_id,
                    "seq": 0,
                    "ts": "",
                    "payload": {"info_text": f"⚠ 本轮因端点瞬态压力中止(重试已耗尽): {str(exc)[:120]}——可直接重发"},
                })
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
            from langgraph.types import Command
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
