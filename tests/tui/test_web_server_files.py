"""web_server /api/files 回归 —— 隐藏文件（.gitkeep 等）不作为可下载产物列出。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import main.ist_core.web_server as ws


def test_list_files_skips_dotfiles(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / ".gitkeep").write_text("", encoding="utf-8")
    (outputs / ".DS_Store").write_text("x", encoding="utf-8")
    (outputs / "report.md").write_text("hello", encoding="utf-8")
    (outputs / "评审.md").write_text("内容", encoding="utf-8")

    monkeypatch.setattr(ws, "_OUTPUTS", outputs)
    monkeypatch.setattr(ws, "_resolve_session", lambda token: {"username": "test"})

    result = asyncio.run(ws.list_files(token="dummy"))
    names = {f["name"] for f in result["files"]}

    assert ".gitkeep" not in names
    assert ".DS_Store" not in names
    assert names == {"report.md", "评审.md"}


def test_list_files_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "_OUTPUTS", tmp_path / "nonexistent")
    monkeypatch.setattr(ws, "_resolve_session", lambda token: {"username": "test"})
    result = asyncio.run(ws.list_files(token="dummy"))
    assert result == {"files": []}
