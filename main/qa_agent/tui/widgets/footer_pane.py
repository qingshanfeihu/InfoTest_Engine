"""FooterPane：风格的屏底状态条。

照搬 
- status 行：``✶ Considering… (1m 1s · ↑ 181 tokens)``
  - ✶ U+2736 八角星（不是盲文 ⠋）
  - 动词从 ``SPINNER_VERBS`` 列表里随机选（每次进 busy 状态时锁定一个）
  - 括号：耗时（mm:ss / 1m 1s）+ ``↑ token 数``
- hint 行：``esc to interrupt``
"""

from __future__ import annotations

import random
import time

from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static


SPINNER_GLYPH = "✶"
SPINNER_TICK_S = 0.5  # 状态行刷新间隔（不是动画——只为更新耗时）

SPINNER_VERBS = (
    "Accomplishing", "Actioning", "Architecting", "Brewing", "Calculating",
    "Cogitating", "Composing", "Considering", "Contemplating", "Cooking",
    "Crafting", "Creating", "Deciphering", "Discovering", "Distilling",
    "Forging", "Investigating", "Munching", "Mulling", "Noodling",
    "Percolating", "Pondering", "Processing", "Reasoning", "Reflecting",
    "Searching", "Synthesizing", "Thinking", "Working", "Wrangling",
)

DEFAULT_HINT_LINE = "esc to interrupt"


def _format_elapsed(seconds: float) -> str:
    """``1.2s`` / ``45s`` / ``1m 1s`` / ``1h 2m`` ."""
    if seconds < 60:
        return f"{int(seconds)}s" if seconds >= 10 else f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


class FooterPane(Vertical):
    """2-line bottom status pane (status row + hint row)."""

    DEFAULT_CSS = """
    FooterPane {
        dock: bottom;
        height: 2;
        background: $surface-darken-1;
    }
    FooterPane #footer-status {
        height: 1;
        padding: 0 1;
        color: $text;
    }
    FooterPane #footer-hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    FooterPane.budget-warn #footer-status { color: $warning; }
    FooterPane.budget-danger #footer-status { color: $error; }
    """

    is_busy: reactive[bool] = reactive(False)
    tokens_used: reactive[int] = reactive(0)
    tokens_budget: reactive[int] = reactive(128_000)
    model_name: reactive[str] = reactive("qwen-plus")

    def __init__(self) -> None:
        super().__init__()
        self._verb = "Considering"
        self._busy_since: float | None = None
        self._spinner_handle = None  # set_interval handle

    def compose(self):
        yield Static("", id="footer-status")
        yield Static(DEFAULT_HINT_LINE, id="footer-hint")

    def on_mount(self) -> None:
        self._spinner_handle = self.set_interval(SPINNER_TICK_S, self._tick)
        self._refresh_status()

    # -- Reactive watchers --------------------------------------------------

    def watch_is_busy(self, _old: bool, new: bool) -> None:
        if new:
            # 进入 busy：锁定一个随机动词 + 记录开始时间
            self._verb = random.choice(SPINNER_VERBS)
            self._busy_since = time.time()
        else:
            self._busy_since = None
        self._refresh_status()

    def watch_tokens_used(self, _old: int, _new: int) -> None:
        self._refresh_status()
        self._refresh_budget_class()

    def watch_tokens_budget(self, _old: int, _new: int) -> None:
        self._refresh_status()
        self._refresh_budget_class()

    def watch_model_name(self, _old: str, _new: str) -> None:
        self._refresh_status()

    # -- Periodic tick: 仅刷新耗时显示 ----------------------------------------

    def _tick(self) -> None:
        if not self.is_busy:
            return
        self._refresh_status()

    def _refresh_status(self) -> None:
        try:
            status = self.query_one("#footer-status", Static)
        except Exception:
            return
        if self.is_busy and self._busy_since is not None:
            elapsed = time.time() - self._busy_since
            elapsed_str = _format_elapsed(elapsed)
            text = (
                f"{SPINNER_GLYPH} {self._verb}… "
                f"({elapsed_str} · ↑ {self.tokens_used:,} tokens · {self.model_name})"
            )
        else:
            text = ""
        status.update(text)

    def _refresh_budget_class(self) -> None:
        budget = max(1, self.tokens_budget)
        ratio = self.tokens_used / budget
        self.remove_class("budget-warn")
        self.remove_class("budget-danger")
        if ratio >= 0.95:
            self.add_class("budget-danger")
        elif ratio >= 0.80:
            self.add_class("budget-warn")

    def update_hint(self, text: str | None = None) -> None:
        try:
            hint = self.query_one("#footer-hint", Static)
        except Exception:
            return
        hint.update(text if text is not None else DEFAULT_HINT_LINE)
