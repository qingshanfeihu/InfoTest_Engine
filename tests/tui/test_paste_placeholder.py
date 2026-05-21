"""Tests for the cc-haha-style [Pasted text #N +K lines] placeholder."""

from __future__ import annotations

import re

from main.qa_agent.ink.components.prompt_input import PromptInput
from main.qa_agent.ink.cursor import CursorManager


def _make_prompt() -> PromptInput:
    return PromptInput(cursor_manager=CursorManager())


# ---------------------------------------------------------------------------
# Threshold behavior
# ---------------------------------------------------------------------------


def test_short_paste_inserts_verbatim():
    pi = _make_prompt()
    pi.handle_paste("hello world")
    assert pi.value == "hello world"
    # No placeholder created.
    assert pi._pasted_contents == {}


def test_short_paste_with_few_newlines_uses_marker():
    """Up to PASTE_MAX_LINES (2) newlines stay inline, mapped to ↵."""
    pi = _make_prompt()
    pi.handle_paste("a\nb\nc")  # 2 newlines, exactly at the boundary
    assert "↵" in pi.value
    assert "[Pasted text" not in pi.value
    assert pi._pasted_contents == {}


def test_long_paste_replaced_by_placeholder():
    pi = _make_prompt()
    big = "x" * 1000  # > PASTE_THRESHOLD (800)
    pi.handle_paste(big)
    assert pi.value == "[Pasted text #1]"  # 0 newlines → no "+K lines" suffix
    assert pi._pasted_contents == {1: big}


def test_multi_line_paste_replaced_with_line_count():
    pi = _make_prompt()
    text = "line1\nline2\nline3\nline4"  # 3 newlines > 2
    pi.handle_paste(text)
    assert pi.value == "[Pasted text #1 +3 lines]"
    assert pi._pasted_contents == {1: text}


def test_paste_normalizes_crlf_to_lf_in_storage():
    pi = _make_prompt()
    text = "a\r\nb\r\nc\r\nd"
    pi.handle_paste(text)
    # Stored as LF-only.
    assert pi._pasted_contents[1] == "a\nb\nc\nd"
    # Placeholder counts the 3 logical newlines.
    assert pi.value == "[Pasted text #1 +3 lines]"


def test_paste_ids_are_monotonic():
    pi = _make_prompt()
    pi.handle_paste("x" * 1000)
    pi.handle_paste("y" * 1000)
    assert pi.value == "[Pasted text #1][Pasted text #2]"
    assert pi._pasted_contents == {1: "x" * 1000, 2: "y" * 1000}


# ---------------------------------------------------------------------------
# expand / consume
# ---------------------------------------------------------------------------


def test_expand_pasted_refs_returns_text_unchanged_when_none():
    pi = _make_prompt()
    assert pi.expand_pasted_refs("hello") == "hello"


def test_expand_pasted_refs_replaces_placeholder():
    pi = _make_prompt()
    big = "line1\nline2\nline3\nline4"  # 3 newlines > PASTE_MAX_LINES (2)
    pi.handle_paste(big)
    placeholder = pi.value
    assert placeholder == "[Pasted text #1 +3 lines]"
    expanded = pi.expand_pasted_refs(f"prefix {placeholder} suffix")
    assert expanded == f"prefix {big} suffix"
    # expand keeps the entry alive (idempotent reads).
    assert pi._pasted_contents == {1: big}


def test_expand_pasted_refs_handles_multiple_in_order():
    pi = _make_prompt()
    pi.handle_paste("AAA\nAAA\nAAA\nAAA")  # id=1
    pi.handle_paste("BBB\nBBB\nBBB\nBBB")  # id=2
    text = f"{pi.value} middle"
    # text now has both placeholders ordered #1 then #2; expand restores both.
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
    pi.handle_paste("aaa\naaa\naaa\naaa")  # id=1
    pi.handle_paste("bbb\nbbb\nbbb\nbbb")  # id=2
    # User edits the prompt down to just one placeholder before submit.
    text_with_only_id1 = "[Pasted text #1 +3 lines]"
    out = pi.consume_pasted_refs(text_with_only_id1)
    assert out == "aaa\naaa\naaa\naaa"
    # id=2 still in the store (still referenced elsewhere — at least in
    # principle; the unreferenced cleanup is left for the caller).
    assert pi._pasted_contents == {2: "bbb\nbbb\nbbb\nbbb"}


def test_ctrl_u_clears_pasted_store():
    pi = _make_prompt()
    pi.handle_paste("x" * 1000)
    assert pi._pasted_contents
    pi.handle_key("ctrl+u")
    assert pi.value == ""
    assert pi._pasted_contents == {}


# ---------------------------------------------------------------------------
# Repeat-paste behavior — placeholders simply stack
# ---------------------------------------------------------------------------


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
