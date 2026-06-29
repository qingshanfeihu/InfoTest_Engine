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
    # 生命周期
    "run_start",
    "run_end",
    # Graph 节点
    "node_start",
    "node_end",
    # 工具调用
    "tool_call",
    "tool_start",
    "tool_result",
    "tool_end",
    # 大模型
    "llm_start",
    "llm_token",
    "llm_end",
    # 进度/标记
    "todo_list",
    "phase_marker",
    "evidence_added",
    "finding_emitted",
    # HIL
    "hil_request",
    "hil_response",
    "ask_user_request",
    # 输出
    "finding_written",
    # 错误/信息
    "run_error",
    "error",
    "warn",
    "info",
    # ── Phase 3 审计扩展 ──
    # 认证
    "auth_login",
    "auth_login_failed",
    "auth_logout",
    "auth_token_expired",
    # 会话
    "session_start",
    "session_end",
    # 大模型扩展
    "llm_thinking",
    # 文件操作
    "file_read",
    "file_write",
    "file_edit",
    # 代码执行
    "code_exec",
    "shell_exec",
    # Skill 生命周期
    "skill_invoke",
    "skill_fork_start",
    "skill_fork_end",
    # 安全
    "access_denied",
    "config_change",
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

# 审计 sink 跳过的高频低价值事件
AUDIT_SKIP_EVENTS = frozenset({
    "llm_token",
    "llm_thinking",
    "todo_list",
})

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
        self._default_tags: dict[str, Any] = {}

    def set_default_tags(self, tags: dict[str, Any]) -> None:
        """设置默认标签，会自动合并到每个 emit 的事件中。"""
        self._default_tags.update(tags)

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
        merged_tags = {**self._default_tags, **(tags or {})}
        event: IstCoreEvent = {
            "run_id": self._run_id,
            "parent_run_id": parent_run_id,
            "seq": seq,
            "ts": _now(),
            "kind": kind,
            "payload": payload or {},
            "tags": merged_tags,
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
