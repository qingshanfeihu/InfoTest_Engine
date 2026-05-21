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

    def _build_reminder(self, messages: list = None, *, thread_id: str = "", query: str = "", request: Any = None) -> HumanMessage | None:
        sections: list[str] = []

        if not query:
            query = self._query_extractor(messages or [])

        # L1 工作记忆
        if thread_id:
            try:
                working = self._store.read_working(thread_id, max_lines=40)
                if working:
                    sections.append(f"## Working Notes\n{working}")
            except Exception as exc:
                logger.debug("read_working 失败: %s", exc)

        # key_resolvers 直接读指定路径
        if self._key_resolvers and messages:
            try:
                keys = self._key_resolvers(messages)
                for _ns, key in keys[:self._max_items]:
                    content = self._store.read_long_term_by_path(key)
                    if content:
                        snippet = content if len(content) <= 800 else content[:797] + "..."
                        sections.append(f"## {key}\n{snippet}")
            except Exception as exc:
                logger.debug("key_resolvers 读取失败: %s", exc)

        # L2 按 query 关键词检索 long-term
        remaining = self._max_items - len(sections)
        if remaining > 0 and query:
            try:
                hits = self._store.read_long_term(query, top_k=remaining)
                if hits:
                    lt_parts = []
                    for path, content in hits:
                        snippet = content if len(content) <= 800 else content[:797] + "..."
                        lt_parts.append(f"### {path}\n{snippet}")
                    sections.append("## Relevant Long-Term Notes\n" + "\n\n".join(lt_parts))
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
            query = self._query_extractor(request.messages)
            thread_id = ""
            try:
                state = getattr(request, "state", None)
                runtime = getattr(request, "runtime", None)
                if state and runtime:
                    thread_id = self._get_thread_id(state, runtime)
            except Exception:
                pass
            reminder = self._build_reminder(
                request.messages, thread_id=thread_id, query=query, request=request
            )
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

    @staticmethod
    def _get_thread_id(state: Any, runtime: Any) -> str:
        return MemoryWriteMiddleware._get_thread_id(state, runtime)

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


_DISTILL_KEYWORDS = {"以后", "下次", "记住", "不要再", "每次都", "总是"}


class MemoryWriteMiddleware(AgentMiddleware):
    """每轮 after_model 抽取 L1 工作记忆 + 定期触发 distill fork agent。

    同时保留 finalizer 回调路径（评审场景蒸馏结论写入 long_term）。

    Args:
        store: MemoryStore facade 或任何实现 append_working 的对象
        finalizer: 检测任务结束 + 蒸馏内容的回调
        extractor_agent: fork extractor agent 实例（None 时跳过 distill）
        distill_every_n: 每 N 轮触发一次 distill（关键词命中时立即触发）
    """

    def __init__(
        self,
        store: Any,
        finalizer: Finalizer | None = None,
        *,
        extractor_agent: Any = None,
        distill_every_n: int | None = None,
    ) -> None:
        self._store = store
        self._finalizer = finalizer
        self._extractor_agent = extractor_agent
        self._distill_every_n = distill_every_n or int(
            os.environ.get("QA_AGENT_MEMORY_DISTILL_EVERY_N", "10")
        )
        self._finalized: set[str] = set()
        self._seen_threads: set[str] = set()
        self._turn_counts: dict[str, int] = {}

    def _should_distill(self, messages: list, turn_count: int) -> bool:
        """判断是否应触发 distill：关键词命中或达到轮次阈值。"""
        if turn_count >= self._distill_every_n:
            return True
        for m in reversed(messages[-3:] if len(messages) > 3 else messages):
            if isinstance(m, HumanMessage):
                text = m.content if isinstance(m.content, str) else str(m.content)
                if any(kw in text for kw in _DISTILL_KEYWORDS):
                    return True
        return False

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        try:
            messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
            if not messages:
                return None

            thread_id = self._get_thread_id(state, runtime)

            # L1 规则抽取 → append_working
            try:
                from main.qa_agent.memory.extractor import extract_working_entry
                entry = extract_working_entry(messages)
                if entry:
                    self._store.append_working(thread_id, entry)
            except Exception as exc:
                logger.debug("L1 working write: %s", exc)

            # session counter（每个 thread 首轮 +1）
            if thread_id not in self._seen_threads:
                self._seen_threads.add(thread_id)
                self._increment_session_counter()

            # distill 触发
            tc = self._turn_counts.get(thread_id, 0) + 1
            self._turn_counts[thread_id] = tc
            if self._should_distill(messages, tc):
                self._turn_counts[thread_id] = 0
                self._kick_distill_async(thread_id, messages)

            # finalizer 路径（评审专用）
            if self._finalizer is None:
                return None
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

    def _kick_distill_async(self, thread_id: str, messages: list) -> None:
        """后台触发 fork extractor agent 蒸馏 L1 → L2。"""
        if self._extractor_agent is None:
            return
        if os.environ.get("QA_AGENT_MEMORY_DISABLE_LLM", "").strip() == "1":
            return
        try:
            from main.qa_agent.memory.extractor_agent import run_extractor_async
            run_extractor_async(self._store, thread_id, messages)
        except Exception as exc:
            logger.debug("distill trigger: %s", exc)

    def _increment_session_counter(self) -> None:
        """dream 闸门 session 计数 +1。"""
        try:
            current = read_session_counter()
            path = _session_counter_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(current + 1), encoding="utf-8")
        except Exception as exc:
            logger.debug("session counter increment: %s", exc)

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


def _extract_thread_id(state: Any, runtime: Any) -> str:
    """模块级 thread_id 提取（供测试 + 外部调用）。"""
    return MemoryWriteMiddleware._get_thread_id(state, runtime)


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
    "_extract_thread_id",
    "read_session_counter",
    "reset_session_counter",
]
