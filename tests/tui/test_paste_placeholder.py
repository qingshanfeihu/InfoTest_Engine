"""Tests for the [Pasted text #N +K lines] placeholder."""

from __future__ import annotations

import re

from main.ist_core.ink.components.prompt_input import PromptInput
from main.ist_core.ink.cursor import CursorManager


def _make_prompt() -> PromptInput:
    return PromptInput(cursor_manager=CursorManager())







def test_short_paste_inserts_verbatim():
    pi = _make_prompt()
    pi.handle_paste("hello world")
    assert pi.value == "hello world"
    
    assert pi._pasted_contents == {}


def test_short_paste_with_few_newlines_uses_marker():
    """Up to PASTE_MAX_LINES (2) newlines stay inline, mapped to ↵."""
    pi = _make_prompt()
    pi.handle_paste("a\nb\nc")
    assert "↵" in pi.value
    assert "[Pasted text" not in pi.value
    assert pi._pasted_contents == {}


def test_long_paste_replaced_by_placeholder():
    pi = _make_prompt()
    big = "x" * 1000
    pi.handle_paste(big)
    assert pi.value == "[Pasted text #1]"
    assert pi._pasted_contents == {1: big}


def test_multi_line_paste_replaced_with_line_count():
    pi = _make_prompt()
    text = "line1\nline2\nline3\nline4"
    pi.handle_paste(text)
    assert pi.value == "[Pasted text #1 +3 lines]"
    assert pi._pasted_contents == {1: text}


def test_paste_normalizes_crlf_to_lf_in_storage():
    pi = _make_prompt()
    text = "a\r\nb\r\nc\r\nd"
    pi.handle_paste(text)
    
    assert pi._pasted_contents[1] == "a\nb\nc\nd"
    
    assert pi.value == "[Pasted text #1 +3 lines]"


def test_paste_ids_are_monotonic():
    pi = _make_prompt()
    pi.handle_paste("x" * 1000)
    pi.handle_paste("y" * 1000)
    assert pi.value == "[Pasted text #1][Pasted text #2]"
    assert pi._pasted_contents == {1: "x" * 1000, 2: "y" * 1000}







def test_expand_pasted_refs_returns_text_unchanged_when_none():
    pi = _make_prompt()
    assert pi.expand_pasted_refs("hello") == "hello"


def test_expand_pasted_refs_replaces_placeholder():
    pi = _make_prompt()
    big = "line1\nline2\nline3\nline4"
    pi.handle_paste(big)
    placeholder = pi.value
    assert placeholder == "[Pasted text #1 +3 lines]"
    expanded = pi.expand_pasted_refs(f"prefix {placeholder} suffix")
    assert expanded == f"prefix {big} suffix"
    
    assert pi._pasted_contents == {1: big}


def test_expand_pasted_refs_handles_multiple_in_order():
    pi = _make_prompt()
    pi.handle_paste("AAA\nAAA\nAAA\nAAA")
    pi.handle_paste("BBB\nBBB\nBBB\nBBB")
    text = f"{pi.value} middle"
    
    expanded = pi.expand_pasted_refs(text)
    assert "AAA\nAAA\nAAA\nAAA" in expanded
    assert "BBB\nBBB\nBBB\nBBB" in expanded


def test_consume_pasted_refs_drops_entries():
    pi = _make_prompt()
    pi.handle_paste("x" * 1000)
    placeholder = pi.value
    out = pi.consume_pasted_refs(placeholder)
    assert out == "x" * 1000
    assert pi._pasted_contents == {}


def test_consume_only_drops_referenced_entries():
    pi = _make_prompt()
    pi.handle_paste("aaa\naaa\naaa\naaa")
    pi.handle_paste("bbb\nbbb\nbbb\nbbb")
    
    text_with_only_id1 = "[Pasted text #1 +3 lines]"
    out = pi.consume_pasted_refs(text_with_only_id1)
    assert out == "aaa\naaa\naaa\naaa"
    
    
    assert pi._pasted_contents == {2: "bbb\nbbb\nbbb\nbbb"}


def test_ctrl_u_clears_pasted_store():
    pi = _make_prompt()
    pi.handle_paste("x" * 1000)
    assert pi._pasted_contents
    pi.handle_key("ctrl+u")
    assert pi.value == ""
    assert pi._pasted_contents == {}







