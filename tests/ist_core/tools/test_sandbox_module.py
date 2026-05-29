"""测试 ``_sandbox.py`` 模块的 CWD 解析层。

来源：plan Step 5（沙箱接口统一）。

参考实现：
- ``utils/cwd.ts:1-33`` ``pwd()`` —— 简化为 ``_default_cwd()``
- ``BashTool/pathValidation.ts`` —— 反向变种 ``_resolve_cwd_for_target()``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from main.ist_core.tools.deepagent import file_tools
from main.ist_core.tools.deepagent._sandbox import (
    _default_cwd,
    _resolve_cwd_for_target,
)


def test_default_cwd_returns_first_root():
    """``_default_cwd()`` 返回 ``_agent_roots()[0]``——当前是 knowledge/data/."""
    assert _default_cwd() == file_tools._agent_roots()[0]


def test_default_cwd_picks_up_monkeypatch(tmp_path, monkeypatch):
    """改 ``file_tools._AGENT_ROOT`` 后 ``_default_cwd()`` 跟上."""
    sandbox = tmp_path / "knowledge" / "data"
    sandbox.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", sandbox)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "_no_workspace")
    assert _default_cwd() == sandbox


def test_resolve_cwd_for_none_falls_back_to_default():
    """target=None 退化到 ``_default_cwd()``."""
    assert _resolve_cwd_for_target(None) == _default_cwd()


def test_resolve_cwd_for_path_in_workspace(tmp_path, monkeypatch):
    """target 在 workspace 根下 → 返回 workspace 根."""
    agent_root = tmp_path / "knowledge" / "data"
    workspace_root = tmp_path / "workspace"
    agent_root.mkdir(parents=True)
    workspace_root.mkdir(parents=True)
    target = workspace_root / "inputs" / "case.xlsx"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", workspace_root)

    chosen = _resolve_cwd_for_target(target)
    
    assert chosen.resolve() == workspace_root.resolve()


def test_resolve_cwd_for_path_in_agent_root(tmp_path, monkeypatch):
    """target 在 knowledge/data 根下 → 返回 agent_root."""
    agent_root = tmp_path / "knowledge" / "data"
    workspace_root = tmp_path / "workspace"
    agent_root.mkdir(parents=True)
    workspace_root.mkdir(parents=True)
    target = agent_root / "markdown" / "qa" / "x.md"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", workspace_root)

    chosen = _resolve_cwd_for_target(target)
    assert chosen.resolve() == agent_root.resolve()


def test_resolve_cwd_for_outside_path_falls_back(tmp_path, monkeypatch):
    """target 在所有沙箱根之外 → 退化到 ``_default_cwd()``."""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "_no_workspace")
    outside = tmp_path / "elsewhere" / "x.txt"
    outside.parent.mkdir(parents=True)
    outside.write_text("x")

    assert _resolve_cwd_for_target(outside) == agent_root


def test_resolve_cwd_accepts_string_path(tmp_path, monkeypatch):
    """target 接受字符串而不只是 Path 对象."""
    agent_root = tmp_path / "knowledge" / "data"
    agent_root.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", agent_root)
    monkeypatch.setattr(file_tools, "_WORKSPACE_ROOT", tmp_path / "_nx")
    target = agent_root / "x.md"
    target.write_text("x")

    chosen = _resolve_cwd_for_target(str(target))
    assert chosen.resolve() == agent_root.resolve()
