"""TraceCollector — 对话轮次 trace 聚合采集器。

一次 run（用户提问→agent 回答）聚合为一行结构化记录，写入 ist_audit.trace。
涵盖：执行链路 / 思考文本 / 技能日志 / 知识库检索 / 工具明细 / 报错信息。

架构（Redis 模式）：
    TraceCollector.__call__(): 按 run_id 累积事件到进程内状态
        │
        ▼
    run_end → _finalize(): 构建 trace 行 → LPUSH ist:trace:queue ~0.5ms
        │
        ▼ (守护线程，攒批 5 条 或 2s 超时)
    batch INSERT → ist_audit.trace

架构（降级模式，无 Redis）：
    run_end → _finalize(): deque.append() <0.1ms
        │
        ▼ (守护线程，每 2s 或攒满 5 条)
    batch INSERT → ist_audit.trace

设计要点：
- 进程内按 run_id 维持状态机，零阻塞
- trace 不入 LLM 上下文——只存数据库
- PG 不可用时静默丢弃（与 audit_log 策略一致）
- 单条 run_end INSERT，不在高频路径上
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

_TRACE_REDIS_KEY = "ist:trace:queue"
_TRACE_BATCH_SIZE = 5
_TRACE_FLUSH_INTERVAL = 2.0
_TRACE_MAX_DEQUE_LEN = 5_000

# 知识库检索工具集
_KB_TOOLS = frozenset({
    "fs_grep", "fs_ls", "fs_glob", "fs_read",
    "kb_footprint", "kb_bug_search", "kb_memory_search",
})

# tool_name → category 映射（运行中动态检测，这些是静态已知分类）
_TOOL_CATEGORY_MAP: dict[str, str] = {
    "invoke_skill": "skill",
    "agent_define": "skill",
    "compile_pipeline": "compile",
    "compile_prep": "compile",
    "compile_fanout": "compile",
    "compile_emit": "compile",
    "compile_emit_merged": "compile",
    "compile_precedent": "compile",
    "compile_score": "compile",
    "compile_check_verifiability": "compile",
    "compile_grade_extract": "compile",
    "compile_attribute": "compile",
    "compile_runtime_slots": "compile",
    "compile_runtime_fill": "compile",
    "submit_verdict": "compile",
    "submit_attribution": "compile",
    "compile_skeleton": "compile",
    "compile_expected_hits": "compile",
    "compile_writeback": "compile",
    "compile_footprint_writeback": "compile",
    "dev_ssh": "device",
    "dev_rest": "device",
    "dev_probe": "device",
    "dev_run_case": "device",
    "dev_run_batch": "device",
    "fs_read": "file",
    "fs_write": "file",
    "fs_edit": "file",
    "run_shell": "execute",
    "run_python": "execute",
}


def _tool_category(name: str) -> str:
    return _TOOL_CATEGORY_MAP.get(name, "other")


def _parse_args(raw: Any) -> dict[str, Any]:
    """将 _safe_str 产生的字符串化 dict 还原为真实 dict。

    streaming.py 的 _to_event_payload 调用 ``_safe_str(data["input"])``
    把工具入参 dict 转成 ``"{'pattern': 'show', ...}"`` 字符串，
    TraceCollector 需要 dict 才能提取 pattern / path 等字段。
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        # 先试 JSON（双引号格式）
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass
        # 再试 Python 字面量（单引号格式: "{'a': 'b'}"）
        try:
            import ast
            obj = ast.literal_eval(s)
            if isinstance(obj, dict):
                return obj
        except (ValueError, SyntaxError):
            pass
    return {}


def _is_kb_tool(name: str) -> bool:
    return name in _KB_TOOLS