def test_repeat_paste_stacks_placeholders():
    """Pasting the same long content twice yields two distinct
    placeholders. We deliberately do NOT auto-expand or auto-submit:
    the prompt is single-line and inline-expanding multi-line content
    corrupts the render."""
    pi = _make_prompt()
    text = "alpha\nbeta\ngamma\ndelta"
    pi.handle_paste(text)
    pi.handle_paste(text)
    assert pi.value == "[Pasted text #1 +3 lines][Pasted text #2 +3 lines]"
    assert pi.pop_repeat_paste() is None
    assert pi._pasted_contents == {1: text, 2: text}


def test_pop_repeat_paste_always_returns_none():
    pi = _make_prompt()
    pi.handle_paste("a\n" * 10)
    assert pi.pop_repeat_paste() is None
    pi.handle_paste("a\n" * 10)
    assert pi.pop_repeat_paste() is None


def test_paste_with_different_content_stacks():
    pi = _make_prompt()
    a = "a\n" * 10
    b = "b\n" * 10
    pi.handle_paste(a)
    pi.handle_paste(b)
    assert pi.value == "[Pasted text #1 +10 lines][Pasted text #2 +10 lines]"
    assert pi._pasted_contents == {1: a, 2: b}


# ── D10 长输入水平滚动(治长文本溢出污染 footer,2026-07-18 修复轮) ──────────────

def test_d10_horizontal_window_short_text_unchanged():
    """短文本(显示宽≤width)原样返回——正常输入行为不变,不影响非长输入。"""
    from main.ist_core.ink.components.prompt_input import _horizontal_window
    assert _horizontal_window("abc", 3, 20) == ("abc", 3)
    assert _horizontal_window("", 0, 20) == ("", 0)
    assert _horizontal_window("你好世界", 4, 20) == ("你好世界", 8)  # CJK 短文本全显


def test_d10_horizontal_window_long_text_windows_to_width():
    """长文本超 width:窗口显示宽≤width(防溢出),**光标三位置(头/中/尾)都可见**
    (Design 完备性点:锁"光标在哪窗口跟到哪",防窗口只跟末尾致中间光标看不到)。
    "光标可见"判据=col(光标在窗口内列偏移) ∈ [0, 窗口显示宽]。"""
    from main.ist_core.ink.components.prompt_input import _horizontal_window
    from main.ist_core.ink.string_width import string_width
    # 光标在尾:窗口含尾部,光标在窗口末端可见
    disp, col = _horizontal_window("a" * 100, 100, 20)
    assert string_width(disp) <= 20 and disp.endswith("a")
    assert 0 <= col <= string_width(disp), "尾光标须在窗口显示宽内(可见)"
    # 光标在中间:窗口跟随到中间,光标可见
    disp, col = _horizontal_window("b" * 100, 50, 20)
    assert string_width(disp) <= 20
    assert 0 <= col <= string_width(disp), "中间光标须在窗口内(防窗口只跟末尾)"
    # 光标在头:窗口从头,光标在最左可见
    disp, col = _horizontal_window("x" * 100, 0, 20)
    assert col == 0 and string_width(disp) <= 20
    # CJK 光标在中间:宽字符窗口跟随,光标列按显示宽(非字符数)
    disp, col = _horizontal_window("中" * 50, 25, 20)
    assert string_width(disp) <= 20 and 0 <= col <= string_width(disp)


def test_d10_horizontal_window_cjk_no_half_char():
    """CJK 宽字符按显示宽算,窗口不含半个宽字符(否则错位/半字)。"""
    from main.ist_core.ink.components.prompt_input import _horizontal_window
    from main.ist_core.ink.string_width import string_width
    disp, col = _horizontal_window("中" * 50, 50, 20)  # 每字宽2,总宽100
    assert string_width(disp) <= 20
    assert all(string_width(c) == 2 for c in disp), "窗口不得含半个宽字符"
    # 混合 CJK+ASCII
    mix = "abc中文def" * 20
    disp2, _ = _horizontal_window(mix, len(mix), 20)
    assert string_width(disp2) <= 20
