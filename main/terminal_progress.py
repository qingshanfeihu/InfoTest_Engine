"""Unified terminal progress display and LLM event logging for the pipeline."""

from __future__ import annotations

import contextvars
import os
import sys
import threading
import time
from typing import Any

_active_progress: contextvars.ContextVar[TerminalProgress | None] = contextvars.ContextVar(
    "_active_progress", default=None
)

_SPINNER = r"-\|/"
_BAR_WIDTH = 20
_TICK_INTERVAL = 0.5


def _is_progress_enabled() -> bool:
    val = os.environ.get("NO_PROGRESS", "").strip().lower()
    return val not in ("1", "true", "yes")


class TerminalProgress:
    """Single-line refreshing progress bar for pipeline steps.

    A daemon thread ticks the spinner every 0.5 s so the display stays alive
    even when the main thread blocks on network I/O.

    Non-TTY or ``NO_PROGRESS=1`` automatically degrades to static output.
    Thread-safe via internal lock (safe for ThreadPoolExecutor concurrency).
    """

    def __init__(self, *, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = _is_progress_enabled() and sys.stderr.isatty()
        self._enabled = enabled
        self._lock = threading.Lock()
        self._paused = False
        self._stopped = False
        self._spin_idx = 0
        self._last_line = ""
        self._macro_phase = ""
        self._macro_index = 0
        self._macro_total = 0
        self._item_label = ""
        self._item_index = 0
        self._item_total = 0
        self._detail = ""
        self._ticker: threading.Thread | None = None
        if self._enabled:
            t = threading.Thread(target=self._tick_loop, daemon=True)
            t.start()
            self._ticker = t

    def _tick_loop(self) -> None:
        while not self._stopped:
            time.sleep(_TICK_INTERVAL)
            with self._lock:
                if not self._stopped and not self._paused:
                    self._render()

    # -- context management --------------------------------------------------

    def enter(self) -> None:
        _active_progress.set(self)

    def leave(self) -> None:
        _active_progress.set(None)

    def __enter__(self) -> TerminalProgress:
        self.enter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.finish()
        self.leave()

    # -- pause / resume (for interleaved print output) -----------------------

    def pause(self) -> None:
        with self._lock:
            if self._enabled and self._last_line:
                sys.stderr.write("\r" + " " * len(self._last_line) + "\r")
                sys.stderr.flush()
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False
            self._render()

    # -- update --------------------------------------------------------------

    def update(
        self,
        *,
        macro_phase: str | None = None,
        macro_index: int | None = None,
        macro_total: int | None = None,
        item_label: str | None = None,
        item_index: int | None = None,
        item_total: int | None = None,
        detail: str | None = None,
    ) -> None:
        with self._lock:
            if macro_phase is not None:
                self._macro_phase = macro_phase
            if macro_index is not None:
                self._macro_index = macro_index
            if macro_total is not None:
                self._macro_total = macro_total
            if item_label is not None:
                self._item_label = item_label
            if item_index is not None:
                self._item_index = item_index
            if item_total is not None:
                self._item_total = item_total
            if detail is not None:
                self._detail = detail
            self._render()

    # -- finish --------------------------------------------------------------

    def finish(self) -> None:
        self._stopped = True
        if self._ticker is not None:
            self._ticker.join(timeout=2.0)
            self._ticker = None
        with self._lock:
            if self._enabled and self._last_line:
                sys.stderr.write("\r" + " " * len(self._last_line) + "\r")
                sys.stderr.flush()
            self._last_line = ""

    # -- internal rendering (must hold self._lock) ---------------------------

    def _render(self) -> None:
        if not self._enabled or self._paused:
            return
        self._spin_idx = (self._spin_idx + 1) % 4
        spinner = _SPINNER[self._spin_idx]

        parts: list[str] = []
        if self._macro_phase:
            if self._macro_total > 0:
                parts.append(f"[{self._macro_index}/{self._macro_total}]")
            parts.append(self._macro_phase)
        parts.append(spinner)
        if self._item_label:
            parts.append(self._item_label)
        if self._item_total > 0:
            parts.append(f"({self._item_index}/{self._item_total})")
        if self._detail:
            parts.append(self._detail)

        pct = 0.0
        if self._item_total > 0:
            pct = self._item_index / self._item_total
        filled = int(_BAR_WIDTH * pct)
        bar = "#" * filled + "." * (_BAR_WIDTH - filled)
        parts.append(f"[{bar}] {pct:.0%}")

        line = " ".join(parts)
        try:
            cols = os.get_terminal_size(sys.stderr.fileno()).columns
            if len(line) > cols:
                line = line[: cols - 1]
        except (ValueError, OSError):
            pass

        if self._last_line:
            clear_len = max(len(self._last_line), len(line))
            sys.stderr.write("\r" + " " * clear_len + "\r" + line)
        else:
            sys.stderr.write("\r" + line)
        sys.stderr.flush()
        self._last_line = line


# ---------------------------------------------------------------------------
# Unified LLM event logging
# ---------------------------------------------------------------------------

def emit_llm_event(event_type: str, message: str) -> None:
    """Write a formatted LLM diagnostic line to stderr.

    If an active ``TerminalProgress`` exists in the current context,
    automatically pauses and resumes it so the line doesn't collide with
    the progress bar.
    """
    line = f"[LLM] [{event_type}] {message}"
    progress = _active_progress.get(None)
    if progress is not None:
        progress.pause()
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
        progress.resume()
    else:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def emit_status(message: str) -> None:
    """Write a plain status line to stderr, respecting active progress."""
    progress = _active_progress.get(None)
    if progress is not None:
        progress.pause()
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
        progress.resume()
    else:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
