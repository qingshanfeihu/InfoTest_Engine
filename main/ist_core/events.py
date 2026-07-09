"""类型化事件模型（对应原计划 §16.1）。

所有运行时日志 / 进度 / 结果 / HIL 询问 / 错误 **统一经"类型化事件流"**，
CLI、未来 Web UI、Langfuse 三者订阅同一 ``EventBus``。
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Literal, TypedDict

EventKind = Literal[
    "run_start",
    "run_end",
    "node_start",
    "node_end",
    "tool_call",
    "tool_start",
    "tool_result",
    "tool_end",
    "llm_start",
    "llm_token",
    "llm_end",
    "todo_list",
    "phase_marker",
    "evidence_added",
    "fork_cards",
    "finding_emitted",
    
    
    
    
    "hil_request",
    "hil_response",
    "ask_user_request",
    "finding_written",
    "run_error",
    "error",
    "warn",
    "info",
]

REVIEWER_PROGRESS_EVENTS = {
    "run_start",
    "tool_start",
    "tool_end",
    "phase_marker",
    "evidence_added",
    "finding_emitted",
    "run_end",
    "run_error",
}

class IstCoreEvent(TypedDict, total=False):
    run_id: str
    parent_run_id: str | None
    seq: int
    ts: str
    kind: EventKind
    payload: dict[str, Any]
    tags: dict[str, Any]
    usage: dict[str, Any] | None
    elapsed_ms: int | None

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

class EventBus:
    """进程内同步 EventBus（扇出到注册的 sink 回调）。

    设计取舍：
    - 不引入 asyncio.Queue，因为 CLI sink + JSONL sink 都可同步处理（< 1ms）
    - 若未来需要异步 Sink（WebSocket 推送），可派生 ``AsyncEventBus`` 包装本类
    """

    def __init__(self, run_id: str | None = None) -> None:
        self._run_id = run_id or ""
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._sinks: list[Callable[[IstCoreEvent], None]] = []

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id

    def subscribe(self, sink: Callable[[IstCoreEvent], None]) -> None:
        self._sinks.append(sink)

    def emit(
        self,
        kind: EventKind,
        *,
        payload: dict[str, Any] | None = None,
        tags: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        elapsed_ms: int | None = None,
        parent_run_id: str | None = None,
    ) -> IstCoreEvent:
        with self._lock:
            seq = next(self._seq)
        event: IstCoreEvent = {
            "run_id": self._run_id,
            "parent_run_id": parent_run_id,
            "seq": seq,
            "ts": _now(),
            "kind": kind,
            "payload": payload or {},
            "tags": tags or {},
            "usage": usage,
            "elapsed_ms": elapsed_ms,
        }
        for sink in self._sinks:
            try:
                sink(event)
            except Exception:  # noqa: BLE001
                
                pass
        return event


_DEFAULT_BUS: EventBus | None = None
_DEFAULT_BUS_LOCK = threading.Lock()

def get_default_bus() -> EventBus:
    global _DEFAULT_BUS
    if _DEFAULT_BUS is None:
        with _DEFAULT_BUS_LOCK:
            if _DEFAULT_BUS is None:
                _DEFAULT_BUS = EventBus()
    return _DEFAULT_BUS

def reset_default_bus(run_id: str | None = None) -> EventBus:
    """在新 run 开始前重置单例 Bus。"""
    global _DEFAULT_BUS
    with _DEFAULT_BUS_LOCK:
        _DEFAULT_BUS = EventBus(run_id=run_id)
        return _DEFAULT_BUS
