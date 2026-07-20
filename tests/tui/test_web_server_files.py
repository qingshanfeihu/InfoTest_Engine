"""web_server /api/files 回归 —— 树结构列出 + 隐藏文件过滤。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import main.ist_core.web_server as ws


def _patch_user_dir(monkeypatch, tmp_path: Path, dirname: str = "test"):
    """绕过登录校验，直接指向临时用户目录。"""
    user_dir = tmp_path / dirname
    user_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ws, "_get_user_outputs_dir", lambda sid, tok: user_dir)
    return user_dir


def test_list_files_skips_dotfiles(tmp_path, monkeypatch):
    user_dir = _patch_user_dir(monkeypatch, tmp_path)
    (user_dir / ".gitkeep").write_text("", encoding="utf-8")
    (user_dir / ".DS_Store").write_text("x", encoding="utf-8")
    (user_dir / "report.md").write_text("hello", encoding="utf-8")
    (user_dir / "评审.md").write_text("内容", encoding="utf-8")

    result = asyncio.run(ws.list_files(token="dummy"))
    names = {f["name"] for f in result["files"]}

    assert ".gitkeep" not in names
    assert ".DS_Store" not in names
    assert names == {"report.md", "评审.md"}


def test_list_files_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ws, "_get_user_outputs_dir", lambda sid, tok: tmp_path / "nonexistent")
    result = asyncio.run(ws.list_files(token="dummy"))
    assert result == {"files": []}


def test_list_files_tree_structure(tmp_path, monkeypatch):
    """子目录应作为树节点展开，空目录不列出。"""
    user_dir = _patch_user_dir(monkeypatch, tmp_path)
    batch = user_dir / "batch1"
    batch.mkdir()
    (batch / "case.xlsx").write_bytes(b"\x00")
    (batch / "report.md").write_text("ok", encoding="utf-8")
    empty_dir = user_dir / "empty_sub"
    empty_dir.mkdir()

    result = asyncio.run(ws.list_files(token="dummy"))
    files = result["files"]

    # 根目录只有 batch1 目录节点（empty_sub 因为空被跳过）
    assert len(files) == 1
    assert files[0]["type"] == "dir"
    assert files[0]["name"] == "batch1"
    assert len(files[0]["children"]) == 2

    child_names = {c["name"] for c in files[0]["children"]}
    assert child_names == {"case.xlsx", "report.md"}

    # 子文件带 path 用于下载
    for child in files[0]["children"]:
        assert child["type"] == "file"
        assert child["path"].startswith("batch1/")
        assert "size" in child


def test_list_files_root_files(tmp_path, monkeypatch):
    """根目录下的文件直接作为 file 节点。"""
    user_dir = _patch_user_dir(monkeypatch, tmp_path)
    (user_dir / "out.xlsx").write_bytes(b"\x00" * 2048)

    result = asyncio.run(ws.list_files(token="dummy"))
    files = result["files"]

    assert len(files) == 1
    assert files[0]["name"] == "out.xlsx"
    assert files[0]["type"] == "file"
    assert files[0]["path"] == "out.xlsx"
    assert files[0]["size"] == 2048
