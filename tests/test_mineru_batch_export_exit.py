"""mineru_batch_export 退出码与分批 helper 测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from main.mineru_batch_export import (
    FileOutcome,
    _chunk_paths,
    _is_success,
    _mineru_batch_size,
    _should_exit_error,
)


def test_is_success_done_with_json():
    o = FileOutcome(
        source="a.pdf",
        stem="a",
        state="done",
        code_format_path="/tmp/a.code_format.json",
    )
    assert _is_success(o) is True


def test_is_success_cached_with_markdown():
    o = FileOutcome(
        source="b.docx",
        stem="b",
        state="cached",
        markdown_path="/tmp/b.md",
    )
    assert _is_success(o) is True


def test_is_success_cached_without_markdown():
    o = FileOutcome(source="b.docx", stem="b", state="cached")
    assert _is_success(o) is False


def test_should_exit_error_all_cached_ok():
    outcomes = [
        FileOutcome(source="x", stem="x", state="cached", markdown_path="/m/x.md"),
    ]
    assert _should_exit_error(outcomes) is False


def test_should_exit_error_with_failed():
    outcomes = [
        FileOutcome(source="x", stem="x", state="cached", markdown_path="/m/x.md"),
        FileOutcome(source="y", stem="y", state="failed", err_msg="api"),
    ]
    assert _should_exit_error(outcomes) is True


def test_should_exit_error_empty():
    assert _should_exit_error([]) is True


def test_chunk_paths():
    paths = [Path(f"f{i}.pdf") for i in range(5)]
    chunks = _chunk_paths(paths, 2)
    assert len(chunks) == 3
    assert len(chunks[0]) == 2
    assert len(chunks[-1]) == 1


def test_mineru_batch_size_default():
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("MINERU_BATCH_SIZE", None)
        assert _mineru_batch_size() == 30


def test_mineru_batch_size_env():
    with patch.dict("os.environ", {"MINERU_BATCH_SIZE": "7"}):
        assert _mineru_batch_size() == 7
