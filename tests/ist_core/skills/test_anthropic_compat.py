"""标准 Custom Skill 架构兼容性测试。

验证 IST-Core 能直接加载未经修改的标准 spec skill / subagent 文件。
"""

from __future__ import annotations

import pytest


def test_anthropic_official_subagent_format(tmp_path, monkeypatch):
    """完全按 standard subagent 格式写的 .md 应该能加载。
    """
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    agent_file = agents_dir / "code-reviewer.md"
    agent_file.write_text(
        """---
name: code-reviewer
description: Reviews code for quality and best practices
tools: fs_read, fs_grep
model: sonnet
---

You are a code reviewer. Analyze the code and provide actionable feedback
on quality, security, and best practices.
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "main.ist_core.skills.loader._AGENTS_DIR", agents_dir
    )

    from main.ist_core.skills.loader import load_subagent

    spec = load_subagent("code-reviewer")
    assert spec is not None
    assert spec["name"] == "code-reviewer"
    assert spec["description"] == "Reviews code for quality and best practices"
    assert spec["model"] == "sonnet"
    assert "code reviewer" in spec["system_prompt"].lower()
    
    assert "fs_read" in str(spec["tools_spec"])


def test_anthropic_official_fork_skill_format(tmp_path, monkeypatch):
    """完全按 standard fork skill 格式写的 SKILL.md 应该能加载。
    """
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "deep-research"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        """---
name: deep-research
description: Research a topic thoroughly using the review-verifier subagent.
context: fork
agent: review-verifier
---

Research $ARGUMENTS thoroughly:
1. Find relevant files using grep
2. Read and analyze the code
3. Summarize findings with specific file references
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "main.ist_core.skills.loader._SKILLS_DIR", skills_dir
    )

    
    from main.ist_core.skills.loader import read_skill_frontmatter

    fm = read_skill_frontmatter(skill_md)
    assert fm is not None
    assert fm["name"] == "deep-research"
    assert fm["context"] == "fork"
    assert fm["agent"] == "review-verifier"


def test_anthropic_arguments_substitution(tmp_path, monkeypatch):
    """标准 $ARGUMENTS 占位符应被正确替换。"""
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "echo-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: echo-skill
description: Echoes args back
context: fork
agent: review-verifier
---

User wants: $ARGUMENTS

Process the request above.
""",
        encoding="utf-8",
    )

    from langchain_core.messages import AIMessage, HumanMessage

    captured = []

    class _StubRunnable:
        def with_config(self, *a, **kw):
            return self

        def invoke(self, payload):
            captured.extend(payload["messages"])
            return {"messages": [AIMessage(content="done")]}

    monkeypatch.setattr(
        "main.ist_core.skills.loader._SKILLS_DIR", skills_dir
    )
    monkeypatch.setattr(
        "main.ist_core.skills.loader.get_subagent_runnable",
        lambda name: _StubRunnable(),
    )

    from main.ist_core.skills.loader import execute_fork_skill

    result = execute_fork_skill("echo-skill", brief="explain DNS round-robin")
    assert result == "done"

    msg = captured[0]
    assert isinstance(msg, HumanMessage)
    assert "explain DNS round-robin" in msg.content
    assert "$ARGUMENTS" not in msg.content


def test_skill_overrides_state_file_format():
    """skillOverrides 写入的 settings 文件格式。"""
    import json
    from pathlib import Path
    import tempfile

    from main.ist_core.skills import state as state_mod

    with tempfile.TemporaryDirectory() as td:
        settings = Path(td) / "settings.local.json"
        old_path = state_mod._SETTINGS_PATH
        state_mod._SETTINGS_PATH = settings
        try:
            state_mod.set_skill_state("foo", "name-only")
            state_mod.set_skill_state("bar", "off")
            data = json.loads(settings.read_text())
            
            assert "skillOverrides" in data
            assert data["skillOverrides"]["foo"] == "name-only"
            assert data["skillOverrides"]["bar"] == "off"
        finally:
            state_mod._SETTINGS_PATH = old_path


def test_skill_overrides_four_states():
    """四个 state 都能正确读写。"""
    import tempfile
    from pathlib import Path

    from main.ist_core.skills import state as state_mod

    with tempfile.TemporaryDirectory() as td:
        settings = Path(td) / "settings.local.json"
        old_path = state_mod._SETTINGS_PATH
        state_mod._SETTINGS_PATH = settings
        try:
            for s in ("on", "name-only", "user-invocable-only", "off"):
                state_mod.set_skill_state("test-skill", s)
                assert state_mod.get_skill_state("test-skill") == s
        finally:
            state_mod._SETTINGS_PATH = old_path
