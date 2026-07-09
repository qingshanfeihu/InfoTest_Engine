"""Unit tests for the selection engine.

Tests target pure logic (no real terminal / Output / Layout). Each test
constructs a small Screen + StylePool and exercises selection state.
"""

from __future__ import annotations

import os
import sys

import pytest

from main.ist_core.ink.screen import (
    CELL_NORMAL,
    CELL_SPACER,
    CELL_WIDE,
    CharPool,
    Screen,
    StylePool,
    set_cell_style_id,
)
from main.ist_core.ink.selection import (
    AnchorSpan,
    Point,
    SelectionState,
    apply_selection_overlay,
    capture_scrolled_rows,
    clear_selection,
    extend_selection,
    finish_selection,
    get_selected_text,
    has_selection,
    is_cell_selected,
    move_focus,
    select_line_at,
    select_word_at,
    selection_bounds,
    shift_anchor,
    shift_selection,
    shift_selection_for_follow,
    start_selection,
    update_selection,
)







def _make_screen(text_rows: list[str], width: int | None = None) -> tuple[Screen, StylePool, CharPool]:
    """Build a tiny Screen filled with the given text rows."""
    char_pool = CharPool()
    style_pool = StylePool()
    if width is None:
        width = max(len(r) for r in text_rows) if text_rows else 1
    height = len(text_rows)
    screen = Screen(width, height, char_pool, style_pool)
    for y, row in enumerate(text_rows):
        for x, ch in enumerate(row):
            screen.set_cell(x, y, char_pool.intern(ch), style_pool.none, 0, CELL_NORMAL)
    return screen, style_pool, char_pool







def test_start_selection_clears_focus():
    s = SelectionState()
    start_selection(s, col=4, row=2)
    assert s.anchor == Point(col=4, row=2)
    assert s.focus is None
    assert s.is_dragging is True
    assert has_selection(s) is False


def test_update_selection_noop_at_anchor():
    s = SelectionState()
    start_selection(s, col=4, row=2)
    update_selection(s, col=4, row=2)
    assert s.focus is None
    update_selection(s, col=5, row=2)
    assert s.focus == Point(col=5, row=2)


def test_finish_selection_keeps_anchor_focus():
    s = SelectionState()
    start_selection(s, col=4, row=2)
    update_selection(s, col=10, row=2)
    finish_selection(s)
    assert s.is_dragging is False
    assert s.anchor is not None and s.focus is not None


def test_clear_resets_everything():
    s = SelectionState()
    start_selection(s, col=4, row=2)
    update_selection(s, col=10, row=2)
    s.scrolled_off_above.append("foo")
    s.scrolled_off_above_sw.append(False)
    clear_selection(s)
    assert not has_selection(s)
    assert s.scrolled_off_above == []
    assert s.scrolled_off_above_sw == []







def test_selection_bounds_normalizes_reading_order():
    s = SelectionState()
    s.anchor = Point(col=8, row=4)
    s.focus = Point(col=2, row=1)
    b = selection_bounds(s)
    assert b is not None
    start, end = b
    assert start == Point(col=2, row=1)
    assert end == Point(col=8, row=4)


def test_is_cell_selected_corners():
    s = SelectionState()
    s.anchor = Point(col=2, row=1)
    s.focus = Point(col=8, row=3)
    assert is_cell_selected(s, 2, 1) is True
    assert is_cell_selected(s, 1, 1) is False
    assert is_cell_selected(s, 0, 2) is True
    assert is_cell_selected(s, 8, 3) is True
    assert is_cell_selected(s, 9, 3) is False
    assert is_cell_selected(s, 0, 4) is False


def test_has_selection_false_until_focus_set():
    s = SelectionState()
    start_selection(s, 5, 5)
    assert has_selection(s) is False
    update_selection(s, 6, 5)
    assert has_selection(s) is True







def test_word_bounds_letter_run():
    """`hello world` — clicking col=2 should select cols 0..4 (`hello`)."""
    screen, _, _ = _make_screen(["hello world"])
    select_word_at(SelectionState(), screen, 2, 0)
    s = SelectionState()
    select_word_at(s, screen, 2, 0)
    assert s.anchor == Point(col=0, row=0)
    assert s.focus == Point(col=4, row=0)
    assert s.anchor_span is not None
    assert s.anchor_span.kind == "word"


