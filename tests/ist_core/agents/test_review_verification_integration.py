"""测试 review-verifier fork skill 集成（对齐 Anthropic 官方设计）。

新架构：
- skills/review-verifier/SKILL.md     fork skill 任务定义（agent: review-verifier）
- agents/review-verifier.md                subagent 容器（system_prompt + tools + model）
- invoke_skill 检测 context: fork → 调 execute_fork_skill → spawn subagent
"""

from __future__ import annotations

import pytest


def test_review_verification_skill_loadable():
    """review-verifier 的 SKILL.md frontmatter 完整可读。"""
    from main.ist_core.skills.loader import read_skill_frontmatter
    from pathlib import Path

    skill_md = (
        Path(__file__).resolve().parents[3]
        / "main" / "ist_core" / "skills" / "review-verifier" / "SKILL.md"
    )
    fm = read_skill_frontmatter(skill_md)
    assert fm is not None
    assert fm["name"] == "review-verifier"
    assert fm["context"] == "fork"
    assert fm["agent"] == "review-verifier"


def test_review_verifier_subagent_loadable():
    """agents/review-verifier.md 通过 load_subagent 可加载。"""
    from main.ist_core.skills.loader import load_subagent

    spec = load_subagent("review-verifier")
    assert spec is not None
    assert spec["name"] == "review-verifier"
    assert spec["model"] == "opus"
    
    assert "try to break it" in spec["system_prompt"]
    assert "VERDICT:" in spec["system_prompt"]


def test_review_verifier_system_prompt_anti_laziness():
    """subagent system_prompt 包含反偷懒约束（adversarial + 独立验证）。"""
    from main.ist_core.skills.loader import load_subagent

    spec = load_subagent("review-verifier")
    prompt = spec["system_prompt"]

    
    assert "try to break it" in prompt
    assert "Independent verification" in prompt or "independent verification" in prompt.lower()

    
    assert "VERDICT:" in prompt
    assert "LEVEL:" in prompt

    
    assert "Bucket discipline" in prompt


def test_review_verifier_forbids_recursive_subagents():
    """subagent 不能再 spawn 子代理（避免无限递归）。"""
    from main.ist_core.skills.loader import load_subagent

    spec = load_subagent("review-verifier")
    prompt = spec["system_prompt"]
    
    assert "spawning further subagents" in prompt.lower()


def test_main_agent_no_longer_registers_review_verification(monkeypatch):
    """build_main_agent() 不再把 review-verifier 注册为 deepagents subagent。

    新架构：fork skill 通过 invoke_skill 执行，不进 deepagents subagents 列表。
    """
    import sys

    class _StubModel:
        def bind_tools(self, tools, **kw):
            return self

        def invoke(self, *args, **kwargs):
            return None

    monkeypatch.setattr(
        "main.ist_core.agents._llm.build_agent_chat_model",
        lambda *args, **kwargs: _StubModel(),
    )
    monkeypatch.setattr(
        "main.ist_core.agents._llm.build_explore_model",
        lambda *args, **kwargs: _StubModel(),
    )

    captured: dict = {}

    def _capture_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return _StubModel()

    deepagents_mod = sys.modules.get("deepagents")
    if deepagents_mod is None:
        import deepagents as deepagents_mod
    monkeypatch.setattr(
        deepagents_mod, "create_deep_agent", _capture_create_deep_agent,
    )

    from main.ist_core.agents.main_agent import build_main_agent
    build_main_agent()

    assert "subagents" in captured
    subagent_names = [s["name"] for s in captured["subagents"]]
    assert "explore" in subagent_names
    assert "review-verifier" not in subagent_names
    assert "review-verifier" not in subagent_names


def test_invoke_skill_routes_to_execute_fork_skill(monkeypatch):
    """invoke_skill 检测 context: fork → execute_fork_skill。"""
    captured: dict = {}

    def _stub_execute_fork_skill(skill: str, brief: str = "") -> str:
        captured["skill"] = skill
        captured["brief"] = brief
        return "STUB FORK RESULT"

    monkeypatch.setattr(
        "main.ist_core.skills.loader.execute_fork_skill",
        _stub_execute_fork_skill,
    )

    from main.ist_core.tools.skills import invoke_skill

    out = invoke_skill.invoke(
        {"skill": "review-verifier", "brief": "test brief"}
    )
    assert out == "STUB FORK RESULT"
    assert captured["skill"] == "review-verifier"
    assert captured["brief"] == "test brief"


def test_execute_fork_skill_renders_arguments(monkeypatch):
    """SKILL.md body 中的 $ARGUMENTS 应被 brief 替换后传给 subagent。"""
    from langchain_core.messages import AIMessage, HumanMessage

    captured_messages = []

    class _StubRunnable:
        def with_config(self, *args, **kwargs):
            return self

        def invoke(self, payload, config=None):
            captured_messages.extend(payload.get("messages", []))
            return {
                "messages": [
                    AIMessage(content="STUB OUTPUT\n\nVERDICT: PASS\nLEVEL: P3")
                ]
            }

    def _stub_runnable_factory(name, **kwargs):
        return _StubRunnable()

    monkeypatch.setattr(
        "main.ist_core.skills.loader.get_subagent_runnable",
        _stub_runnable_factory,
    )

    from main.ist_core.skills.loader import execute_fork_skill

    result = execute_fork_skill("review-verifier", brief="MY_BRIEF_CONTENT")

    
    assert "VERDICT: PASS" in result

    
    assert len(captured_messages) == 1
    msg = captured_messages[0]
    assert isinstance(msg, HumanMessage)
    assert "MY_BRIEF_CONTENT" in msg.content
    
    assert "$ARGUMENTS" not in msg.content


def test_execute_fork_skill_missing_agent_field_errors(tmp_path, monkeypatch):
    """fork skill 缺少 agent: 字段 → 报错。"""
    from main.ist_core.skills.loader import execute_fork_skill

    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "broken-fork"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken-fork\ndescription: missing agent field\ncontext: fork\n---\nBody.",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "main.ist_core.skills.loader._SKILLS_DIR", skills_dir
    )

    result = execute_fork_skill("broken-fork", brief="x")
    assert "ERROR" in result
    assert "agent:" in result.lower() or "agent " in result.lower()


def test_execute_fork_skill_unknown_agent_errors(tmp_path, monkeypatch):
    """fork skill 引用不存在的 subagent → 报错。"""
    from main.ist_core.skills.loader import execute_fork_skill

    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / "bad-agent"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: bad-agent\ndescription: x\ncontext: fork\nagent: nonexistent\n---\nBody.",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "main.ist_core.skills.loader._SKILLS_DIR", skills_dir
    )

    result = execute_fork_skill("bad-agent", brief="x")
    assert "ERROR" in result
    assert "nonexistent" in result
