"""FooterPane — status bar component (bottom-fixed).

Shows: status indicator + token count + model name.
Live timer during loading (like old TUI's ✶ Cogitating… format).
"""

from __future__ import annotations

import random
import threading
import time

from ..dom import DOMElement, NodeType, create_element, create_text
from ...pricing import compute_cost_rmb

_VERBS = [
    "Thinking", "Considering", "Analyzing", "Brewing", "Pondering",
    "Cogitating", "Reflecting", "Processing", "Evaluating", "Examining",
]

# footer 括号内尾字段：显示 mimo **当前真实状态**（由实际流式相位驱动，非按秒数假计时）。
# thinking = 正在收到 reasoning_content delta（真在深度思考）；
# output   = 正在收到 content delta（真在生成回答）；
# input    = 请求已发、尚无 delta（接收/处理中）。
# 无相位（工具执行 / 编排间隙）→ 回退显示模型名。
_PHASE_STATE_TEXT = {
    "thinking": "深度思考中",
    "output": "生成回答中",
    "input": "接收/处理中",
}


def _format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _format_token_count(n: int) -> str:
    """≥1k 时缩为 XX.Xk，便于扫读大用量。"""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return f"{n:,}"


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
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.fork_input: int = 0      # fork(draft/grade)累计用量 → 合并进总 token + 成本显示
        self.fork_output: int = 0
        self._latest_evidence: str = ""   # 最新一条 fork 步骤,塞进 busy 状态行(单行,不刷 transcript)
        self._cache_hit_tokens: int = 0
        self._llm_phase: str = ""
        self._output_token_count: int = 0
        # 本轮 run 开始时的累计快照，用于算本轮增量
        self._run_start_input: int = 0
        # 最近一条 fork/evidence 事件时间（ist_app 的 evidence tailer 更新）——
        # main 无相位且 fork 静默过久时，busy 行标注「在等 worker」。
        self.fork_last_event_ts: float = 0.0
        self._run_start_output: int = 0
        self._busy_since: float = 0.0
        self._verb: str = ""
        self._timer: threading.Timer | None = None
        self._timer_running = False
        self._search_query: str | None = None
        self._search_match: str | None = None
        self._toast_text: str | None = None
        self._toast_timer: threading.Timer | None = None
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
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        fork_input: int | None = None,
        fork_output: int | None = None,
        latest_evidence: str | None = None,
        llm_phase: str | None = None,
        output_token_count: int | None = None,
        cache_hit_tokens: int | None = None,
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
        if input_tokens is not None:
            self.input_tokens = input_tokens
        if output_tokens is not None:
            self.output_tokens = output_tokens
        if fork_input is not None:
            self.fork_input = fork_input
        if fork_output is not None:
            self.fork_output = fork_output
        if latest_evidence is not None:
            self._latest_evidence = latest_evidence
        if llm_phase is not None:
            self._llm_phase = llm_phase
        if output_token_count is not None:
            self._output_token_count = output_token_count
        if cache_hit_tokens is not None:
            self._cache_hit_tokens = cache_hit_tokens
        self._refresh()

    def set_search_state(self, query: str | None, match: str | None) -> None:
        """Show / hide reverse-i-search status (overrides thinking + status row)."""
        self._search_query = query
        self._search_match = match
        self._refresh()

    def set_toast(self, text: str | None, ttl_seconds: float = 1.2) -> None:
        """Briefly flash text on the status row (e.g. "Copied 12 chars").

        Priority order in _refresh: search > toast > thinking > default
        status. Pass text=None to clear immediately.
        """
        if self._toast_timer is not None:
            self._toast_timer.cancel()
            self._toast_timer = None
        self._toast_text = text
        self._refresh()
        if self._render_cb:
            self._render_cb()
        if text and ttl_seconds > 0:
            t = threading.Timer(ttl_seconds, self._clear_toast)
            t.daemon = True
            self._toast_timer = t
            t.start()

    def _clear_toast(self) -> None:
        self._toast_text = None
        self._toast_timer = None
        self._refresh()
        if self._render_cb:
            self._render_cb()

    def _start_timer(self) -> None:
        if self._timer_running:
            return
        self._busy_since = time.time()
        self._verb = random.choice(_VERBS)
        # 快照当前累计值，后续算本轮增量
        self._run_start_input = self.input_tokens + self.fork_input
        self._run_start_output = self.output_tokens + self.fork_output
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

    def _session_summary(self) -> str:
        """输入框下方常驻摘要：会话累计 ↑/↓ token + 花费（人民币）。

        花费按 cache 拆分精确算：hit = 会话累计命中，miss = 总输入 − hit。
        未知模型（定价表无）显示 ¥0.00。
        """
        total_in = self.input_tokens + self.fork_input
        total_out = self.output_tokens + self.fork_output
        hit = min(self._cache_hit_tokens, total_in)
        miss = max(total_in - hit, 0)
        parts = [
            f"↑ {_format_token_count(total_in)} · ↓ {_format_token_count(total_out)} tokens"
        ]
        if self.model:
            parts.append(self.model)
        cost = compute_cost_rmb(
            self.model, input_miss=miss, input_hit=hit, output=total_out
        )
        parts.append("¥0.00" if cost is None else f"¥{cost:.4f}")
        return " · ".join(parts)

    def _refresh(self) -> None:
        if self._search_query is not None:
            match_disp = self._search_match if self._search_match else ""
            status_text = f"(reverse-i-search) '{self._search_query}': {match_disp}"
            if self._thinking_cb:
                self._thinking_cb(None)
            self._status_line.set_value(status_text)
            self._hint_line.set_value(
                "ctrl+r next · enter accept · esc cancel"
            )
            return
        if self._toast_text is not None:
            if self._thinking_cb:
                self._thinking_cb(None)
            self._status_line.set_value(self._toast_text)
            
            self._hint_line.set_value(
                "ctrl+c abort · ctrl+d exit · / commands · ↑↓ history"
            )
            return
        if self._timer_running and self._busy_since:
            elapsed = time.time() - self._busy_since
            elapsed_str = _format_elapsed(elapsed)
            # 本轮增量 = 当前累计 − 本轮开始时快照
            _run_in = max(0, self.input_tokens + self.fork_input - self._run_start_input)
            _run_out = max(0, self.output_tokens + self.fork_output - self._run_start_output)
            # 尾字段 = mimo 当前真实状态（由实际流式相位驱动，零假计时）；前面随机词不动。
            _state = _PHASE_STATE_TEXT.get(self._llm_phase)   # 无相位 → None
            # 有真实相位（input/thinking/output）才带 "token · 状态" 尾字段：
            #   input=上传阶段（↑，本轮增量）；
            #   thinking/output=生成阶段（↓，用实时 _output_token_count——每 token 累加、
            #     含思考期 reasoning；input 也叠加到 ↑，让用户看到本轮总消耗）。
            if _state:
                if self._llm_phase == "input":
                    _tok = (
                        f"↑ {_format_token_count(_run_in)}"
                        f" · ↓ {_format_token_count(_run_out)} tokens"
                    )
                else:  # thinking / output
                    _tok = (
                        f"↑ {_format_token_count(_run_in)}"
                        f" · ↓ {_format_token_count(self._output_token_count)} tokens"
                    )
                thinking_text = f"✶ {self._verb}… ({elapsed_str} · {_tok} · {_state})"
            else:
                # 无相位常见于 main 阻塞等 fork/长工具。
                # fork 静默期仍要显本轮 token 增量（fork_input 实时递增），
                # 让用户看到 fork 在烧钱、有进展；静默 ≥15s 再加 worker 提示。
                _tok = (
                    f" · ↑ {_format_token_count(_run_in)}"
                    f" · ↓ {_format_token_count(_run_out)} tokens"
                )
                _fork_wait = ""
                if self.fork_last_event_ts > (self._busy_since or 0.0):
                    _idle = time.time() - self.fork_last_event_ts
                    if _idle >= 15:
                        _fork_wait = f" · ◌ worker {int(_idle)}s 无新事件"
                thinking_text = f"✶ {self._verb}… ({elapsed_str}{_tok}{_fork_wait})"
            if self._thinking_cb:
                self._thinking_cb(thinking_text)
        else:
            
            if self._thinking_cb:
                self._thinking_cb(None)
        
        status_text = self._session_summary()
        self._status_line.set_value(status_text)
        self._hint_line.set_value(
            "ctrl+c abort · ctrl+d exit · / commands · ↑↓ history"
        )
