"""fork skill loader 工具注册表与主 agent 工具路径一致."""

from __future__ import annotations

from main.ist_core.skills.loader import _get_tool_registry


def test_fork_tool_registry_includes_knowledge_tools():
    reg = _get_tool_registry()
    assert "kb_bug_search" in reg
    assert "kb_footprint" in reg
    assert getattr(reg["kb_bug_search"], "name", None) == "kb_bug_search"
    assert getattr(reg["kb_footprint"], "name", None) == "kb_footprint"
