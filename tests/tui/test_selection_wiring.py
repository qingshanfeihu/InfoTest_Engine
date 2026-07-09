"""Integration-level tests for the IstInkApp mouse + selection wiring.

These tests don't drive a real terminal — they construct an InkApp,
inject MouseEvent objects directly via _handle_mouse / _handle_left_press
/ _handle_key, and assert the resulting selection state, clipboard
calls, and footer state.

Real terminal behaviors that can't be tested here (and need manual
verification): drag highlight rendering, pbcopy actually writing to
the system clipboard, tmux passthrough reaching the outer terminal,
mouse-capture sequences leaving the terminal cleanly on exit.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from main.ist_core.ink.parse_keypress import KeyPress, MouseEvent
from main.ist_core.ink.screen import (
    CELL_NORMAL,
    CELL_SPACER,
    CELL_WIDE,
    CharPool,
    Screen,
    StylePool,
)
from main.ist_core.ink.selection import (
    SelectionState,
    has_selection,
    select_word_at,
    selection_bounds,
    start_selection,
    update_selection,
)







def test_set_clipboard_returns_raw_osc52_outside_tmux(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    
    from main.ist_core.ink.termio import osc as osc_mod
    with patch.object(osc_mod, "_copy_native_async") as native:
        seq = osc_mod.set_clipboard("hello")
    native.assert_called_once_with("hello")
    assert seq.startswith("\x1b]52;c;")
    assert seq.endswith("\x07")
    
    assert "aGVsbG8=" in seq


def test_set_clipboard_skips_native_in_ssh(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 1234 5.6.7.8 22")
    from main.ist_core.ink.termio import osc as osc_mod
    with patch.object(osc_mod, "_copy_native_async") as native:
        seq = osc_mod.set_clipboard("hello")
    native.assert_not_called()
    assert seq.startswith("\x1b]52;c;")


def test_set_clipboard_empty_returns_empty(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    from main.ist_core.ink.termio import osc as osc_mod
    assert osc_mod.set_clipboard("") == ""


def test_set_clipboard_dcs_passthrough_when_tmux_succeeds(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-fake")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    from main.ist_core.ink.termio import osc as osc_mod
    with patch.object(osc_mod, "_copy_native_async"), \
         patch.object(osc_mod, "_tmux_load_buffer_sync", return_value=True):
        seq = osc_mod.set_clipboard("x")
    
    assert seq.startswith("\x1bPtmux;")
    assert seq.endswith("\x1b\\")


def test_set_clipboard_falls_back_to_raw_when_tmux_load_fails(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-fake")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    from main.ist_core.ink.termio import osc as osc_mod
    with patch.object(osc_mod, "_copy_native_async"), \
         patch.object(osc_mod, "_tmux_load_buffer_sync", return_value=False):
        seq = osc_mod.set_clipboard("x")
    
    assert seq.startswith("\x1b]52;c;")
    assert seq.endswith("\x07")







class _FakeApp:
    """Just enough InkApp surface for IstInkApp's mouse logic to exercise.

    Avoids the real terminal init — IstInkApp normally calls InkApp(),
    which opens stdin in raw mode and starts background threads. We
    side-step that by constructing IstInkApp.__new__ and wiring the
    minimum attributes the mouse path touches.
    """

    def __init__(self, width: int = 20, height: int = 5):
        self.lock = _DummyLock()
        char_pool = CharPool()
        self._style_pool = StylePool()
        self._curr_screen = Screen(width, height, char_pool, self._style_pool)
        
        text = " hello world "
        for i, ch in enumerate(text):
            self._curr_screen.set_cell(
                i, 0, char_pool.intern(ch), self._style_pool.none, 0, CELL_NORMAL
            )
        self.selection = SelectionState()
        self.notify_count = 0
        self.render_count = 0
        self.repaint_count = 0
        self.terminal_writes: list[str] = []

    def visible_screen(self):
        # 单缓冲 fake:显示帧就是这块 screen(真实 App 里返回交换后的 _prev_screen)。
        return self._curr_screen

    def _repaint_full(self) -> None:
        self.repaint_count += 1

    def notify_selection_change(self) -> None:
        self.notify_count += 1

    def render(self) -> None:
        self.render_count += 1

    @property
    def _terminal(self):
        return self

    def write(self, s: str) -> None:
        self.terminal_writes.append(s)


class _DummyLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeFooter:
    def __init__(self):
        self.toasts: list[str] = []

    def set_toast(self, text, ttl_seconds=1.2):
        self.toasts.append(text)

    def set_search_state(self, query, match):
        pass


def _make_ist_app():
    """Construct IstInkApp without running its __init__ (which opens
    stdin / spawns threads). We only need the mouse / selection methods."""
    from main.ist_core.ink.components.ist_app import IstInkApp

    obj = IstInkApp.__new__(IstInkApp)
    obj._app = _FakeApp(width=20, height=5)
    obj._footer = _FakeFooter()
    obj._is_loading = False
    return obj


def test_left_press_starts_selection_at_cell():
    app = _make_ist_app()
    me = MouseEvent(type="press", button=0, x=2, y=0)
    app._handle_mouse(me)
    sel = app._app.selection
    assert sel.anchor is not None
    assert sel.anchor.col == 2
    assert sel.anchor.row == 0
    assert sel.is_dragging is True
    assert has_selection(sel) is False


def test_drag_motion_sets_focus_after_real_motion():
    app = _make_ist_app()
    app._handle_mouse(MouseEvent(type="press", button=0, x=2, y=0))
    
    app._handle_mouse(MouseEvent(type="move", button=0, x=2, y=0))
    sel = app._app.selection
    assert sel.focus is None
    
    app._handle_mouse(MouseEvent(type="move", button=0, x=6, y=0))
    assert sel.focus is not None and sel.focus.col == 6


def test_release_auto_copies_when_dragged():
    app = _make_ist_app()
    app._handle_mouse(MouseEvent(type="press", button=0, x=1, y=0))
    app._handle_mouse(MouseEvent(type="move", button=0, x=5, y=0))
    from main.ist_core.ink.termio import osc as osc_mod
    with patch.object(osc_mod, "set_clipboard", return_value="\x1b]52;c;FAKE\x07") as setc:
        app._handle_mouse(MouseEvent(type="release", button=0, x=5, y=0))
    setc.assert_called_once()
    text = setc.call_args[0][0]
    
    assert text == "hello"
    
    assert has_selection(app._app.selection)
    
    assert any("FAKE" in w for w in app._app.terminal_writes)
    
    assert any("Copied" in t for t in app._footer.toasts)


def test_double_click_selects_word():
    app = _make_ist_app()
    
    app._handle_mouse(MouseEvent(type="press", button=0, x=3, y=0))
    app._handle_mouse(MouseEvent(type="release", button=0, x=3, y=0))
    app._handle_mouse(MouseEvent(type="press", button=0, x=3, y=0))
    sel = app._app.selection
    
    assert sel.anchor is not None and sel.anchor.col == 1
    assert sel.focus is not None and sel.focus.col == 5
    assert sel.anchor_span is not None and sel.anchor_span.kind == "word"


def test_triple_click_selects_line():
    app = _make_ist_app()
    for _ in range(3):
        app._handle_mouse(MouseEvent(type="press", button=0, x=3, y=0))
        app._handle_mouse(MouseEvent(type="release", button=0, x=3, y=0))
    
    app._handle_mouse(MouseEvent(type="press", button=0, x=3, y=0))
    sel = app._app.selection
    assert sel.anchor is not None and sel.anchor.col == 0
    assert sel.focus is not None and sel.focus.col == app._app._curr_screen.width - 1
    assert sel.anchor_span is not None and sel.anchor_span.kind == "line"


def test_wheel_routes_to_scroll_transcript():
    """滚轮事件委托给 _scroll_transcript(-3/+3)。wheel 分支自身不直接改选区——
    选区随内容的平移发生在 _scroll_transcript 内部(见
    test_scroll_transcript_shifts_selection_and_captures_offscreen)。这里用桩
    隔离出「wheel→scroll 委托」这一层路由。"""
    app = _make_ist_app()
    from main.ist_core.ink.selection import Point
    app._app.selection.anchor = Point(col=2, row=0)
    app._app.selection.focus = Point(col=5, row=0)

    calls = []
    app._scroll_transcript = lambda d: calls.append(d)
    app._handle_mouse(MouseEvent(type="wheel", button=0, x=0, y=0))
    app._handle_mouse(MouseEvent(type="wheel", button=1, x=0, y=0))
    assert calls == [-3, 3]

    assert app._app.selection.anchor.col == 2
    assert app._app.selection.focus.col == 5


# —— 选区随 transcript 滚动平移(修复:选中后滚轮/PageUp 选中内容随滚动漂移)——


class _FakeRect:
    def __init__(self, y: int, width: int, height: int):
        self.x = 0
        self.y = y
        self.width = width
        self.height = height


class _FakeTranscriptNode:
    def __init__(self, scroll_top: int, rect: "_FakeRect"):
        self.scroll_top = scroll_top
        self.rect = rect


class _FakeTranscript:
    """够 _scroll_transcript 用的最小 Transcript:带 scroll_top + rect 的 node,
    以及复刻 Transcript.scroll_by 顶/底 clamp 语义的 scroll_by。"""

    def __init__(self, scroll_top: int, rect_y: int, rect_height: int, content_rows: int):
        self.node = _FakeTranscriptNode(scroll_top, _FakeRect(rect_y, 10, rect_height))
        self._content_rows = content_rows

    def scroll_by(self, delta: int) -> None:
        max_top = max(0, self._content_rows - self.node.rect.height + 1)
        self.node.scroll_top = max(0, min(max_top, self.node.scroll_top + delta))


class _ScrollApp:
    """滚动路径用的 fake InkApp:真实 Screen + SelectionState + _scroll_transcript
    触及的三个钩子。单缓冲,visible_screen 直接返回这块 screen。"""

    def __init__(self, screen: Screen):
        self.selection = SelectionState()
        self._curr_screen = screen
        self._prev_screen = screen
        self.notify_count = 0
        self.repaint_count = 0

    def visible_screen(self) -> Screen:
        return self._prev_screen

    def notify_selection_change(self) -> None:
        self.notify_count += 1

    def _repaint_full(self) -> None:
        self.repaint_count += 1


def _make_scroll_app(*, scroll_top: int = 10, rect_height: int = 5, content_rows: int = 100):
    """IstInkApp(不跑 __init__) + 5 行不同内容(AAAA..EEEE)的 10×5 屏 + fake transcript。"""
    from main.ist_core.ink.components.ist_app import IstInkApp

    char_pool = CharPool()
    style_pool = StylePool()
    screen = Screen(10, 5, char_pool, style_pool)
    for y, r in enumerate(["AAAA", "BBBB", "CCCC", "DDDD", "EEEE"]):
        for x, ch in enumerate(r):
            screen.set_cell(x, y, char_pool.intern(ch), style_pool.none, 0, CELL_NORMAL)
    obj = IstInkApp.__new__(IstInkApp)
    obj._app = _ScrollApp(screen)
    obj._transcript = _FakeTranscript(scroll_top, 0, rect_height, content_rows)
    return obj


def test_scroll_transcript_shifts_selection_and_captures_offscreen():
    from main.ist_core.ink.selection import Point

    app = _make_scroll_app(scroll_top=10, rect_height=5)
    sel = app._app.selection
    sel.anchor = Point(col=0, row=1)
    sel.focus = Point(col=3, row=3)

    # 向下滚 2(内容上移):两端行号各减 2,anchor 上溢 clamp 到 row0,移出的 BBBB 抓入累加器
    app._scroll_transcript(2)
    assert selection_bounds(sel) == (Point(col=0, row=0), Point(col=3, row=1))
    assert sel.scrolled_off_above == ["BBBB"]
    assert app._app.repaint_count == 1
    assert app._app.notify_count == 1


def test_scroll_transcript_round_trip_restores_selection():
    from main.ist_core.ink.selection import Point

    app = _make_scroll_app(scroll_top=10, rect_height=5)
    sel = app._app.selection
    sel.anchor = Point(col=0, row=1)
    sel.focus = Point(col=3, row=3)

    app._scroll_transcript(2)    # 下滚 2
    app._scroll_transcript(-2)   # 回滚 2 → 复原
    assert selection_bounds(sel) == (Point(col=0, row=1), Point(col=3, row=3))
    assert sel.scrolled_off_above == []


def test_scroll_transcript_noop_when_clamped_at_top():
    from main.ist_core.ink.selection import Point

    app = _make_scroll_app(scroll_top=0, rect_height=5)  # 已在顶部
    sel = app._app.selection
    sel.anchor = Point(col=0, row=1)
    sel.focus = Point(col=3, row=3)

    app._scroll_transcript(-3)   # 继续上滚被 clamp,实际位移 0 → 不平移选区
    assert selection_bounds(sel) == (Point(col=0, row=1), Point(col=3, row=3))
    assert sel.scrolled_off_above == []
    assert app._app.notify_count == 0
    assert app._app.repaint_count == 1  # 仍重绘(残影自愈)


def test_scroll_transcript_ignores_selection_below_viewport():
    from main.ist_core.ink.selection import Point

    # transcript 只占前 3 行,选区落在其下方(row4,如输入框/footer)——不随 transcript 滚
    app = _make_scroll_app(scroll_top=10, rect_height=3)
    sel = app._app.selection
    sel.anchor = Point(col=0, row=4)
    sel.focus = Point(col=3, row=4)

    app._scroll_transcript(2)
    assert selection_bounds(sel) == (Point(col=0, row=4), Point(col=3, row=4))
    assert sel.scrolled_off_above == []
    assert app._app.notify_count == 0


def test_press_on_right_button_is_ignored():
    app = _make_ist_app()
    app._handle_mouse(MouseEvent(type="press", button=2, x=3, y=0))
    assert app._app.selection.anchor is None


def test_release_without_drag_does_not_copy():
    """A bare click (press then release at the same cell) should not copy."""
    app = _make_ist_app()
    app._handle_mouse(MouseEvent(type="press", button=0, x=3, y=0))
    from main.ist_core.ink.termio import osc as osc_mod
    with patch.object(osc_mod, "set_clipboard", return_value="\x1b]52;c;X\x07") as setc:
        app._handle_mouse(MouseEvent(type="release", button=0, x=3, y=0))
    setc.assert_not_called()







class _StubInputHistory:
    in_search_mode = False
    search_query = ""

    def add(self, text): pass


def _attach_minimum_key_state(app):
    """The Ctrl+C-while-selected branch only needs `selection`, but the
    fall-through branch touches `_input_history` and `_is_loading`."""
    app._input_history = _StubInputHistory()
    app._is_loading = False


def test_ctrl_c_with_selection_copies_and_does_not_abort():
    app = _make_ist_app()
    _attach_minimum_key_state(app)
    
    from main.ist_core.ink.selection import Point
    app._app.selection.anchor = Point(col=1, row=0)
    app._app.selection.focus = Point(col=5, row=0)

    from main.ist_core.ink.termio import osc as osc_mod
    with patch.object(osc_mod, "set_clipboard", return_value="\x1b]52;c;FAKE\x07") as setc:
        app._handle_key(KeyPress(key="ctrl+c"))
    setc.assert_called_once()
    
    
    
    assert has_selection(app._app.selection)


def test_escape_with_selection_clears_highlight():
    app = _make_ist_app()
    _attach_minimum_key_state(app)
    from main.ist_core.ink.selection import Point
    app._app.selection.anchor = Point(col=1, row=0)
    app._app.selection.focus = Point(col=5, row=0)
    app._handle_key(KeyPress(key="escape"))
    assert not has_selection(app._app.selection)


def test_ctrl_c_without_selection_falls_through_to_abort_branch():
    """No selection + not loading + first Ctrl+C → message "press ctrl+c
    again to exit". We just want to confirm the fall-through happens."""
    app = _make_ist_app()
    _attach_minimum_key_state(app)
    
    app._last_ctrl_c = 0.0
    app._bridge = None
    transcript_msgs = []

    class _Tr:
        def append_message(self, m): transcript_msgs.append(m)
    app._transcript = _Tr()

    app._handle_key(KeyPress(key="ctrl+c"))
    
    assert not app._app.terminal_writes
    
    assert any("ctrl+c again" in m for m in transcript_msgs)







