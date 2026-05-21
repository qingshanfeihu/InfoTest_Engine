"""Memory injection + write middleware（通用三层架构）。

设计原则（cc-haha + deepagents 调研结论）：
1. 只记结论不记过程
2. 注入时做选择（按相关性选条目，不全量塞）
3. 写入分两路（hot path 任务结束后蒸馏 + cold path 定期合并）
4. 业务无关——middleware 接受回调（query_extractor / key_resolvers / finalizer），
   不写死任何业务路径前缀

通用层接口：
- MemoryInjectionMiddleware(store, query_extractor, key_resolvers, max_items)
- MemoryWriteMiddleware(store, finalizer)

业务适配层（如评审）通过传入不同回调实现定制。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage

from main.qa_agent.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_REMINDER_TAG = "<memory-context>"
_REMINDER_END = "</memory-context>"

# 类型别名
QueryExtractor = Callable[[list], str]
KeyResolver = Callable[[list], list[tuple[str, str]]]
Finalizer = Callable[[list, MemoryStore], dict[str, str] | None]


def _has_recent_reminder(messages: list) -> bool:
    recent = messages[-4:] if len(messages) > 4 else messages
    for msg in recent:
        content = getattr(msg, "content", "") or ""
        if isinstance(content, str) and _REMINDER_TAG in content:
            return True
    return False


def _last_user_query(messages: list) -> str:
    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            c = m.content if isinstance(m.content, str) else str(m.content)
            if _REMINDER_TAG in c or "<system-reminder>" in c:
                continue
            return c
    return ""


# ----------------------------------------------------------------------
# Injection middleware（通用回调接口）
# ----------------------------------------------------------------------


class MemoryInjectionMiddleware(AgentMiddleware):
    """每轮按回调检索相关记忆条目，注入到模型请求。

    通用接口——不写死任何业务路径前缀。业务层通过传入不同回调实现定制。

    Args:
        store: MemoryStore facade
        query_extractor: 从 messages 提取检索 query 的回调
        key_resolvers: 从 messages 返回 [(namespace, key)] 直接读取路径的回调
        max_items: 最多注入条目数（cc-haha 原则：≤5）
    """

    def __init__(
        self,
        store: MemoryStore,
        query_extractor: QueryExtractor | None = None,
        key_resolvers: KeyResolver | None = None,
        *,
        max_items: int = 5,
    ) -> None:
        self._store = store
        self._query_extractor = query_extractor or _last_user_query
        self._key_resolvers = key_resolvers
        self._max_items = max(1, int(max_items))

    def _build_reminder(self, messages: list) -> HumanMessage | None:
        sections: list[str] = []

        query = self._query_extractor(messages)

        # 1. 按 key_resolvers 直接读指定路径
        if self._key_resolvers:
            try:
                keys = self._key_resolvers(messages)
                for _ns, key in keys[:self._max_items]:
                    content = self._store.read_long_term_by_path(key)
                    if content:
                        snippet = content if len(content) <= 800 else content[:797] + "..."
                        sections.append(f"## {key}\n{snippet}")
            except Exception as exc:
                logger.debug("key_resolvers 读取失败: %s", exc)

        # 2. 按 query 关键词检索 long-term（补足到 max_items）
        remaining = self._max_items - len(sections)
        if remaining > 0 and query:
            try:
                hits = self._store.read_long_term(query, top_k=remaining)
                for path, content in hits:
                    snippet = content if len(content) <= 800 else content[:797] + "..."
                    sections.append(f"## {path}\n{snippet}")
            except Exception as exc:
                logger.debug("read_long_term 失败: %s", exc)

        if not sections:
            return None

        body = "\n\n".join(sections)
        return HumanMessage(
            content=f"{_REMINDER_TAG}\n{body}\n{_REMINDER_END}"
        )

    def _inject(self, request: ModelRequest) -> ModelRequest:
        try:
            if _has_recent_reminder(request.messages):
                return request
            reminder = self._build_reminder(request.messages)
            if reminder is None:
                return request
            new_msgs = list(request.messages)
            insert_at = len(new_msgs)
            for i in range(len(new_msgs) - 1, -1, -1):
                if isinstance(new_msgs[i], HumanMessage):
                    insert_at = i
                    break
            new_msgs.insert(insert_at, reminder)
            return request.override(messages=new_msgs)
        except Exception as exc:
            logger.debug("MemoryInjectionMiddleware 注入失败: %s", exc)
            return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._inject(request))


# ----------------------------------------------------------------------
# Write middleware（通用回调接口）
# ----------------------------------------------------------------------


class MemoryWriteMiddleware(AgentMiddleware):
    """任务结束后触发 finalizer 回调蒸馏结论写入 store。

    不再每轮 after_model 写过程日志。只在 finalizer 判定任务结束时触发一次。

    Args:
        store: MemoryStore facade
        finalizer: 检测任务结束 + 蒸馏内容的回调，返回 {path: content} 写入计划或 None
    """

    def __init__(
        self,
        store: MemoryStore,
        finalizer: Finalizer | None = None,
    ) -> None:
        self._store = store
        self._finalizer = finalizer
        self._finalized: set[str] = set()

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        if self._finalizer is None:
            return None
        try:
            messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
            if not messages:
                return None

            thread_id = self._get_thread_id(state, runtime)
            if thread_id in self._finalized:
                return None

            write_plan = self._finalizer(messages, self._store)
            if write_plan:
                self._finalized.add(thread_id)
                for path, content in write_plan.items():
                    try:
                        self._store.upsert_long_term(path, content, mode="replace")
                        logger.info("memory write: %s (%d chars)", path, len(content))
                    except Exception as exc:
                        logger.warning("memory write 失败 %s: %s", path, exc)
        except Exception as exc:
            logger.debug("MemoryWriteMiddleware after_model: %s", exc)
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

    @staticmethod
    def _get_thread_id(state: Any, runtime: Any) -> str:
        try:
            ei = getattr(runtime, "execution_info", None)
            tid = getattr(ei, "thread_id", None) if ei else None
            if tid:
                return str(tid)
        except Exception:
            pass
        try:
            if isinstance(state, dict):
                tid = state.get("thread_id")
            else:
                tid = getattr(state, "thread_id", None)
            if tid:
                return str(tid)
        except Exception:
            pass
        return "default"


# ----------------------------------------------------------------------
# Session counter for dream task gate (保留供 dream.py 使用)
# ----------------------------------------------------------------------


def read_session_counter() -> int:
    """读取 dream 闸门的 session 计数。"""
    path = _session_counter_path()
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0


def reset_session_counter() -> None:
    """重置 session 计数（dream 完成后调用）。"""
    path = _session_counter_path()
    try:
        path.write_text("0", encoding="utf-8")
    except Exception:
        pass


def _session_counter_path():
    from pathlib import Path

    from main.qa_agent.memory.backend import get_default_root

    root = get_default_root()
    dream_dir = root / ".dream"
    dream_dir.mkdir(parents=True, exist_ok=True)
    return dream_dir / "session_count"


def reset_session_counter() -> None:
    path = _session_counter_path()
    try:
        path.write_text("0", encoding="utf-8")
    except Exception as exc:
        logger.debug("reset session counter 失败: %s", exc)


__all__ = [
    "MemoryInjectionMiddleware",
    "MemoryWriteMiddleware",
    "read_session_counter",
    "reset_session_counter",
]