class _TraceBuilder:
    """单次 run 的结构化数据累积器。"""

    __slots__ = (
        "trace_id", "user_id", "session_id", "conversation_id",
        "thread_id", "user_input", "started_at",
        "demand_classification", "node_path", "llm_calls",
        "thinking_full", "thinking_segments",
        "subagent_runs", "kb_retrievals", "tool_calls",
        "error_info", "status",
        "_tool_seq", "_node_set", "_pending_tools",
        "_subagent_map", "_llm_seq", "_thinking_seq",
        "_tool_use_id_to_idx", "_username",
        "ended_at", "duration_ms",
    )

    def __init__(self, trace_id: str) -> None:
        # run_id 是 12-char hex（uuid4().hex[:12]），不是合法 UUID，补到 32 字符
        import uuid as _uuid
        try:
            padded = trace_id.ljust(32, "0") if len(trace_id) < 32 else trace_id
            self.trace_id: str = str(_uuid.UUID(padded))
        except (ValueError, AttributeError):
            self.trace_id: str = str(_uuid.uuid4())
        self.user_id: str | None = None
        self.session_id: str | None = None
        self.conversation_id: str | None = None
        self.thread_id: str = ""
        self.user_input: str = ""
        self.started_at: str = ""
        self.ended_at: str = ""
        self.duration_ms: int = 0
        self.demand_classification: dict[str, Any] | None = None
        self.node_path: list[str] = []
        self.llm_calls: list[dict[str, Any]] = []
        self.thinking_full: list[str] = []
        self.thinking_segments: list[dict[str, Any]] = []
        self.subagent_runs: list[dict[str, Any]] = []
        self.kb_retrievals: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.error_info: dict[str, Any] = {"errors": [], "total_error_count": 0, "resolved_count": 0, "unresolved_count": 0}
        self.status: str = "running"
        self._tool_seq: int = 0
        self._node_set: set[str] = set()
        self._pending_tools: dict[str, int] = {}
        self._subagent_map: dict[str, int] = {}
        self._llm_seq: int = 0
        self._thinking_seq: int = 0
        self._tool_use_id_to_idx: dict[str, int] = {}

    def record_node(self, node_name: str) -> None:
        if node_name and node_name not in self._node_set:
            self._node_set.add(node_name)
            self.node_path.append(node_name)

    def record_llm_end(self, payload: dict[str, Any], tags: dict[str, Any], usage: dict[str, Any] | None) -> None:
        self._llm_seq += 1
        call: dict[str, Any] = {
            "seq": self._llm_seq,
            "model_name": payload.get("model_name") or tags.get("model_name") or "",
            "node": tags.get("node", ""),
            "phase": "output",
        }
        if usage:
            call["input_tokens"] = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            call["output_tokens"] = usage.get("output_tokens") or usage.get("completion_tokens") or 0
            call["cache_hit"] = usage.get("prompt_cache_hit_tokens") or usage.get("cache_hit_input_tokens") or 0
            call["cache_miss"] = usage.get("prompt_cache_miss_tokens") or usage.get("cache_miss_input_tokens") or 0
        # reasoning_content / thinking
        reasoning = payload.get("reasoning", "")
        if isinstance(reasoning, str) and reasoning.strip():
            self._thinking_seq += 1
            self.thinking_full.append(reasoning.strip())
            self.thinking_segments.append({
                "seq": self._thinking_seq,
                "text": reasoning.strip()[:500],
                "llm_call_seq": self._llm_seq,
            })
            call["phase"] = "thinking"
        self.llm_calls.append(call)

    def record_tool_call(self, name: str, args: dict[str, Any], tags: dict[str, Any]) -> None:
        self._tool_seq += 1
        seq = self._tool_seq
        tool_use_id = tags.get("tool_use_id", "")
        entry: dict[str, Any] = {
            "seq": seq,
            "tool_name": name,
            "display": self._tool_display(name, args),
            "input_preview": self._tool_input_preview(name, args),
            "output_summary": "",
            "is_error": False,
            "duration_ms": 0,
            "parent_subagent": tags.get("parent_subagent") or None,
            "category": _tool_category(name),
        }
        if tool_use_id:
            self._tool_use_id_to_idx[tool_use_id] = seq
        if _is_kb_tool(name):
            self.kb_retrievals.append(entry)
        else:
            self.tool_calls.append(entry)

    def record_tool_result(self, name: str, output: str, is_error: bool, duration_ms: int, tags: dict[str, Any]) -> None:
        tool_use_id = tags.get("tool_use_id", "")
        seq = self._tool_use_id_to_idx.get(tool_use_id)
        if seq is None:
            return
        lists: list[list[dict[str, Any]]] = [self.tool_calls, self.kb_retrievals]
        for lst in lists:
            for entry in lst:
                if entry.get("seq") == seq:
                    entry["is_error"] = is_error
                    entry["duration_ms"] = duration_ms
                    if is_error:
                        entry["output_summary"] = output[:300] if output else ""
                    else:
                        entry["output_summary"] = self._tool_output_summary(name, output)
                    # 知识库检索补充字段
                    if _is_kb_tool(name) and not is_error and output:
                        self._enrich_kb_entry(entry, name, output)
                    return

    def record_error(self, kind: str, payload: dict[str, Any], tags: dict[str, Any]) -> None:
        err = {
            "seq": self._tool_seq,
            "type": kind,
            "message": (payload.get("error") or payload.get("message") or "")[:300],
            "node": tags.get("node", ""),
        }
        self.error_info["errors"].append(err)
        self.error_info["total_error_count"] += 1
        self.error_info["unresolved_count"] += 1

    def record_transient_error(self, resolved: bool) -> None:
        if self.error_info["errors"]:
            last = self.error_info["errors"][-1]
            last["type"] = "transient"
            last["handled_by"] = "retry"
            last["retry_success"] = resolved
        if resolved and self.error_info["unresolved_count"] > 0:
            self.error_info["unresolved_count"] -= 1
            self.error_info["resolved_count"] += 1

    def record_subagent_reference(self, agent_name: str) -> None:
        if agent_name and agent_name not in self._subagent_map:
            self._subagent_map[agent_name] = len(self.subagent_runs)
            self.subagent_runs.append({
                "agent_name": agent_name,
                "skill_name": self._infer_skill_from_agent(agent_name),
                "tool_use_ids": [],
                "llm_call_count": 0,
                "tool_call_count": 0,
                "errors": [],
                "status": "running",
            })

    def record_subagent_llm(self, agent_name: str, tags: dict[str, Any]) -> None:
        idx = self._subagent_map.get(agent_name)
        if idx is not None and idx < len(self.subagent_runs):
            self.subagent_runs[idx]["llm_call_count"] += 1

    def record_subagent_tool(self, agent_name: str, tool_name: str) -> None:
        idx = self._subagent_map.get(agent_name)
        if idx is not None and idx < len(self.subagent_runs):
            sa = self.subagent_runs[idx]
            sa["tool_call_count"] += 1
            tn_set = sa.setdefault("tool_names_used", [])
            if tool_name not in tn_set:
                tn_set.append(tool_name)

    def record_subagent_error(self, agent_name: str, message: str) -> None:
        idx = self._subagent_map.get(agent_name)
        if idx is not None and idx < len(self.subagent_runs):
            self.subagent_runs[idx]["errors"].append(
                {"message": message[:300]}
            )
            self.subagent_runs[idx]["status"] = "error"

    def mark_subagent_done(self, agent_name: str) -> None:
        idx = self._subagent_map.get(agent_name)
        if idx is not None and idx < len(self.subagent_runs):
            if self.subagent_runs[idx].get("status") == "running":
                self.subagent_runs[idx]["status"] = "done"

    def set_status(self, status: str) -> None:
        self.status = status

    def to_db_row(self) -> dict[str, Any]:
        thinking_text = "\n\n".join(self.thinking_full) if self.thinking_full else None
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id or None,
            "session_id": self.session_id or None,
            "conversation_id": self.conversation_id or None,
            "thread_id": self.thread_id or None,
            "user_input": self.user_input[:4000] if self.user_input else None,
            "started_at": self.started_at,
            "ended_at": "___PLACEHOLDER_ENDED_AT___",
            "duration_ms": 0,
            "demand_classification": json.dumps(self.demand_classification, default=str, ensure_ascii=False) if self.demand_classification else None,
            "node_path": self.node_path if self.node_path else None,
            "llm_calls": json.dumps(self.llm_calls, default=str, ensure_ascii=False) if self.llm_calls else None,
            "thinking_full": thinking_text,
            "thinking_segments": json.dumps(self.thinking_segments, default=str, ensure_ascii=False) if self.thinking_segments else None,
            "subagent_runs": json.dumps(self.subagent_runs, default=str, ensure_ascii=False) if self.subagent_runs else None,
            "kb_retrievals": json.dumps(self.kb_retrievals, default=str, ensure_ascii=False) if self.kb_retrievals else None,
            "tool_calls": json.dumps(self.tool_calls, default=str, ensure_ascii=False) if self.tool_calls else None,
            "error_info": json.dumps(self.error_info, default=str, ensure_ascii=False) if self.error_info else None,
            "status": self.status,
        }

    # ── helpers ──

    @staticmethod
    def _tool_display(name: str, args: dict[str, Any]) -> str:
        if not args:
            return name
        if name in ("fs_read", "fs_write", "fs_edit", "fs_ls"):
            path = args.get("file_path") or args.get("path") or ""
            if isinstance(path, str) and path:
                parts = path.replace("\\", "/").split("/")
                return f"{name}({parts[-1]})" if len(parts) <= 2 else f"{name}(.../{'/'.join(parts[-2:])})"
        if name in ("fs_grep", "fs_glob"):
            pattern = args.get("pattern") or args.get("query") or ""
            return f"{name}({str(pattern)[:60]})" if pattern else name
        if name in ("run_shell", "run_python"):
            cmd = str(args.get("command", ""))
            if len(cmd) <= 60:
                return f"{name}({cmd})"
            return f"{name}({cmd[:57]}...)"
        if name == "invoke_skill":
            skill = args.get("skill") or ""
            brief_path = args.get("briefs_path") or args.get("brief") or ""
            if skill and brief_path:
                return f"Skill({skill}, batch)"
            if skill:
                return f"Skill({skill})"
        first_val = next(iter(args.values()), "")
        if isinstance(first_val, str) and len(first_val) <= 80:
            return f"{name}({first_val})"
        return name

    @staticmethod
    def _tool_input_preview(name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        if not args:
            return None
        if name in ("fs_grep", "fs_glob"):
            return {"pattern": args.get("pattern") or args.get("query"), "path": args.get("path")}
        if name == "fs_read":
            return {"file_path": args.get("file_path") or args.get("path"), "limit": args.get("limit")}
        if name == "invoke_skill":
            return {"skill": args.get("skill"), "briefs_path": args.get("briefs_path")}
        # 只保留小参数防止膨胀
        compact = {}
        for k, v in args.items():
            if k in ("raw", "steps_json", "steps"):
                continue
            sv = str(v)
            if len(sv) <= 200:
                compact[k] = v
        return compact if compact else None

    @staticmethod
    def _tool_output_summary(name: str, output: str) -> str:
        if not output:
            return ""
        if name == "fs_read":
            n = output.count("\n") + (1 if output and not output.endswith("\n") else 0)
            return f"Read {n} lines"
        if name in ("fs_glob", "fs_ls"):
            lines = [l for l in output.split("\n") if l.strip()]
            return f"{len(lines)} matches"
        if name == "fs_grep":
            lines = [l for l in output.split("\n") if l.strip()]
            return f"{len(lines)} matches"
        return output[:200] if len(output) > 200 else output

    @staticmethod
    def _enrich_kb_entry(entry: dict[str, Any], name: str, output: str) -> None:
        """从工具输出提取知识库检索的 files_hit / matches_count。"""
        lines = [l for l in output.split("\n") if l.strip()]
        entry["matches_count"] = len(lines)
        # extract file paths from grep/ls/glob output lines
        file_paths: list[str] = []
        for line in lines[:20]:
            # grep format: "path/to/file:content" or "path/to/file:123:content"
            if ":" in line:
                head = line.split(":")[0].strip()
            else:
                head = line.strip()
            if head and ("/" in head or "\\" in head or head.endswith((".md", ".json", ".txt", ".py", ".yaml"))):
                file_paths.append(head)
        if file_paths:
            entry["files_hit"] = list(dict.fromkeys(file_paths))[:10]

    @staticmethod
    def _infer_skill_from_agent(agent_name: str) -> str:
        """从 dyn-* 子 agent 名推断 skill 名。"""
        if agent_name.startswith("dyn-"):
            return agent_name[4:]
        return ""


class TraceCollector:
    """对话轮次 trace 聚合采集器。

    注册为 EventBus sink，在一次 Agent run 中累积执行状态。
    run_end 时将结构化 trace 入队 TraceQueue，由后台守护线程批量写入 PG。

    用法::

        collector = TraceCollector()
        bus.subscribe(collector)
    """

    def __init__(self) -> None:
        self._builders: dict[str, _TraceBuilder] = {}
        self._builders_lock = threading.Lock()
        self._queue = TraceQueue.get()

    def __call__(self, event: IstCoreEvent) -> None:
        kind = event.get("kind", "")
        try:
            self._handle(kind, event)
        except Exception:  # noqa: BLE001
            logger.debug("TraceCollector _handle 异常: kind=%s", kind, exc_info=True)

    def _handle(self, kind: str, event: IstCoreEvent) -> None:
        run_id = event.get("run_id", "")
        payload = event.get("payload") or {}
        tags = event.get("tags") or {}
        usage = event.get("usage")
        elapsed = event.get("elapsed_ms")

        if kind == "run_start":
            b = _TraceBuilder(run_id)
            b.user_input = payload.get("user_input") or payload.get("query") or ""
            b.thread_id = tags.get("configurable_thread_id") or tags.get("thread_id") or ""
            b.session_id = tags.get("session_id") or None
            b.conversation_id = tags.get("conversation_id") or None
            b._username = tags.get("session_user") or None
            b.started_at = datetime.now(timezone.utc).isoformat()
            with self._builders_lock:
                self._builders[run_id] = b
            return

        # 没有对应 run_id 的 builder（可能是 run_start 之前的事件）→ 忽略
        with self._builders_lock:
            b = self._builders.get(run_id)
            if b is None:
                return

        if kind == "run_end":
            b.set_status("done")
            self._finalize(b, run_id)

        elif kind == "run_error":
            b.set_status("error")
            b.record_error("run_error", payload, tags)
            self._finalize(b, run_id)

        elif kind == "node_start":
            node = tags.get("node") or tags.get("name") or ""
            b.record_node(node)

        elif kind == "node_end":
            node = tags.get("node") or tags.get("name") or ""
            b.record_node(node)

        elif kind == "llm_end":
            parent_subagent = tags.get("parent_subagent") or ""
            if parent_subagent:
                b.record_subagent_reference(parent_subagent)
                b.record_subagent_llm(parent_subagent, tags)
            b.record_llm_end(payload, tags, usage)

        elif kind == "llm_start":
            parent_subagent = tags.get("parent_subagent") or ""
            if parent_subagent:
                b.record_subagent_reference(parent_subagent)

        elif kind in ("tool_call", "tool_start"):
            tool_name = tags.get("name") or payload.get("name") or ""
            if not tool_name:
                return
            parent_subagent = tags.get("parent_subagent") or ""
            if parent_subagent:
                b.record_subagent_reference(parent_subagent)
                b.record_subagent_tool(parent_subagent, tool_name)
            raw_input = payload.get("input") or {}
            args = _parse_args(raw_input)
            b.record_tool_call(tool_name, args, tags)

        elif kind in ("tool_result", "tool_end"):
            tool_name = tags.get("name") or payload.get("name") or ""
            if not tool_name:
                return
            output = payload.get("output") or ""
            is_error = kind == "error" or payload.get("is_error", False)
            if not is_error and output:
                # 瞬态错误判断
                from main.ist_core.resilience import is_transient_error
                if isinstance(output, str) and is_transient_error(output):
                    is_error = True
                    b.record_transient_error(True)
            b.record_tool_result(tool_name, output, is_error, elapsed or 0, tags)
            parent_subagent = tags.get("parent_subagent") or ""
            if parent_subagent:
                b.mark_subagent_done(parent_subagent)

        elif kind in ("error", "warn"):
            parent_subagent = tags.get("parent_subagent") or ""
            if parent_subagent:
                b.record_subagent_reference(parent_subagent)
                b.record_subagent_error(parent_subagent, payload.get("error") or payload.get("message") or "")
            b.record_error(kind, payload, tags)

        elif kind == "info":
            # 捕获 demand classification（从 goal_gate 或 normalize_input 后的首条 info）
            phase = tags.get("progress_event") or ""
            if phase in ("phase_marker",) and payload.get("phase"):
                pass  # 后续扩展：捕获需求判定阶段

        elif kind == "evidence_added":
            pass  # 编译证据线——已由 tool_call 覆盖

    def _finalize(self, b: _TraceBuilder, run_id: str) -> None:
        with self._builders_lock:
            self._builders.pop(run_id, None)
        # 计算 duration
        try:
            st = datetime.fromisoformat(b.started_at)
            et = datetime.now(timezone.utc)
            delta = (et - st).total_seconds()
            b.ended_at = et.isoformat()
            b.duration_ms = int(delta * 1000)
        except Exception:
            b.ended_at = datetime.now(timezone.utc).isoformat()
            b.duration_ms = 0
        # 解析 user_id
        raw = b.to_db_row()
        raw["ended_at"] = b.ended_at
        raw["duration_ms"] = b.duration_ms
        self._queue.enqueue(raw, username=getattr(b, "_username", None))


class TraceQueue:
    """trace 行队列单例：run_end 入队 + 后台守护线程批量写入 PG。"""

    _instance: TraceQueue | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._redis = self._build_redis()
        self._buf: deque[str] = deque(maxlen=_TRACE_MAX_DEQUE_LEN)
        self._buf_lock = threading.Lock()
        self._running = True
        self._consumer_thread: threading.Thread | None = None
        self._flush_event = threading.Event()

        mode = "Redis" if self._redis else "deque (降级)"
        logger.info("TraceQueue 初始化，模式: %s", mode)

        self._start_consumer()
        atexit.register(self.shutdown)

    @classmethod
    def get(cls) -> TraceQueue:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def enqueue(self, row: dict[str, Any], *, username: str | None = None) -> None:
        if username:
            row["_username"] = username
        raw = json.dumps(row, default=str)
        if self._redis is not None:
            try:
                self._redis.lpush(_TRACE_REDIS_KEY, raw)
                return
            except Exception:
                logger.debug("TraceQueue LPUSH 失败，降级到 deque")
                self._redis = None
        with self._buf_lock:
            self._buf.append(raw)
        if len(self._buf) >= _TRACE_BATCH_SIZE:
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
            name="trace-queue-consumer",
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
                logger.debug("TraceQueue consumer 异常", exc_info=True)
            self._flush_event.wait(timeout=_TRACE_FLUSH_INTERVAL)
            self._flush_event.clear()

    def _pop_batch(self) -> list[dict]:
        raw_list: list[str] = []
        if self._redis is not None:
            for _ in range(_TRACE_BATCH_SIZE):
                try:
                    result = self._redis.brpop(_TRACE_REDIS_KEY, timeout=0.1)
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
                while raw_list.__len__() < _TRACE_BATCH_SIZE and self._buf:
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
            logger.info("TraceQueue shutdown: drained %d rows", total)

    def _batch_insert(self, batch: list[dict]) -> None:
        if not batch:
            return
        # 解析 user_id
        self._resolve_user_ids(batch)
        sql = """
            INSERT INTO ist_audit.trace (
                trace_id, user_id, session_id, conversation_id, thread_id,
                user_input, started_at, ended_at, duration_ms,
                demand_classification, node_path, llm_calls,
                thinking_full, thinking_segments,
                subagent_runs, kb_retrievals, tool_calls, error_info,
                status
            ) VALUES (
                %(trace_id)s, %(user_id)s, %(session_id)s, %(conversation_id)s, %(thread_id)s,
                %(user_input)s, %(started_at)s, %(ended_at)s, %(duration_ms)s,
                %(demand_classification)s, %(node_path)s, %(llm_calls)s,
                %(thinking_full)s, %(thinking_segments)s,
                %(subagent_runs)s, %(kb_retrievals)s, %(tool_calls)s, %(error_info)s,
                %(status)s
            )
            ON CONFLICT (trace_id) DO NOTHING
        """
        try:
            from main.ist_core.auth.db import get_pg_connection
            conn = get_pg_connection()
            try:
                with conn.cursor() as cur:
                    cur.executemany(sql, batch)
            finally:
                conn.close()
            logger.debug("TraceQueue: wrote %d rows", len(batch))
        except Exception as exc:
            logger.warning("TraceQueue batch INSERT 失败 (%d rows): %s", len(batch), exc)

    _user_cache: dict[str, str] = {}

    def _resolve_user_ids(self, batch: list[dict]) -> None:
        uncached: list[tuple[dict, str]] = []
        for row in batch:
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
            logger.debug("TraceQueue _resolve_user_ids 失败: %s", exc)
        for row, uname in uncached:
            if uname in self._user_cache:
                row["user_id"] = self._user_cache[uname]

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
            logger.debug("TraceQueue: Redis 不可用，降级为 deque 模式: %s", exc)
            return None