def test_word_bounds_includes_underscore_and_dash():
    """`qa_search-tool` is one word (iTerm2 default class includes _ and -)."""
    screen, _, _ = _make_screen(["  qa_search-tool  "])
    s = SelectionState()
    select_word_at(s, screen, 5, 0)
    assert s.anchor == Point(col=2, row=0)
    assert s.focus == Point(col=15, row=0)


def test_word_bounds_skips_spacer_tail():
    """Wide-char head followed by a SpacerTail should be treated as one word."""
    char_pool = CharPool()
    style_pool = StylePool()
    screen = Screen(6, 1, char_pool, style_pool)
    
    screen.set_cell(0, 0, char_pool.intern("中"), style_pool.none, 0, CELL_WIDE)
    screen.set_cell(1, 0, char_pool.intern(""), style_pool.none, 0, CELL_SPACER)
    screen.set_cell(2, 0, char_pool.intern("文"), style_pool.none, 0, CELL_WIDE)
    screen.set_cell(3, 0, char_pool.intern(""), style_pool.none, 0, CELL_SPACER)
    screen.set_cell(4, 0, char_pool.intern(" "), style_pool.none, 0, CELL_NORMAL)
    s = SelectionState()
    
    select_word_at(s, screen, 1, 0)
    assert s.anchor == Point(col=0, row=0)
    assert s.focus == Point(col=3, row=0)


def test_word_bounds_returns_none_on_no_select():
    screen, _, _ = _make_screen(["  hello"])
    screen.mark_no_select(2, 0, 6, 0)
    s = SelectionState()
    select_word_at(s, screen, 4, 0)
    assert s.anchor is None


def test_select_line_full_width():
    screen, _, _ = _make_screen(["hello"])
    s = SelectionState()
    select_line_at(s, screen, 0)
    assert s.anchor == Point(col=0, row=0)
    assert s.focus == Point(col=screen.width - 1, row=0)
    assert s.anchor_span is not None and s.anchor_span.kind == "line"







def test_extend_selection_word_forward():
    screen, _, _ = _make_screen(["hello world  foo"])
    s = SelectionState()
    select_word_at(s, screen, 2, 0)
    extend_selection(s, screen, 14, 0)
    assert s.anchor == Point(col=0, row=0)
    assert s.focus == Point(col=15, row=0)


def test_extend_selection_word_backward():
    screen, _, _ = _make_screen(["foo hello world"])
    s = SelectionState()
    select_word_at(s, screen, 7, 0)
    extend_selection(s, screen, 1, 0)
    assert s.anchor == Point(col=8, row=0)
    assert s.focus == Point(col=0, row=0)


def test_extend_selection_overlap_returns_anchor_span():
    screen, _, _ = _make_screen(["hello world"])
    s = SelectionState()
    select_word_at(s, screen, 2, 0)
    extend_selection(s, screen, 3, 0)
    assert s.anchor == Point(col=0, row=0)
    assert s.focus == Point(col=4, row=0)







def test_get_selected_text_single_row():
    screen, _, _ = _make_screen(["hello world"])
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=4, row=0)
    assert get_selected_text(s, screen) == "hello"


def test_get_selected_text_trims_trailing_whitespace():
    """End of a logical line — trailing spaces are dropped."""
    screen, _, _ = _make_screen(["hello     "])
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=9, row=0)
    assert get_selected_text(s, screen) == "hello"


def test_get_selected_text_joins_soft_wrap():
    screen, _, _ = _make_screen(["the quick ", "brown fox "], width=10)
    
    screen.set_soft_wrap_continuation(1, 10)
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=8, row=1)
    text = get_selected_text(s, screen)
    
    
    assert text == "the quick brown fox"


def test_get_selected_text_multi_row_with_newlines():
    screen, _, _ = _make_screen(["line1", "line2", "line3"])
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=4, row=2)
    assert get_selected_text(s, screen) == "line1\nline2\nline3"


def test_get_selected_text_skips_no_select():
    screen, _, _ = _make_screen([" |hello"])
    screen.mark_no_select(0, 0, 1, 0)
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=6, row=0)
    assert get_selected_text(s, screen) == "hello"







def test_apply_selection_overlay_changes_style_id():
    screen, style_pool, _ = _make_screen(["hello world"])
    base = screen.get_cell(2, 0).style_id
    s = SelectionState()
    s.anchor = Point(col=2, row=0)
    s.focus = Point(col=6, row=0)
    apply_selection_overlay(screen, s, style_pool)
    inside = screen.get_cell(4, 0).style_id
    outside = screen.get_cell(0, 0).style_id
    assert inside != base
    assert outside == base
    assert inside == style_pool.with_selection_bg(base)


