"""Tests for fs_write and fs_edit."""

from __future__ import annotations

import pytest

import main.ist_core.tools.deepagent.file_tools as file_tools


def _setup_sandbox(tmp_path, monkeypatch):
    """Point _PROJECT_ROOT, _AGENT_ROOT, _WORKSPACE_ROOT at a tmp tree."""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    (agent_root / "markdown").mkdir()
    (agent_root / "orgin").mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "inputs").mkdir()
    (workspace / "outputs").mkdir()
    (workspace / "defects").mkdir()
    monkeypatch.setattr(file_tools, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", workspace)
    return agent_root, workspace





class TestWriteFile:
    def test_write_new_file(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_write.invoke(
            {"path": "bug1.md", "content": "# Bug 1\ndetails"}
        )
        assert "wrote" in result
        assert (workspace / "outputs" / "bug1.md").read_text() == "# Bug 1\ndetails"

    def test_write_refuses_overwrite_by_default(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        (workspace / "outputs" / "existing.md").write_text("old")
        result = file_tools.fs_write.invoke(
            {"path": "existing.md", "content": "new"}
        )
        assert "error" in result
        assert "already exists" in result
        assert (workspace / "outputs" / "existing.md").read_text() == "old"

    def test_write_overwrite_true(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        (workspace / "outputs" / "existing.md").write_text("old")
        result = file_tools.fs_write.invoke(
            {"path": "existing.md", "content": "new", "overwrite": True}
        )
        assert "wrote" in result
        assert (workspace / "outputs" / "existing.md").read_text() == "new"

    def test_write_sandbox_traversal(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_write.invoke(
            {"path": "../main/evil.py", "content": "bad"}
        )
        assert "error" in result
        assert "traversal" in result

    def test_write_non_writable_subdir(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_write.invoke(
            {"path": "workspace/inputs/test.txt", "content": "data"}
        )
        assert "error" in result
        assert "not allowed" in result

    def test_write_to_root_rejected(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_write.invoke(
            {"path": "workspace/root.md", "content": "bad"}
        )
        assert "error" in result

    def test_write_content_too_large(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        big = "x" * (1024 * 1024 + 1)
        result = file_tools.fs_write.invoke(
            {"path": "report.md", "content": big}
        )
        assert "error" in result
        assert "too large" in result

    def test_write_binary_suffix_rejected(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_write.invoke(
            {"path": "payload.exe", "content": "data"}
        )
        assert "error" in result
        assert "suffix" in result

    def test_write_no_extension_rejected(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_write.invoke(
            {"path": "noext", "content": "data"}
        )
        assert "error" in result
        assert "extension" in result

    def test_write_parent_not_exist(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_write.invoke(
            {"path": "deep/nested/file.md", "content": "data"}
        )
        assert "wrote" in result
        assert (tmp_path / "workspace" / "outputs" / "deep" / "nested" / "file.md").exists()





class TestEditFile:
    def test_edit_single_replacement(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        (workspace / "outputs" / "bug.md").write_text("hello world")
        result = file_tools.fs_edit.invoke(
            {"path": "bug.md", "old_string": "hello", "new_string": "goodbye"}
        )
        assert "replaced 1" in result
        assert (workspace / "outputs" / "bug.md").read_text() == "goodbye world"

    def test_edit_replace_all(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        (workspace / "outputs" / "doc.md").write_text("foo bar foo baz foo")
        result = file_tools.fs_edit.invoke({
            "path": "doc.md",
            "old_string": "foo",
            "new_string": "qux",
            "replace_all": True,
        })
        assert "replaced 3" in result
        assert (workspace / "outputs" / "doc.md").read_text() == "qux bar qux baz qux"

    def test_edit_uniqueness_check(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        (workspace / "outputs" / "dup.md").write_text("aaa bbb aaa")
        result = file_tools.fs_edit.invoke(
            {"path": "dup.md", "old_string": "aaa", "new_string": "ccc"}
        )
        assert "error" in result
        assert "2 times" in result
        assert (workspace / "outputs" / "dup.md").read_text() == "aaa bbb aaa"

    def test_edit_not_found(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        (workspace / "outputs" / "f.md").write_text("hello")
        result = file_tools.fs_edit.invoke(
            {"path": "f.md", "old_string": "xyz", "new_string": "abc"}
        )
        assert "error" in result
        assert "not found in file" in result

    def test_edit_file_not_exist(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_edit.invoke(
            {"path": "ghost.md", "old_string": "a", "new_string": "b"}
        )
        assert "error" in result
        assert "not found" in result

    def test_edit_same_string_rejected(self, tmp_path, monkeypatch):
        _, workspace = _setup_sandbox(tmp_path, monkeypatch)
        (workspace / "outputs" / "f.md").write_text("hello")
        result = file_tools.fs_edit.invoke(
            {"path": "f.md", "old_string": "hello", "new_string": "hello"}
        )
        assert "error" in result
        assert "identical" in result

    def test_edit_sandbox_denied(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_edit.invoke(
            {"path": "workspace/inputs/doc.md", "old_string": "a", "new_string": "b"}
        )
        assert "error" in result
        assert "not allowed" in result

    def test_edit_traversal_denied(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        result = file_tools.fs_edit.invoke(
            {"path": "../main/x.py", "old_string": "a", "new_string": "b"}
        )
        assert "error" in result
        assert "traversal" in result
