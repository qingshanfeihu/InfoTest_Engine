"""CLI Sink：实时渲染 ``QaAgentEvent`` 到终端。

对应原计划 §16.3。80ms 节流聚合 llm_token，其余事件直接带色前缀打印。
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from main.qa_agent.events import QaAgentEvent

_COLOR_MAP = {
    "node_start": "\033[36m",   # cyan
    "node_end": "\033[90m",
    "tool_call": "\033[35m",    # magenta
    "tool_result": "\033[32m",  # green
    "llm_start": "\033[34m",    # blue
    "llm_end": "\033[90m",
    "hil_request": "\033[33m",  # yellow
    "hil_response": "\033[33m",
    "finding_written": "\033[36m",
    "error": "\033[31m",        # red
    "warn": "\033[33m",
    "info": "\033[90m",
}
_RESET = "\033[0m"


class CLISink:
    """调用方：``bus.subscribe(CLISink(verbose=True))``。"""

    def __init__(self, *, verbose: bool = False, no_color: bool = False, throttle_ms: int = 80) -> None:
        self.verbose = verbose
        self.no_color = no_color
        self.throttle_s = throttle_ms / 1000.0
        self._token_buf: list[str] = []
        self._last_flush = 0.0
        self._lock = threading.Lock()

    def __call__(self, event: QaAgentEvent) -> None:
        kind = event.get("kind")
        if kind == "llm_token":
            self._handle_token(event)
            return
        self._flush_tokens(force=True)
        self._print_event(event)

    def _handle_token(self, event: QaAgentEvent) -> None:
        content = (event.get("payload") or {}).get("content") or ""
        if not content:
            return
        with self._lock:
            self._token_buf.append(content)
            now = time.time()
            if now - self._last_flush >= self.throttle_s:
                self._flush_tokens_unsafe()
                self._last_flush = now

    def _flush_tokens(self, *, force: bool = False) -> None:
        with self._lock:
            if self._token_buf and (force or time.time() - self._last_flush >= self.throttle_s):
                self._flush_tokens_unsafe()

    def _flush_tokens_unsafe(self) -> None:
        if not self._token_buf:
            return
        chunk = "".join(self._token_buf)
        self._token_buf.clear()
        sys.stdout.write(chunk)
        sys.stdout.flush()

    def _print_event(self, event: QaAgentEvent) -> None:
        kind = event.get("kind") or ""
        color = "" if self.no_color else _COLOR_MAP.get(kind, "")
        reset = "" if self.no_color else _RESET

        tags = event.get("tags") or {}
        name = tags.get("name") or ""
        node = tags.get("node") or ""
        label = f"{name or node}" if (name or node) else ""

        base = f"{color}[{kind}]{reset}"
        if label:
            base = f"{base} {label}"

        if self.verbose:
            payload = event.get("payload") or {}
            extra = {k: v for k, v in payload.items() if k != "content"}
            if extra:
                base += " " + json.dumps(extra, ensure_ascii=False, default=str)[:300]
            usage = event.get("usage")
            if usage:
                base += f"  usage={usage}"

        if kind in {"run_start", "run_end", "tool_call", "tool_result", "node_start", "error", "warn", "hil_request"}:
            print(base, flush=True)
        elif self.verbose:
            print(base, flush=True)

    def replay(self, jsonl_path: str) -> None:
        """从 jsonl 文件读事件、按 seq 排序后回放。"""
        p = Path(jsonl_path)
        if not p.exists():
            print(f"[replay] 文件不存在: {p}", file=sys.stderr)
            return
        events: list[QaAgentEvent] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        events.sort(key=lambda e: e.get("seq") or 0)
        for ev in events:
            self.__call__(ev)
        self._flush_tokens(force=True)
