"""fork skill loader 工具注册表与主 agent 工具路径一致."""

from __future__ import annotations

from main.ist_core.skills.loader import _get_tool_registry


def test_fork_tool_registry_includes_knowledge_tools():
    reg = _get_tool_registry()
    assert "web_bug_search" in reg
    assert "qa_footprint_lookup" in reg
    assert getattr(reg["web_bug_search"], "name", None) == "web_bug_search"
    assert getattr(reg["qa_footprint_lookup"], "name", None) == "qa_footprint_lookup"
