"""checkpoint_repo：封装 LangGraph BaseCheckpointSaver 的 list/get_tuple。

Plan 风险 #4：Postgres DSN 未配时 sidebar 报错——三级降级
（Postgres → SQLite → MemorySaver），任何环节失败 try/except 包成 "无历史"提示。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional


logger = logging.getLogger(__name__)


def _saver_uses_async_api(saver: Any) -> bool:
    return callable(getattr(saver, "alist", None))


def _run_sync(coro_factory):
    """在无 running loop 的 UI 线程里跑 async checkpoint 读操作。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    raise RuntimeError("CheckpointRepo 无法在运行中的 event loop 内同步读 checkpoint")


def _saver_list_checkpoints(saver: Any, *, limit: int) -> list[Any]:
    if _saver_uses_async_api(saver):
        async def _collect() -> list[Any]:
            out: list[Any] = []
            try:
                async_iter = saver.alist(None, limit=limit)
            except TypeError:
                async_iter = saver.alist({}, limit=limit)
            async for item in async_iter:
                out.append(item)
            return out

        return _run_sync(_collect)
    try:
        return list(saver.list(None, limit=limit))
    except TypeError:
        return list(saver.list({}, limit=limit))


def _saver_get_tuple(saver: Any, config: dict[str, Any]) -> Any:
    if _saver_uses_async_api(saver):
        async def _get() -> Any:
            return await saver.aget_tuple(config)

        return _run_sync(_get)
    return saver.get_tuple(config)


@dataclass
class ThreadEntry:
    """sidebar 列表显示的 thread 摘要。"""

    thread_id: str
    last_step: int
    preview: str
    timestamp: str


class CheckpointRepo:
    """对 langgraph BaseCheckpointSaver 的薄包装。

    - ``list_threads(limit)`` → 按 thread_id 去重返回最新 checkpoint 摘要
    - ``get_thread(tid)`` → 返回最终 state（用于 ``--resume`` 回灌 message log）

    构造时不传 saver → 使用 graph.py:_make_checkpointer 同款工厂
    （按 env IST_POSTGRES_CHECKPOINT_DSN / IST_SQLITE_PATH 自动选）。
    """

    def __init__(self, saver: Any | None = None) -> None:
        self._saver = saver if saver is not None else self._build_default()

    @staticmethod
    def _build_default() -> Any:
        """从 graph.py 复用工厂——保持降级行为一致。"""
        try:
            from main.ist_core.graph import _make_checkpointer  # type: ignore[attr-defined]
            return _make_checkpointer()
        except Exception as exc:  # noqa: BLE001
            logger.warning("CheckpointRepo: _make_checkpointer 失败，退回 MemorySaver: %s", exc)
            try:
                from langgraph.checkpoint.memory import InMemorySaver
                return InMemorySaver()
            except Exception:
                return None

    @property
    def is_persistent(self) -> bool:
        """SQLite/Postgres → True；MemorySaver / None → False。"""
        if self._saver is None:
            return False
        cls = type(self._saver).__name__
        return "Memory" not in cls

    

    def list_threads(self, *, limit: int = 50) -> list[ThreadEntry]:
        """按 thread_id 去重，返回最新 checkpoint 摘要。

        失败一律返回空列表（plan 风险 #4：sidebar 失败显示"无历史"）。
        """
        if self._saver is None:
            return []
        try:
            tuples = _saver_list_checkpoints(self._saver, limit=limit * 4)
        except Exception as exc:  # noqa: BLE001
            logger.debug("CheckpointRepo.list_threads 失败: %s", exc)
            return []

        seen: set[str] = set()
        out: list[ThreadEntry] = []
        for t in tuples:
            tid = self._extract_thread_id(t)
            if not tid or tid in seen:
                continue
            seen.add(tid)
            out.append(self._tuple_to_entry(t, tid))
            if len(out) >= limit:
                break
        return out

    def get_thread(self, thread_id: str) -> Optional[dict[str, Any]]:
        """返回 thread 最新 state dict。失败返回 None。"""
        if not thread_id or self._saver is None:
            return None
        config = {"configurable": {"thread_id": thread_id}}
        try:
            tup = _saver_get_tuple(self._saver, config)
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_tuple 失败 tid=%s: %s", thread_id, exc)
            return None
        if tup is None:
            return None
        
        try:
            checkpoint = getattr(tup, "checkpoint", None) or {}
            return dict(checkpoint.get("channel_values") or {})
        except Exception:
            return None

    def most_recent_thread_id(self) -> Optional[str]:
        threads = self.list_threads(limit=1)
        return threads[0].thread_id if threads else None

    

    @staticmethod
    def _extract_thread_id(t: Any) -> str:
        """从 CheckpointTuple 取 thread_id。"""
        config = getattr(t, "config", None) or {}
        configurable = (config.get("configurable") if isinstance(config, dict) else None) or {}
        return str(configurable.get("thread_id") or "")

    @staticmethod
    def _tuple_to_entry(t: Any, tid: str) -> ThreadEntry:
        metadata = getattr(t, "metadata", None) or {}
        if isinstance(metadata, dict):
            step = int(metadata.get("step") or metadata.get("checkpoint_id_step") or 0)
            writes = metadata.get("writes") or {}
            preview = CheckpointRepo._extract_preview(writes)
        else:
            step = 0
            preview = ""
        
        ts = ""
        try:
            ts = str((getattr(t, "checkpoint", {}) or {}).get("ts") or "")
        except Exception:
            ts = ""
        return ThreadEntry(thread_id=tid, last_step=step, preview=preview, timestamp=ts)

    @staticmethod
    def _extract_preview(writes: Any) -> str:
        """从 writes dict 找第一条用户输入或 LLM 文本，截断 60 字符。"""
        if not isinstance(writes, dict):
            return ""
        for source_node, payload in writes.items():
            if isinstance(payload, dict):
                
                for key in ("user_input", "final_answer", "answer"):
                    val = payload.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()[:60]
        return ""
