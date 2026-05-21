"""Memory injection + write middleware。

参考实现：
- main/qa_agent/middleware/per_turn_skill_reminder.py（注入位置算法 + 去重 + frontmatter 复用）
- deepagents/middleware/memory.py:MemoryMiddleware（系统消息注入参考，但我们走 user-role）
- cc-haha src/services/extractMemories（fork agent 写入触发条件）

为什么不直接复用 MemoryMiddleware：
- MemoryMiddleware 是 system_message 注入 + before_agent 一次加载，对 L3 (AGENTS.md) 够用
- 但 L1 (working) / L2 (long-term) 需要每轮注入 + user-role + 关键词检索 → 必须自己写
- L3 注入由 deepagents 的 MemoryMiddleware 接管（在 main_agent 通过 memory= 参数挂上）
- 本中间件只管 L1 + L2 注入 + 工作记忆写入 + distill 触发
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage

from main.qa_agent.memory.extractor import extract_working_entry
from main.qa_agent.memory.store import MemoryStore

logger = logging.getLogger(__name__)


_DISTILL_KEYWORDS = ("记住", "下次", "以后", "remember", "preference", "preferences", "不要")
_REMINDER_TAG = "<memory-context>"
_REMINDER_END = "</memory-context>"


def _has_recent_reminder(messages: list) -> bool:
    """检查最近 4 条消息是否已注入过 memory-context（避免堆积）。

    照搬 per_turn_skill_reminder._has_recent_reminder 设计。
    """
    recent = messages[-4:] if len(messages) > 4 else messages
    for msg in recent:
        content = getattr(msg, "content", "") or ""
        if isinstance(content, str) and _REMINDER_TAG in content:
            return True
    return False


def _extract_thread_id(state: Any, runtime: Any) -> str:
    """从 runtime / state 拿 thread_id。

    优先级：
    1. runtime.execution_info.thread_id（langgraph 标准位置，runtime.py:39）
    2. state.thread_id（QaAgentState 已有字段）
    3. "default"
    """
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


def _last_user_query(messages: list) -> str:
    """从 messages 倒序找最后一条非 reminder 的 HumanMessage 文本。"""
    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            c = m.content if isinstance(m.content, str) else str(m.content)
            if _REMINDER_TAG in c:
                continue
            if "<system-reminder>" in c:
                continue
            return c
    return ""


# ----------------------------------------------------------------------
# Injection middleware (L1 + L2 → user-role reminder)
# ----------------------------------------------------------------------


class MemoryInjectionMiddleware(AgentMiddleware):
    """每轮把 L1（working）+ L2（long-term）注入到模型请求。

    L3 (AGENTS.md) 由 deepagents 内置 MemoryMiddleware 注入到 system_message，
    本中间件不重复处理。
    """

    def __init__(
        self,
        store: MemoryStore,
        *,
        l1_lines: int = 80,
        l2_top_k: int = 3,
        stale_days: int | None = None,
    ) -> None:
        self._store = store
        self._l1_lines = max(0, int(l1_lines))
        self._l2_top_k = max(0, int(l2_top_k))
        # 陈旧警告阈值（仿 cc-haha "≤1 天无警告，>1 天附陈旧警告"）。
        # 我们项目记忆迭代慢，默认 30 天才提示陈旧；env QA_AGENT_MEMORY_STALE_DAYS 可调。
        if stale_days is None:
            try:
                stale_days = int(os.environ.get("QA_AGENT_MEMORY_STALE_DAYS") or "30")
            except Exception:
                stale_days = 30
        self._stale_days = max(0, stale_days)

    def _build_reminder(
        self, *, thread_id: str, query: str, request: ModelRequest
    ) -> HumanMessage | None:
        sections: list[str] = []

        # L1：当前 thread 的 working 笔记尾部
        try:
            l1 = self._store.read_working(thread_id, max_lines=self._l1_lines)
        except Exception as exc:
            logger.debug("read_working 失败: %s", exc)
            l1 = ""
        if l1:
            sections.append(f"# Working Notes (this thread)\n{l1}")

        # L2：用 query 关键词检索 long-term
        if self._l2_top_k > 0 and query:
            try:
                hits = self._store.read_long_term(query, top_k=self._l2_top_k)
            except Exception as exc:
                logger.debug("read_long_term 失败: %s", exc)
                hits = []
            if hits:
                lines = []
                for path, content in hits:
                    # 截断每条到 800 字
                    snippet = content if len(content) <= 800 else content[:797] + "..."
                    # 仿 cc-haha：>stale_days 加 [stale: Xd ago] 标签
                    stale_tag = self._stale_tag_for(content)
                    header = f"## {path}{stale_tag}"
                    lines.append(f"{header}\n{snippet}")
                sections.append("# Relevant Long-Term Notes\n" + "\n\n".join(lines))

        if not sections:
            return None

        body = "\n\n".join(sections)
        return HumanMessage(
            content=f"{_REMINDER_TAG}\n{body}\n{_REMINDER_END}"
        )

    def _stale_tag_for(self, content: str) -> str:
        """根据 frontmatter.updated 计算陈旧标签。

        仿 cc-haha "≤1 天无警告，>1 天附陈旧警告"。我们 stale_days 默认 30。
        返回 " [stale: Xd ago]" 或 ""。
        """
        if self._stale_days <= 0:
            return ""
        try:
            from datetime import datetime, timezone
            fields, _ = self._store.parse_frontmatter(content)
            updated = (fields.get("updated") or "").strip()
            if not updated:
                return ""
            dt = datetime.fromisoformat(updated)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ago = datetime.now(timezone.utc) - dt
            days = int(ago.total_seconds() / 86400)
            if days >= self._stale_days:
                return f" [stale: {days}d ago]"
        except Exception as exc:
            logger.debug("_stale_tag_for 解析失败: %s", exc)
        return ""

    def _inject(self, request: ModelRequest) -> ModelRequest:
        try:
            thread_id = _extract_thread_id(request.state, request.runtime)
            query = _last_user_query(request.messages)
            if _has_recent_reminder(request.messages):
                return request
            reminder = self._build_reminder(
                thread_id=thread_id, query=query, request=request
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
# Write middleware (L1 hot path + L2/L3 distill trigger)
# ----------------------------------------------------------------------


class MemoryWriteMiddleware(AgentMiddleware):
    """after_model 每轮写 L1；满足触发条件时 fork agent 异步抽 L2/L3。

    Args:
        store: MemoryStore facade
        extractor_agent: build_extractor_agent 返回的 Runnable，None 时 distill 关闭
        distill_every_n: 每 N 轮触发一次 distill（默认 10）
    """

    def __init__(
        self,
        store: MemoryStore,
        extractor_agent: Any,
        *,
        distill_every_n: int = 10,
    ) -> None:
        self._store = store
        self._extractor = extractor_agent
        self._distill_every_n = max(1, int(distill_every_n))
        self._turn_counters: dict[str, int] = {}
        self._counter_lock = threading.Lock()
        self._sessions_seen: set[str] = set()

    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        try:
            messages = state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
            if not messages:
                return None
            thread_id = _extract_thread_id(state, runtime)

            # 1. 写 L1（hot path，无 LLM）
            try:
                entry = extract_working_entry(messages)
                if entry:
                    self._store.append_working(thread_id, entry)
            except Exception as exc:
                logger.debug("append_working 失败: %s", exc)

            # 2. 计数：当前 thread 的 turn 数
            with self._counter_lock:
                self._turn_counters[thread_id] = self._turn_counters.get(thread_id, 0) + 1
                count = self._turn_counters[thread_id]
                first_turn = thread_id not in self._sessions_seen
                if first_turn:
                    self._sessions_seen.add(thread_id)

            # 3. dream session counter：thread 首轮触发时 +1
            if first_turn and not _is_disabled():
                try:
                    _increment_session_counter()
                except Exception as exc:
                    logger.debug("increment session counter 失败: %s", exc)

            # 4. 触发 distill？
            should = self._should_distill(messages, count)
            if should and self._extractor is not None and not _llm_disabled():
                self._kick_distill_async(messages)
        except Exception as exc:
            logger.debug("MemoryWriteMiddleware after_model 兜底: %s", exc)
        return None

    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        # 同步实现已经够轻；异步版本直接转发
        return self.after_model(state, runtime)

    def _should_distill(self, messages: list, turn_count: int) -> bool:
        # 触发器 1：累计轮数到了
        if turn_count > 0 and turn_count % self._distill_every_n == 0:
            return True
        # 触发器 2：用户输入命中关键词
        last_user = _last_user_query(messages)
        if last_user:
            lo = last_user.lower()
            for kw in _DISTILL_KEYWORDS:
                if kw in lo:
                    return True
        return False

    def _kick_distill_async(self, messages: list) -> None:
        """启动后台线程跑 fork agent。失败静默。

        必须用 daemon thread + 拷贝 messages，避免主图状态被外部线程污染。
        """
        try:
            messages_copy = list(messages)
        except Exception:
            return

        def _run():
            try:
                from main.qa_agent.memory.extractor_agent import run_extractor

                result = run_extractor(self._extractor, messages_copy, max_turns=5)
                if result:
                    logger.info("[memory] extractor 完成: %s", result[:200])
            except Exception as exc:
                logger.debug("extractor 后台跑失败: %s", exc)

        try:
            threading.Thread(
                target=_run,
                name=f"memory-extractor-{int(time.time() * 1000)}",
                daemon=True,
            ).start()
        except Exception as exc:
            logger.debug("启动 extractor 线程失败: %s", exc)


# ----------------------------------------------------------------------
# Session counter for dream task gate (fcntl-based)
# ----------------------------------------------------------------------


def _is_disabled() -> bool:
    return (os.environ.get("QA_AGENT_MEMORY_ENABLED") or "1").strip() == "0"


def _llm_disabled() -> bool:
    return (os.environ.get("QA_AGENT_MEMORY_DISABLE_LLM") or "0").strip() == "1"


def _session_counter_path() -> Path:
    from main.qa_agent.memory.backend import get_default_root

    root = get_default_root()
    dream_dir = root / ".dream"
    dream_dir.mkdir(parents=True, exist_ok=True)
    return dream_dir / "session_count"


def _increment_session_counter() -> int:
    """+1 到 memory/.dream/session_count（fcntl 锁；Windows 兜底无锁 last-write-wins）。"""
    path = _session_counter_path()
    try:
        try:
            import fcntl
        except ImportError:
            fcntl = None  # type: ignore[assignment]

        if path.exists():
            try:
                cur = int(path.read_text(encoding="utf-8").strip() or "0")
            except Exception:
                cur = 0
        else:
            cur = 0
        new = cur + 1

        with open(path, "w", encoding="utf-8") as fh:
            if fcntl:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                except Exception:
                    pass
            fh.write(str(new))
            if fcntl:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
        return new
    except Exception as exc:
        logger.debug("session counter +1 失败: %s", exc)
        return 0


def read_session_counter() -> int:
    path = _session_counter_path()
    if not path.exists():
        return 0
    try:
        return int(path.read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0


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