def test_apply_selection_overlay_skips_no_select():
    screen, style_pool, _ = _make_screen([" |hello"])
    screen.mark_no_select(0, 0, 1, 0)
    base = screen.get_cell(0, 0).style_id
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=6, row=0)
    apply_selection_overlay(screen, s, style_pool)
    assert screen.get_cell(0, 0).style_id == base
    assert screen.get_cell(4, 0).style_id != base


def test_apply_selection_overlay_idempotent():
    """Re-applying the same selection shouldn't double-stack bg codes."""
    screen, style_pool, _ = _make_screen(["xxxxx"])
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=4, row=0)
    apply_selection_overlay(screen, s, style_pool)
    once = screen.get_cell(2, 0).style_id
    apply_selection_overlay(screen, s, style_pool)
    twice = screen.get_cell(2, 0).style_id
    
    
    
    
    once_codes = style_pool.get(once)
    twice_codes = style_pool.get(twice)
    assert "\x1b[48;5;238m" in once_codes
    
    assert sum(1 for c in twice_codes if c == "\x1b[48;5;238m") == 1







def test_capture_scrolled_rows_above_appends_and_resets_anchor_col():
    screen, _, _ = _make_screen(["row0      ", "row1      ", "row2      "], width=10)
    s = SelectionState()
    s.anchor = Point(col=2, row=0)
    s.focus = Point(col=4, row=2)
    capture_scrolled_rows(s, screen, 0, 0, side="above")
    assert s.scrolled_off_above == ["w0"]
    
    assert s.anchor == Point(col=0, row=0)


def test_capture_scrolled_rows_below_prepends():
    screen, _, _ = _make_screen(["row0      ", "row1      ", "row2      "], width=10)
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=2, row=2)
    capture_scrolled_rows(s, screen, 2, 2, side="below")
    assert s.scrolled_off_below == ["row"]
    
    
    
    assert s.anchor == Point(col=0, row=0)







def test_shift_selection_clears_when_both_overshoot_above():
    s = SelectionState()
    s.anchor = Point(col=0, row=1)
    s.focus = Point(col=5, row=2)
    shift_selection(s, d_row=-5, min_row=0, max_row=10, width=10)
    assert not has_selection(s)


def test_shift_selection_tracks_virtual_row_for_round_trip():
    s = SelectionState()
    s.anchor = Point(col=0, row=1)
    s.focus = Point(col=5, row=4)
    
    shift_selection(s, d_row=-3, min_row=0, max_row=10, width=10)
    assert s.anchor == Point(col=0, row=0)
    assert s.virtual_anchor_row == -2
    assert s.focus == Point(col=5, row=1)
    
    shift_selection(s, d_row=3, min_row=0, max_row=10, width=10)
    assert s.anchor == Point(col=0, row=1)
    assert s.virtual_anchor_row is None


def test_shift_anchor_only_moves_anchor():
    s = SelectionState()
    s.anchor = Point(col=2, row=5)
    s.focus = Point(col=7, row=8)
    shift_anchor(s, d_row=-2, min_row=0, max_row=10)
    assert s.anchor == Point(col=2, row=3)
    assert s.focus == Point(col=7, row=8)


def test_shift_selection_for_follow_clears_when_both_above_top():
    s = SelectionState()
    s.anchor = Point(col=0, row=0)
    s.focus = Point(col=5, row=1)
    cleared = shift_selection_for_follow(s, d_row=-5, min_row=0, max_row=10)
    assert cleared is True
    assert not has_selection(s)


def test_move_focus_drops_anchor_span_to_char_mode():
    screen, _, _ = _make_screen(["hello world"])
    s = SelectionState()
    select_word_at(s, screen, 2, 0)
    assert s.anchor_span is not None
    move_focus(s, 7, 0)
    assert s.anchor_span is None
    assert s.focus == Point(col=7, row=0)


