"""FooterPane — status bar component (bottom-fixed).

Shows: status indicator + token count + model name.
Live timer during loading (like old TUI's ✶ Cogitating… format).
"""

from __future__ import annotations

import random
import threading
import time

from ..dom import DOMElement, NodeType, create_element, create_text

_VERBS = [
    "Thinking", "Considering", "Analyzing", "Brewing", "Pondering",
    "Cogitating", "Reflecting", "Processing", "Evaluating", "Examining",
]


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


class FooterPane:
    """Fixed-height footer showing status, tokens, and model."""

    def __init__(self, *, render_callback=None, thinking_text_cb=None) -> None:
        self._node = create_element(NodeType.BOX)
        self._node.style.height = 2
        self._node.text_styles.dim = True
        self._status_line = create_text("")
        self._hint_line = create_text("")
        self._node.append_child(self._status_line)
        self._node.append_child(self._hint_line)

        self._render_cb = render_callback
        self._thinking_cb = thinking_text_cb
        self.status: str = "ready"
        self.tokens_used: int = 0
        self.tokens_budget: int = 128_000
        self.model: str = ""
        self._busy_since: float = 0.0
        self._verb: str = ""
        self._timer: threading.Timer | None = None
        self._timer_running = False
        self._refresh()

    @property
    def node(self) -> DOMElement:
        return self._node

    def update(
        self,
        *,
        status: str | None = None,
        tokens_used: int | None = None,
        tokens_budget: int | None = None,
        model: str | None = None,
    ) -> None:
        if status is not None:
            self.status = status
            if status not in ("ready", "error"):
                self._start_timer()
            else:
                self._stop_timer()
        if tokens_used is not None:
            self.tokens_used = tokens_used
        if tokens_budget is not None:
            self.tokens_budget = tokens_budget
        if model is not None:
            self.model = model
        self._refresh()

    def _start_timer(self) -> None:
        if self._timer_running:
            return
        self._busy_since = time.time()
        self._verb = random.choice(_VERBS)
        self._timer_running = True
        self._tick()

    def _stop_timer(self) -> None:
        self._timer_running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _tick(self) -> None:
        if not self._timer_running:
            return
        self._refresh()
        if self._render_cb:
            self._render_cb()
        self._timer = threading.Timer(0.5, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _refresh(self) -> None:
        if self._timer_running and self._busy_since:
            elapsed = time.time() - self._busy_since
            elapsed_str = _format_elapsed(elapsed)
            thinking_text = f"✶ {self._verb}… ({elapsed_str} · ↑ {self.tokens_used:,} tokens · {self.model})"
            status_text = thinking_text
            # Update thinking line above divider
            if self._thinking_cb:
                self._thinking_cb(thinking_text)
        else:
            parts = [self.status]
            # 累计消耗（多轮 LLM call 求和），不是上下文窗口占用——
            # 不展示 budget 比例，避免和模型上下文上限混淆
            parts.append(f"{self.tokens_used:,} tokens")
            if self.model:
                parts.append(self.model)
            status_text = " · ".join(parts)
            # Hide thinking line
            if self._thinking_cb:
                self._thinking_cb(None)
        self._status_line.set_value(status_text)
        self._hint_line.set_value(
            "ctrl+c abort · ctrl+d exit · / commands · ↑↓ history"
        )
