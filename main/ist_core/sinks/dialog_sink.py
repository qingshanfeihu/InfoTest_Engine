"""DialogueCollector：对话轮次采集器，run_end 时入队，后台守护线程批量写入 sys_dialog_chat。

架构（Redis 模式）：
    DialogueCollector._flush()
        └── DialogQueue.enqueue(): redis LPUSH ~0.5ms
                │
                ▼
            Redis List (ist:dialog:queue)
                │
                ▼ (守护线程，攒批 10 条 或 2s 超时)
            batch INSERT → ist_audit.sys_dialog_chat

架构（降级模式，无 Redis）：
    DialogueCollector._flush()
        └── DialogQueue.enqueue(): deque.append() <0.1ms
                │
                ▼
            collections.deque（进程内，maxlen=10000）
                │
                ▼ (守护线程，每 2s 或攒满 10 条)
            batch INSERT → ist_audit.sys_dialog_chat

设计要点：
- _flush() 零阻塞：只做序列化 + 入队，不创建 asyncio task
- 后台单线程消费者：定时 flush（2s）+ 满批 flush（10 条）
- 批量 INSERT：executemany，单次 flush 一次 PG round-trip
- 优雅关闭：atexit 注册 flush，进程退出前清空队列
- 降级兜底：Redis 不可用时自动切换 deque；PG 不可用时静默丢弃
- 独立队列：ist:dialog:queue，与 PgAuditSink 的 ist:audit:queue 隔离

双层存储职责严格拆分：
- Checkpoint：仅服务 Agent 推理、断点续跑、运行时上下文
- sys_dialog_chat：仅服务前端展示、审计、统计、导出，不作为推理数据源
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from main.ist_core.events import IstCoreEvent

logger = logging.getLogger(__name__)

_DIALOG_REDIS_KEY = "ist:dialog:queue"
_DIALOG_BATCH_SIZE = 10
_DIALOG_FLUSH_INTERVAL = 2.0
_DIALOG_MAX_DEQUE_LEN = 10_000
_DIALOG_MAX_RETRIES = 3
_DIALOG_RETRY_DELAY_BASE = 0.5


class DialogQueue:
    """对话队列单例：Redis/Deque 入队 + 后台守护线程批量写入 PG。

    与 PgAuditSink 使用独立队列（ist:dialog:queue vs ist:audit:queue），
    互不干扰。

    用法::

        DialogQueue.get().enqueue(row)
    """

    _instance: DialogQueue | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._redis = self._build_redis()
        self._buf: deque[str] = deque(maxlen=_DIALOG_MAX_DEQUE_LEN)
        self._buf_lock = threading.Lock()
        self._running = True
        self._consumer_thread: threading.Thread | None = None
        self._flush_event = threading.Event()

        mode = "Redis" if self._redis else "deque (降级)"
        logger.info("DialogQueue 初始化，模式: %s", mode)

        self._start_consumer()
        atexit.register(self.shutdown)

    @classmethod
    def get(cls) -> DialogQueue:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def enqueue(self, row: dict[str, Any]) -> None:
        """同步入队，耗时 <0.1ms。"""
        raw = json.dumps(row, default=str)
        if self._redis is not None:
            try:
                self._redis.lpush(_DIALOG_REDIS_KEY, raw)
                return
            except Exception:
                logger.debug("DialogQueue LPUSH 失败，降级到 deque")
                self._redis = None
        with self._buf_lock:
            self._buf.append(raw)
        if len(self._buf) >= _DIALOG_BATCH_SIZE:
            self._flush_event.set()

    def shutdown(self, timeout: float = 5.0) -> None:
        self._running = False
        self._flush_event.set()
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=timeout)
        self._drain_queue()

    def _start_consumer(self) -> None:
        self._consumer_thread = threading.Thread(
            target=self._consumer_loop,
            name="dialog-queue-consumer",
            daemon=True,
        )
        self._consumer_thread.start()

    def _consumer_loop(self) -> None:
        while self._running:
            try:
                batch = self._pop_batch()
                if batch:
                    self._batch_insert(batch)
            except Exception:
                logger.debug("DialogQueue consumer 异常", exc_info=True)
            self._flush_event.wait(timeout=_DIALOG_FLUSH_INTERVAL)
            self._flush_event.clear()

    def _pop_batch(self) -> list[dict]:
        raw_list: list[str] = []
        if self._redis is not None:
            for _ in range(_DIALOG_BATCH_SIZE):
                try:
                    result = self._redis.brpop(_DIALOG_REDIS_KEY, timeout=0.1)
                    if result is None:
                        break
                    raw = result[1] if isinstance(result, (tuple, list)) else result
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    raw_list.append(raw)
                except Exception:
                    break
        else:
            with self._buf_lock:
                while raw_list.__len__() < _DIALOG_BATCH_SIZE and self._buf:
                    raw_list.append(self._buf.popleft())
        return [json.loads(r) for r in raw_list]

    def _drain_queue(self) -> None:
        total = 0
        while True:
            batch = self._pop_batch()
            if not batch:
                break
            self._batch_insert(batch)
            total += len(batch)
        if total:
            logger.info("DialogQueue shutdown: drained %d rows", total)

    def _batch_insert(self, batch: list[dict]) -> None:
        if not batch:
            return
        sql = """
            INSERT INTO ist_audit.sys_dialog_chat (
                username, session_id, conversation_id, thread_id, run_id,
                user_input, model_name, llm_output, recorded_at
            ) VALUES (
                %(username)s, %(session_id)s, %(conversation_id)s, %(thread_id)s, %(run_id)s,
                %(user_input)s, %(model_name)s, %(llm_output)s, %(recorded_at)s
            )
        """
        for attempt in range(1, _DIALOG_MAX_RETRIES + 1):
            try:
                from main.ist_core.auth.db import get_pg_connection
                conn = get_pg_connection()
                try:
                    with conn.cursor() as cur:
                        cur.executemany(sql, batch)
                finally:
                    conn.close()
                logger.debug("DialogQueue: wrote %d rows", len(batch))
                self._increment_message_counts(batch)
                return
            except Exception as exc:
                logger.warning(
                    "DialogQueue batch INSERT 失败 (attempt %d/%d, %d rows): %s",
                    attempt, _DIALOG_MAX_RETRIES, len(batch), exc,
                )
                if attempt < _DIALOG_MAX_RETRIES:
                    time.sleep(_DIALOG_RETRY_DELAY_BASE * attempt)
        logger.error("DialogQueue batch INSERT 最终失败 (%d rows)，需后台补录", len(batch))

    def _increment_message_counts(self, batch: list[dict]) -> None:
        try:
            from main.ist_core.auth.session_manager import _get_session_mgr_safe
            mgr = _get_session_mgr_safe()
            if mgr:
                for row in batch:
                    conv_id = row.get("conversation_id", "")
                    if conv_id:
                        mgr.increment_message_count(conv_id)
        except Exception:
            pass

    @staticmethod
    def _build_redis() -> Any:
        url = os.environ.get("IST_REDIS_URL", "")
        if not url:
            return None
        try:
            import redis
            client = redis.from_url(url, decode_responses=True)
            client.ping()
            return client
        except Exception:
            logger.debug("DialogQueue: Redis 不可用，降级为 deque 模式")
            return None


class DialogueCollector:
    """对话轮次采集器。

    注册为 EventBus sink，在单次 Agent run 生命周期内采集核心对话数据。
    run_end 时将结构化行数据入队 DialogQueue，由后台守护线程批量写入 PG。

    数据采集时机（astream_events 事件节点）：
    - run_start  → 采集 user_input / thread_id / run_id
    - llm_end    → 采集 model_name / llm_output（模型最终回答）
    - run_end    → 触发入队

    用法::

        collector = DialogueCollector(
            username="alice",
            session_id="web_123_abc",
            conversation_id="conv_456_def",
        )
        bus.subscribe(collector)
    """

    def __init__(
        self,
        username: str,
        session_id: str,
        conversation_id: str,
    ) -> None:
        self._username = username
        self._session_id = session_id
        self._conversation_id = conversation_id
        self._reset_round()

    def _reset_round(self) -> None:
        self._round: dict[str, Any] = {
            "run_id": "",
            "thread_id": "",
            "user_input": "",
            "model_name": "",
            "llm_output": "",
        }

    def __call__(self, event: IstCoreEvent) -> None:
        kind = event.get("kind", "")
        payload = event.get("payload") or {}
        tags = event.get("tags") or {}

        if kind == "run_start":
            self._reset_round()
            self._round["run_id"] = event.get("run_id", "")
            self._round["thread_id"] = (
                tags.get("configurable_thread_id")
                or tags.get("thread_id")
                or ""
            )
            self._round["user_input"] = payload.get("query") or payload.get("user_input") or ""

        elif kind == "llm_end":
            name = tags.get("name", "")
            if name == "thought" or "thought" in tags.get("progress_event", ""):
                return
            self._round["llm_output"] = payload.get("content") or payload.get("output") or ""
            self._round["model_name"] = tags.get("model_name") or payload.get("model_name") or ""

        elif kind == "run_end":
            self._flush()

    def _flush(self) -> None:
        if not self._round.get("run_id"):
            return

        row = self._build_row()
        if not row["user_input"] and not row["llm_output"]:
            return

        DialogQueue.get().enqueue(row)

    def _build_row(self) -> dict[str, Any]:
        r = self._round
        return {
            "username": self._username,
            "session_id": self._session_id,
            "conversation_id": self._conversation_id,
            "thread_id": r["thread_id"],
            "run_id": r["run_id"],
            "user_input": r["user_input"],
            "model_name": r["model_name"] or None,
            "llm_output": r["llm_output"] or None,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }