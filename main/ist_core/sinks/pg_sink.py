"""PgAuditSink：Redis 缓存 + 后台消费者批量写 PostgreSQL（无 Redis 时降级为进程内 deque）。

架构（Redis 模式）：
    EventBus.emit()
        └── PgAuditSink.__call__(): redis LPUSH ~0.5ms
                │
                ▼
            Redis List (ist:audit:queue)
                │
                ▼ (守护线程，BRPOP 攒批 100 条 或 2s 超时)
            batch INSERT → ist_audit.audit_log

架构（降级模式，无 Redis）：
    EventBus.emit()
        └── PgAuditSink.__call__(): deque.append() <0.1ms
                │
                ▼
            collections.deque（进程内，maxlen=50000）
                │
                ▼ (守护线程，每 2s 或攒满 100 条)
            batch INSERT → ist_audit.audit_log

设计要点：
- Sink 内部零阻塞：只做入队，不拖慢 EventBus
- 后台单线程消费者：定时 flush（2s）+ 满批 flush（100 条）
- 批量 INSERT：executemany，单次 flush 一次 PG round-trip
- 事件过滤：跳过 llm_token / llm_thinking / todo_list（高频低价值）
- 优雅关闭：atexit 注册 flush，进程退出前清空队列
- 降级兜底：Redis 不可用时自动切换 deque；PG 不可用时静默丢弃
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from main.ist_core.events import AUDIT_SKIP_EVENTS, IstCoreEvent

logger = logging.getLogger(__name__)

# Redis 队列 key
_REDIS_QUEUE_KEY = "ist:audit:queue"
# 批量写入阈值
_BATCH_SIZE = 100
# flush 间隔（秒）
_FLUSH_INTERVAL = 2.0
# deque 最大长度（防 OOM）
_MAX_DEQUE_LEN = 50_000
# tool_input / tool_output 截断长度
_TOOL_INPUT_CAP = 500
_TOOL_OUTPUT_CAP = 2000
# event_summary 截断长度
_SUMMARY_CAP = 200


class PgAuditSink:
    """审计日志 sink，后台线程批量写 PG。

    Redis 可用时走 Redis 缓存队列；不可用时自动降级为进程内 deque。

    用法::

        sink = PgAuditSink()         # 自动启动后台消费者
        bus.subscribe(sink)          # 注册到 EventBus
        # ... 运行结束 ...
        sink.shutdown()              # 优雅关闭（atexit 自动调用）
    """

    def __init__(
        self,
        *,
        redis_client: Any = None,
        batch_size: int = _BATCH_SIZE,
        flush_interval: float = _FLUSH_INTERVAL,
    ) -> None:
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._redis = redis_client or self._build_redis()
        self._use_deque = self._redis is None
        self._buf: deque[str] = deque(maxlen=_MAX_DEQUE_LEN)
        self._buf_lock = threading.Lock()
        self._running = True
        self._consumer_thread: threading.Thread | None = None
        self._flush_event = threading.Event()

        mode = "Redis" if self._redis else "deque (降级)"
        logger.info("PgAuditSink 初始化，模式: %s", mode)

        self._start_consumer()
        atexit.register(self.shutdown)

    # ------------------------------------------------------------------
    # EventBus sink 接口
    # ------------------------------------------------------------------

    def __call__(self, event: IstCoreEvent) -> None:
        """同步入队，耗时 <0.1ms。"""
        kind = event.get("kind", "")
        if kind in AUDIT_SKIP_EVENTS:
            return
        raw = json.dumps(event, default=str)
        if self._redis is not None:
            try:
                self._redis.lpush(_REDIS_QUEUE_KEY, raw)
                return
            except Exception as exc:
                logger.debug("PgAuditSink LPUSH 失败，降级到 deque: %s", exc)
                self._redis = None
                self._use_deque = True
        # deque 模式
        with self._buf_lock:
            self._buf.append(raw)
        # 攒满时唤醒消费者
        if len(self._buf) >= self._batch_size:
            self._flush_event.set()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def shutdown(self, timeout: float = 5.0) -> None:
        """优雅关闭：停止消费者 + 清空队列写入 PG。"""
        self._running = False
        self._flush_event.set()
        if self._consumer_thread and self._consumer_thread.is_alive():
            self._consumer_thread.join(timeout=timeout)
        self._drain_queue()

    # ------------------------------------------------------------------
    # 后台消费者
    # ------------------------------------------------------------------

    def _start_consumer(self) -> None:
        self._consumer_thread = threading.Thread(
            target=self._consumer_loop,
            name="pg-audit-consumer",
            daemon=True,
        )
        self._consumer_thread.start()

    def _consumer_loop(self) -> None:
        """守护线程：攒批 → batch INSERT。"""
        while self._running:
            try:
                batch = self._pop_batch()
                if batch:
                    self._batch_insert(batch)
            except Exception as exc:
                logger.debug("PgAuditSink consumer 异常: %s", exc)
            self._flush_event.wait(timeout=self._flush_interval)
            self._flush_event.clear()

    def _pop_batch(self) -> list[dict]:
        """弹出最多 batch_size 条事件（Redis 或 deque）。"""
        raw_list: list[str] = []
        if self._redis is not None:
            # Redis 模式
            for _ in range(self._batch_size):
                try:
                    result = self._redis.brpop(_REDIS_QUEUE_KEY, timeout=0.1)
                    if result is None:
                        break
                    raw = result[1] if isinstance(result, (tuple, list)) else result
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    raw_list.append(raw)
                except Exception:
                    break
        else:
            # deque 模式
            with self._buf_lock:
                while raw_list.__len__() < self._batch_size and self._buf:
                    raw_list.append(self._buf.popleft())
        return [json.loads(r) for r in raw_list]

    def _drain_queue(self) -> None:
        """清空队列中剩余事件并写入 PG。"""
        total = 0
        while True:
            batch = self._pop_batch()
            if not batch:
                break
            self._batch_insert(batch)
            total += len(batch)
        if total:
            logger.info("PgAuditSink shutdown: drained %d events", total)

    # ------------------------------------------------------------------
    # 批量写入 PG
    # ------------------------------------------------------------------

    def _batch_insert(self, batch: list[dict]) -> None:
        """批量 INSERT 到 ist_audit.audit_log。"""
        if not batch:
            return
        rows = [self._event_to_row(e) for e in batch]
        rows = [r for r in rows if r is not None]
        if not rows:
            return
        self._resolve_user_ids(rows)
        sql = """
            INSERT INTO ist_audit.audit_log (
                user_id, session_id, run_id, thread_id, recorded_at,
                event_kind, event_summary, event_payload,
                model_name, token_input, token_output, token_cache_hit, token_cache_miss,
                tool_name, tool_input, tool_output, tool_duration_ms,
                file_path, file_operation,
                source_ip, is_error, error_message, tags
            ) VALUES (
                %(user_id)s, %(session_id)s, %(run_id)s, %(thread_id)s, %(recorded_at)s,
                %(event_kind)s, %(event_summary)s, %(event_payload)s,
                %(model_name)s, %(token_input)s, %(token_output)s, %(token_cache_hit)s, %(token_cache_miss)s,
                %(tool_name)s, %(tool_input)s, %(tool_output)s, %(tool_duration_ms)s,
                %(file_path)s, %(file_operation)s,
                %(source_ip)s, %(is_error)s, %(error_message)s, %(tags)s
            )
        """
        try:
            from main.ist_core.auth.db import get_pg_connection
            conn = get_pg_connection()
            try:
                with conn.cursor() as cur:
                    cur.executemany(sql, rows)
            finally:
                conn.close()
            logger.debug("PgAuditSink: wrote %d rows", len(rows))
        except Exception as exc:
            logger.warning("PgAuditSink batch INSERT 失败 (%d rows): %s", len(rows), exc)

    # ------------------------------------------------------------------
    # username → user_id 批量解析
    # ------------------------------------------------------------------

    _user_cache: dict[str, str] = {}  # username → user_id UUID（进程级缓存）

    def _resolve_user_ids(self, rows: list[dict]) -> None:
        """批量将 _username 解析为 user_id UUID，写回 rows 的 user_id 字段。"""
        # 第一轮：收集 username，尝试从缓存直接回填
        uncached: list[tuple[dict, str]] = []
        for row in rows:
            if row.get("user_id"):
                row.pop("_username", None)
                continue
            uname = row.pop("_username", None) or ""
            if not uname:
                continue
            if uname in self._user_cache:
                row["user_id"] = self._user_cache[uname]
            else:
                uncached.append((row, uname))

        if not uncached:
            return

        # 批量查 PG
        usernames = list({u for _, u in uncached})
        try:
            from main.ist_core.auth.db import get_pg_connection
            conn = get_pg_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id::text, username FROM ist_audit.users WHERE username = ANY(%s)",
                        (usernames,),
                    )
                    for r in cur.fetchall():
                        self._user_cache[r["username"]] = str(r["id"])
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("PgAuditSink _resolve_user_ids 失败: %s", exc)

        # 第二轮：从缓存回填
        for row, uname in uncached:
            if uname in self._user_cache:
                row["user_id"] = self._user_cache[uname]

    # ------------------------------------------------------------------
    # 事件 → 行映射
    # ------------------------------------------------------------------

    def _event_to_row(self, event: dict) -> dict | None:
        """将 IstCoreEvent 转为 audit_log 行 dict。"""
        kind = event.get("kind", "")
        payload = event.get("payload") or {}
        tags = event.get("tags") or {}
        usage = event.get("usage")

        user_id = tags.get("user_id") or None
        session_id = tags.get("session_id") or None
        thread_id = tags.get("thread_id") or tags.get("configurable_thread_id") or None
        _username = tags.get("session_user") or None

        ts_str = event.get("ts", "")
        try:
            recorded_at = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            recorded_at = datetime.now(timezone.utc)

        summary = self._extract_summary(kind, payload)

        model_name = payload.get("model") or payload.get("name") or tags.get("model") or None
        token_input = token_output = token_cache_hit = token_cache_miss = None
        if usage:
            token_input = usage.get("input_tokens") or usage.get("prompt_tokens")
            token_output = usage.get("output_tokens") or usage.get("completion_tokens")
            token_cache_hit = usage.get("prompt_cache_hit_tokens") or usage.get("cache_hit_input_tokens")
            token_cache_miss = usage.get("prompt_cache_miss_tokens") or usage.get("cache_miss_input_tokens")
            if not model_name:
                model_name = usage.get("model_name")

        tool_name = tool_input = tool_output = tool_duration_ms = None
        if kind in ("tool_call", "tool_start", "tool_result", "tool_end"):
            tool_name = payload.get("name") or tags.get("name") or None
            raw_input = payload.get("input")
            if raw_input is not None:
                tool_input = self._truncate(str(raw_input), _TOOL_INPUT_CAP)
            raw_output = payload.get("output")
            if raw_output is not None:
                tool_output = self._truncate(str(raw_output), _TOOL_OUTPUT_CAP)
            tool_duration_ms = event.get("elapsed_ms")

        file_path = file_operation = None
        if kind in ("file_read", "file_write", "file_edit"):
            file_path = payload.get("path") or payload.get("file_path") or None
            file_operation = {"file_read": "read", "file_write": "write", "file_edit": "edit"}.get(kind)

        is_error = kind in ("error", "run_error", "auth_login_failed", "access_denied")
        error_message = None
        if is_error:
            error_message = self._truncate(payload.get("error") or payload.get("message") or "", _SUMMARY_CAP)

        source_ip = payload.get("source_ip") or tags.get("source_ip") or None

        return {
            "user_id": user_id,
            "session_id": session_id,
            "run_id": event.get("run_id", ""),
            "thread_id": thread_id,
            "recorded_at": recorded_at,
            "event_kind": kind,
            "event_summary": summary,
            "event_payload": json.dumps(payload, default=str) if payload else None,
            "model_name": model_name,
            "token_input": token_input,
            "token_output": token_output,
            "token_cache_hit": token_cache_hit,
            "token_cache_miss": token_cache_miss,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
            "tool_duration_ms": tool_duration_ms,
            "file_path": file_path,
            "file_operation": file_operation,
            "source_ip": source_ip,
            "is_error": is_error,
            "error_message": error_message,
            "tags": json.dumps(tags, default=str) if tags else None,
            "_username": _username,
        }

    @staticmethod
    def _extract_summary(kind: str, payload: dict) -> str:
        for key in ("summary", "message", "error", "content", "info_text"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()[:_SUMMARY_CAP]
        if kind in ("tool_call", "tool_start"):
            name = payload.get("name", "")
            inp = payload.get("input")
            if isinstance(inp, dict):
                preview = json.dumps(inp, ensure_ascii=False, default=str)[:100]
            elif isinstance(inp, str):
                preview = inp[:100]
            else:
                preview = ""
            return f"tool:{name} {preview}".strip()[:_SUMMARY_CAP]
        if kind in ("tool_result", "tool_end"):
            return f"tool_result:{payload.get('name', '')}"[:_SUMMARY_CAP]
        if kind == "llm_end":
            return f"llm_end:{payload.get('name', '')}"[:_SUMMARY_CAP]
        if kind.startswith("auth_"):
            return kind
        return kind

    @staticmethod
    def _truncate(text: str, cap: int) -> str:
        if len(text) <= cap:
            return text
        return text[: cap - 3] + "..."

    # ------------------------------------------------------------------
    # Redis 连接
    # ------------------------------------------------------------------

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
        except Exception as exc:
            logger.warning("PgAuditSink: Redis 不可用，降级为 deque 模式: %s", exc)
            return None