def test_scroll_capture_shift_preserve_partial_offscreen_and_round_trip():
    """滚动时 capture_scrolled_rows + shift_selection 组合的端到端语义:
    选区随内容平移、滚出视口顶部的那截经累加器保留(复制文本不变)、反向滚回弹出
    累加器完全复原。复刻 IstInkApp._shift_selection_for_scroll 对引擎的调用序列。"""
    width = 10
    min_row, max_row = 0, 4
    f0 = ["AAAA      ", "BBBB      ", "CCCC      ", "DDDD      ", "EEEE      "]
    screen0, _, _ = _make_screen(f0, width=width)

    s = SelectionState()
    s.anchor = Point(col=0, row=1)
    s.focus = Point(col=3, row=3)
    assert get_selected_text(s, screen0) == "BBBB\nCCCC\nDDDD"

    # —— 向下滚 2 行(内容上移):顶部 [0,1] 移出上沿,d_row=-2 ——
    capture_scrolled_rows(s, screen0, min_row, min_row + 2 - 1, side="above")
    shift_selection(s, d_row=-2, min_row=min_row, max_row=max_row, width=width)
    assert s.scrolled_off_above == ["BBBB"]
    assert selection_bounds(s) == (Point(col=0, row=0), Point(col=3, row=1))

    # 重绘后 F1:内容整体上移 2 行。滚出的 BBBB 由累加器补回,屏内 CCCC/DDDD 仍正确选中。
    f1 = ["CCCC      ", "DDDD      ", "EEEE      ", "FFFF      ", "GGGG      "]
    screen1, _, _ = _make_screen(f1, width=width)
    assert get_selected_text(s, screen1) == "BBBB\nCCCC\nDDDD"

    # —— 反向滚回 2 行(内容下移):底部 [3,4] 移出下沿(与选区不相交),d_row=+2 ——
    capture_scrolled_rows(s, screen1, max_row - 2 + 1, max_row, side="below")
    shift_selection(s, d_row=2, min_row=min_row, max_row=max_row, width=width)
    assert s.scrolled_off_above == []  # BBBB 回到屏内,弹出累加器
    assert s.scrolled_off_below == []
    assert selection_bounds(s) == (Point(col=0, row=1), Point(col=3, row=3))
    assert get_selected_text(s, screen0) == "BBBB\nCCCC\nDDDD"







def test_screen_no_select_marker():
    screen, _, _ = _make_screen(["xxx"])
    assert screen.is_no_select(1, 0) is False
    screen.mark_no_select(0, 0, 2, 0)
    assert all(screen.is_no_select(x, 0) for x in range(3))


def test_screen_soft_wrap_starts_at_default_zero():
    screen, _, _ = _make_screen(["x", "x"])
    assert screen.soft_wrap_starts_at == [0, 0]
    screen.set_soft_wrap_continuation(1, 5)
    assert screen.soft_wrap_starts_at[1] == 5


def test_screen_reset_clears_no_select_and_soft_wrap():
    screen, _, _ = _make_screen(["xxx"])
    screen.mark_no_select(0, 0, 2, 0)
    screen.set_soft_wrap_continuation(0, 3)
    screen.reset()
    assert screen.soft_wrap_starts_at == [0]
    assert screen.is_no_select(0, 0) is False







def test_with_selection_bg_replaces_existing_bg():
    sp = StylePool()
    base = sp.intern(["\x1b[48;5;100m", "\x1b[31m"])
    new_id = sp.with_selection_bg(base)
    codes = sp.get(new_id)
    assert "\x1b[48;5;100m" not in codes
    assert "\x1b[48;5;238m" in codes
    assert "\x1b[31m" in codes


def test_with_selection_bg_strips_inverse():
    sp = StylePool()
    base = sp.intern(["\x1b[7m", "\x1b[31m"])
    new_id = sp.with_selection_bg(base)
    codes = sp.get(new_id)
    assert "\x1b[7m" not in codes
    assert "\x1b[48;5;238m" in codes


def test_with_selection_bg_caches_by_base_id():
    sp = StylePool()
    base = sp.intern(["\x1b[31m"])
    a = sp.with_selection_bg(base)
    b = sp.with_selection_bg(base)
    assert a == b


def test_set_cell_style_id_only_changes_style():
    char_pool = CharPool()
    sp = StylePool()
    screen = Screen(3, 1, char_pool, sp)
    screen.set_cell(1, 0, char_pool.intern("x"), sp.none, 0, CELL_NORMAL)
    new_style = sp.intern(["\x1b[1m"])
    set_cell_style_id(screen, 1, 0, new_style)
    cell = screen.get_cell(1, 0)
    assert cell.style_id == new_style
    assert char_pool.get(cell.char_id) == "x"
