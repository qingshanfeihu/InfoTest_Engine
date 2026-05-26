"""类型化事件模型（对应原计划 §16.1）。

所有运行时日志 / 进度 / 结果 / HIL 询问 / 错误 **统一经"类型化事件流"**，
CLI、未来 Web UI、LangSmith 三者订阅同一 ``EventBus``。
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
    "phase_marker",
    "evidence_added",
    "finding_emitted",
    # NOTE: subagent_start/end 事件类型已删除（Step 8）。
    # 历史死代码：grep 确认无 emit 点；task 工具走 LangChain 标准
    # tool_call/tool_result，sink.py:310-318 已通过 tool_call 派发
    # SubAgentTaskMessage。cc-haha 同样不自定义 subagent 事件类型。
    "hil_request",
    "hil_response",
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


class QaAgentEvent(TypedDict, total=False):
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
        self._sinks: list[Callable[[QaAgentEvent], None]] = []

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id

    def subscribe(self, sink: Callable[[QaAgentEvent], None]) -> None:
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
    ) -> QaAgentEvent:
        with self._lock:
            seq = next(self._seq)
        event: QaAgentEvent = {
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
                # Sink 异常不应中断主流程
                pass
        return event


# 进程级默认 Bus（多数场景用单例即可）
_DEFAULT_BUS: EventBus | None = None


def get_default_bus() -> EventBus:
    global _DEFAULT_BUS
    if _DEFAULT_BUS is None:
        _DEFAULT_BUS = EventBus()
    return _DEFAULT_BUS


def reset_default_bus(run_id: str | None = None) -> EventBus:
    """在新 run 开始前重置单例 Bus。"""
    global _DEFAULT_BUS
    _DEFAULT_BUS = EventBus(run_id=run_id)
    return _DEFAULT_BUS