def test_inkapp_render_hook_calls_overlay_when_selection_present():
    """We can't call InkApp.start() in tests (TTY), but we can verify
    the conditional in _do_render_inner by directly invoking the
    selection helpers and checking screen state changed."""
    from main.ist_core.ink.selection import (
        Point,
        apply_selection_overlay,
    )
    char_pool = CharPool()
    style_pool = StylePool()
    screen = Screen(10, 1, char_pool, style_pool)
    for x, ch in enumerate("hello world"[:10]):
        screen.set_cell(x, 0, char_pool.intern(ch), style_pool.none, 0, CELL_NORMAL)

    sel = SelectionState()
    sel.anchor = Point(col=0, row=0)
    sel.focus = Point(col=4, row=0)

    base_id = screen.get_cell(2, 0).style_id
    apply_selection_overlay(screen, sel, style_pool)
    new_id = screen.get_cell(2, 0).style_id
    assert new_id != base_id
    
    assert screen.get_cell(7, 0).style_id == base_id







def test_footer_set_toast_overrides_status_text():
    from main.ist_core.ink.components.footer import FooterPane
    f = FooterPane()
    f.update(status="ready", tokens_used=0, model="qwen-plus")
    f.set_toast("Copied 12 chars", ttl_seconds=0)
    
    assert "Copied 12 chars" in f._status_line.value
    
    f.set_toast(None)
    assert "Copied 12 chars" not in f._status_line.value


def test_footer_set_toast_search_takes_priority():
    from main.ist_core.ink.components.footer import FooterPane
    f = FooterPane()
    f.set_search_state(query="foo", match="foobar")
    f.set_toast("Copied 1 chars", ttl_seconds=0)
    
    assert "reverse-i-search" in f._status_line.value
