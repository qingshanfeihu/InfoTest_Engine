"""Tests for qa_deepagent_write_file and qa_deepagent_edit_file."""

from __future__ import annotations

import pytest

import main.qa_agent.tools.deepagent.file_tools as file_tools


def _setup_sandbox(tmp_path, monkeypatch):
    """Point _PROJECT_ROOT and _AGENT_ROOT at a tmp tree with writable subdirs."""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    (agent_root / "defects").mkdir()
    (agent_root / "markdown").mkdir()
    (agent_root / "baselines").mkdir()
    (agent_root / "reports").mkdir()
    (agent_root / "orgin").mkdir()
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    return agent_root


# --- write_file tests ---


class TestWriteFile:
    def test_write_new_file(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "defects/bug1.md", "content": "# Bug 1\ndetails"}
        )
        assert "wrote" in result
        assert (agent_root / "defects" / "bug1.md").read_text() == "# Bug 1\ndetails"

    def test_write_refuses_overwrite_by_default(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        (agent_root / "defects" / "existing.md").write_text("old")
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "defects/existing.md", "content": "new"}
        )
        assert "error" in result
        assert "already exists" in result
        assert (agent_root / "defects" / "existing.md").read_text() == "old"

    def test_write_overwrite_true(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        (agent_root / "defects" / "existing.md").write_text("old")
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "defects/existing.md", "content": "new", "overwrite": True}
        )
        assert "wrote" in result
        assert (agent_root / "defects" / "existing.md").read_text() == "new"

    def test_write_sandbox_traversal(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "../main/evil.py", "content": "bad"}
        )
        assert "error" in result
        assert "traversal" in result

    def test_write_non_writable_subdir(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "orgin/test.txt", "content": "data"}
        )
        assert "error" in result
        assert "not allowed" in result

    def test_write_to_root_rejected(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": ".", "content": "bad"}
        )
        assert "error" in result

    def test_write_content_too_large(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        big = "x" * (1024 * 1024 + 1)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "defects/big.md", "content": big}
        )
        assert "error" in result
        assert "too large" in result

    def test_write_binary_suffix_rejected(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "defects/payload.exe", "content": "data"}
        )
        assert "error" in result
        assert "suffix" in result

    def test_write_no_extension_rejected(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "defects/noext", "content": "data"}
        )
        assert "error" in result
        assert "extension" in result

    def test_write_parent_not_exist(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_write_file.invoke(
            {"path": "defects/deep/nested/file.md", "content": "data"}
        )
        assert "error" in result
        assert "parent directory" in result


# --- edit_file tests ---


class TestEditFile:
    def test_edit_single_replacement(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        (agent_root / "defects" / "bug.md").write_text("hello world")
        result = file_tools.qa_deepagent_edit_file.invoke(
            {"path": "defects/bug.md", "old_string": "hello", "new_string": "goodbye"}
        )
        assert "replaced 1" in result
        assert (agent_root / "defects" / "bug.md").read_text() == "goodbye world"

    def test_edit_replace_all(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        (agent_root / "markdown" / "doc.md").write_text("foo bar foo baz foo")
        result = file_tools.qa_deepagent_edit_file.invoke({
            "path": "markdown/doc.md",
            "old_string": "foo",
            "new_string": "qux",
            "replace_all": True,
        })
        assert "replaced 3" in result
        assert (agent_root / "markdown" / "doc.md").read_text() == "qux bar qux baz qux"

    def test_edit_uniqueness_check(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        (agent_root / "defects" / "dup.md").write_text("aaa bbb aaa")
        result = file_tools.qa_deepagent_edit_file.invoke(
            {"path": "defects/dup.md", "old_string": "aaa", "new_string": "ccc"}
        )
        assert "error" in result
        assert "2 times" in result
        assert (agent_root / "defects" / "dup.md").read_text() == "aaa bbb aaa"

    def test_edit_not_found(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        (agent_root / "defects" / "f.md").write_text("hello")
        result = file_tools.qa_deepagent_edit_file.invoke(
            {"path": "defects/f.md", "old_string": "xyz", "new_string": "abc"}
        )
        assert "error" in result
        assert "not found in file" in result

    def test_edit_file_not_exist(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_edit_file.invoke(
            {"path": "defects/ghost.md", "old_string": "a", "new_string": "b"}
        )
        assert "error" in result
        assert "not found" in result

    def test_edit_same_string_rejected(self, tmp_path, monkeypatch):
        agent_root = _setup_sandbox(tmp_path, monkeypatch)
        (agent_root / "defects" / "f.md").write_text("hello")
        result = file_tools.qa_deepagent_edit_file.invoke(
            {"path": "defects/f.md", "old_string": "hello", "new_string": "hello"}
        )
        assert "error" in result
        assert "identical" in result

    def test_edit_sandbox_denied(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_edit_file.invoke(
            {"path": "orgin/doc.md", "old_string": "a", "new_string": "b"}
        )
        assert "error" in result
        assert "not allowed" in result

    def test_edit_traversal_denied(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.qa_deepagent_edit_file.invoke(
            {"path": "../main/x.py", "old_string": "a", "new_string": "b"}
        )
        assert "error" in result
        assert "traversal" in result
