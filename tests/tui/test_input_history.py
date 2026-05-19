"""Tests for InputHistory: ↑↓ navigation + Ctrl+R search."""

from __future__ import annotations

from pathlib import Path

import pytest

from main.qa_agent.tui.input_history import InputHistory


@pytest.fixture
def hist(tmp_path: Path) -> InputHistory:
    return InputHistory(path=tmp_path / "history", max_items=100)


# ---------------------------------------------------------------------------
# Add + persistence
# ---------------------------------------------------------------------------


def test_add_persists_to_disk(hist, tmp_path):
    hist.add("first")
    hist.add("second")
    persisted = (tmp_path / "history").read_text(encoding="utf-8")
    assert "first" in persisted
    assert "second" in persisted


def test_add_skips_empty_and_dedupe_consecutive(hist):
    hist.add("foo")
    hist.add("foo")  # dedupe consecutive
    hist.add("")
    hist.add("   ")
    hist.add("foo")  # 与最近的 "foo" 相同 -> 仍然 dedupe（bash 风格）
    assert hist.items == ["foo"]


def test_add_keeps_distinct_after_empty(hist):
    hist.add("foo")
    hist.add("")  # 跳过
    hist.add("bar")
    hist.add("foo")  # 与最近的 "bar" 不同 -> 加入
    assert hist.items == ["foo", "bar", "foo"]


def test_add_caps_at_max_items(tmp_path):
    h = InputHistory(path=tmp_path / "h", max_items=3)
    for i in range(10):
        h.add(f"q{i}")
    assert len(h) == 3
    assert h.items == ["q7", "q8", "q9"]


def test_load_from_existing_file(tmp_path):
    p = tmp_path / "h"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    h = InputHistory(path=p)
    assert h.items == ["a", "b", "c"]


def test_load_handles_missing_file(tmp_path):
    h = InputHistory(path=tmp_path / "nonexistent")
    assert h.items == []


# ---------------------------------------------------------------------------
# Up / Down navigation
# ---------------------------------------------------------------------------


def test_up_returns_most_recent_first(hist):
    hist.add("a")
    hist.add("b")
    hist.add("c")
    assert hist.up("draft") == "c"
    assert hist.up("draft") == "b"
    assert hist.up("draft") == "a"


def test_up_at_oldest_stays(hist):
    hist.add("a")
    assert hist.up("draft") == "a"
    assert hist.up("draft") == "a"


def test_down_returns_to_draft_at_end(hist):
    hist.add("a")
    hist.add("b")
    hist.up("my-draft")  # cursor -> "b"
    hist.up("my-draft")  # cursor -> "a"
    assert hist.down("my-draft") == "b"  # back forward
    assert hist.down("my-draft") == "my-draft"  # restore draft
    # 再 ↓ 一次：超出，仍是 draft
    assert hist.down("my-draft") is None


def test_up_records_draft_on_first_press(hist):
    hist.add("a")
    out = hist.up("currently typing")
    assert out == "a"
    # ↓ 应回到 "currently typing"
    assert hist.down("ignored") == "currently typing"


def test_up_when_empty_returns_none(hist):
    assert hist.up("draft") is None


def test_reset_navigation_clears_cursor(hist):
    hist.add("a")
    hist.up("draft")
    hist.reset_navigation()
    # After reset, ↑ 重新记录新 draft
    assert hist.up("new-draft") == "a"


# ---------------------------------------------------------------------------
# Ctrl+R search
# ---------------------------------------------------------------------------


def test_start_search_finds_match(hist):
    hist.add("hello world")
    hist.add("foo bar")
    hist.add("hello universe")
    out = hist.start_search("hello")
    assert hist.in_search_mode
    assert "hello" in (out or "").lower()


def test_search_cycles_through_matches(hist):
    hist.add("apple pie")
    hist.add("banana")
    hist.add("apple tart")
    hist.start_search("apple")
    first = hist.search_next()
    second = hist.search_next()
    third = hist.search_next()
    # cycle 回第一个
    assert first != second
    assert "apple" in (first or "").lower() and "apple" in (second or "").lower()
    assert third == first  # cycle back


def test_search_no_matches_returns_none(hist):
    hist.add("foo")
    hist.add("bar")
    out = hist.start_search("zzz")
    assert out is None
    assert hist.in_search_mode


def test_update_search_query_refilters(hist):
    hist.add("foo apple")
    hist.add("foo banana")
    hist.start_search("foo")
    hist.update_search_query("apple")
    assert hist.search_query == "apple"
    # 切换 query 后应能找到 apple
    hist.search_next()


def test_exit_search_restores_draft(hist):
    hist.add("history-item")
    hist.start_search("history")
    restored = hist.exit_search(restore=True)
    assert restored == "history"  # 进搜索前的 draft 是 "history"
    assert not hist.in_search_mode


def test_search_case_insensitive(hist):
    hist.add("Hello World")
    out = hist.start_search("hello")
    assert "Hello" in (out or "")


# ---------------------------------------------------------------------------
# Persistence across instances
# ---------------------------------------------------------------------------


def test_persistence_survives_new_instance(tmp_path):
    p = tmp_path / "h"
    h1 = InputHistory(path=p)
    h1.add("persist-me")
    h2 = InputHistory(path=p)
    assert "persist-me" in h2.items
