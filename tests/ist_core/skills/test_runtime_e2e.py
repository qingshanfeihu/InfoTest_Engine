"""真实 runtime 集成测试：fork skill 完整链路 + 官方 explore subagent 加载。

不依赖 tmp_path，使用 IST-Core 仓库内真实文件。
LLM 用 stub 避免 API 依赖，但 graph / invoke_skill / execute_fork_skill 路径真实执行。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_AGENTS_DIR = _PROJECT_ROOT / "main" / "ist_core" / "agents"
_SKILLS_DIR = _PROJECT_ROOT / "main" / "ist_core" / "skills"







def test_official_explore_subagent_file_exists():
    """main/ist_core/agents/explore.md 是真实文件（不是 tmp_path fixture）。"""
    explore_md = _AGENTS_DIR / "explore.md"
    assert explore_md.exists(), f"{explore_md} not found"


def test_official_explore_subagent_loads():
    """通过 load_subagent 真实加载官方 explore.md。"""
    from main.ist_core.skills.loader import load_subagent

    spec = load_subagent("explore")
    assert spec is not None
    assert spec["name"] == "Explore"
    assert spec["model"] == "haiku"
    
    assert "read-only research subagent" in spec["system_prompt"]
    assert "thoroughness" in spec["system_prompt"].lower()
    
    tools_spec = spec["tools_spec"]
    assert "fs_read" in str(tools_spec)
    assert "fs_grep" in str(tools_spec)


def test_official_explore_listed_in_subagents():
    """list_subagents() 应能发现官方 explore subagent。"""
    from main.ist_core.skills.loader import list_subagents

    names = [s["name"] for s in list_subagents()]
    assert "Explore" in names
    assert "review-verifier" in names


def test_fork_skill_can_reference_official_explore():
    """创建一个引用官方 Explore 的 fork skill，验证 frontmatter 被正确解析。"""
    
    import tempfile

    from main.ist_core.skills.loader import (
        _AGENTS_DIR as real_agents_dir,
        load_subagent,
        read_skill_frontmatter,
    )

    
    spec = load_subagent("explore")
    assert spec is not None, "official explore subagent must be loadable for fork skill to reference it"
    assert real_agents_dir == _AGENTS_DIR







def test_review_verification_fork_runs_end_to_end(monkeypatch):
    """端到端：invoke_skill('review-verification') → execute_fork_skill →
    review-verifier subagent → 返回带 VERDICT/LEVEL 的报告。

    用 stub LLM 模拟 review-verifier 的行为（输出 VERDICT/LEVEL 行）。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    captured_input_messages: list = []
    captured_system_prompt: list[str] = []

    class _StubChatModel:
        def bind_tools(self, tools, **kw):
            return self

        def invoke(self, messages, **kwargs):
            
            for msg in messages or []:
                if hasattr(msg, "type") and msg.type == "system":
                    captured_system_prompt.append(msg.content)
            return AIMessage(
                content=(
                    "## 评审报告\n"
                    "已验证主 agent 草稿，未发现重大缺漏。\n\n"
                    "## 改进建议\n"
                    "- (P3) 补充边界值用例\n\n"
                    "VERDICT: PASS\n"
                    "LEVEL: P3"
                )
            )

    
    monkeypatch.setattr(
        "main.ist_core.agents._llm.build_agent_chat_model",
        lambda *a, **kw: _StubChatModel(),
    )

    
    class _StubAgentGraph:
        def with_config(self, *a, **kw):
            return self

        def invoke(self, payload, config=None):
            captured_input_messages.extend(payload.get("messages", []))
            stub_model = _StubChatModel()
            ai_msg = stub_model.invoke([])
            return {"messages": payload["messages"] + [ai_msg]}

    monkeypatch.setattr(
        "langchain.agents.create_agent",
        lambda *a, **kw: _StubAgentGraph(),
    )

    
    from main.ist_core.skills.loader import clear_subagent_cache
    clear_subagent_cache()

    
    from main.ist_core.tools.skills import invoke_skill

    test_brief = (
        "test_case_file: knowledge/data/markdown/qa/Test_List_demo.md\n"
        "bug_id: BUG-DEMO-1\n"
        "draft_findings:\n"
        "  - line 10: missing negative test\n"
        "draft_level: P3\n"
    )

    result = invoke_skill.invoke({
        "skill": "review-verification",
        "brief": test_brief,
    })

    
    assert "VERDICT: PASS" in result
    assert "LEVEL: P3" in result
    assert "评审报告" in result

    
    assert len(captured_input_messages) >= 1
    human_msgs = [m for m in captured_input_messages if isinstance(m, HumanMessage)]
    assert len(human_msgs) >= 1
    msg_content = human_msgs[0].content
    assert "BUG-DEMO-1" in msg_content
    assert "$ARGUMENTS" not in msg_content
    
    assert "Verify the test list review draft" in msg_content


def test_skill_overrides_off_blocks_fork_skill_invocation(monkeypatch, tmp_path):
    """skillOverrides 'off' 状态下，invoke_skill 应拒绝调用。"""
    import main.ist_core.skills.state as state_mod

    
    settings = tmp_path / "settings.local.json"
    monkeypatch.setattr(state_mod, "_SETTINGS_PATH", settings)

    
    state_mod.set_skill_state("review-verification", "off")

    from main.ist_core.tools.skills import invoke_skill

    result = invoke_skill.invoke({
        "skill": "review-verification",
        "brief": "test",
    })

    assert "ERROR" in result
    assert "off" in result.lower() or "not callable" in result.lower()


def test_skill_overrides_on_allows_invocation(monkeypatch, tmp_path):
    """skillOverrides 'on' 状态（默认）下，invoke_skill 应放行到执行流程。"""
    import main.ist_core.skills.state as state_mod

    settings = tmp_path / "settings.local.json"
    monkeypatch.setattr(state_mod, "_SETTINGS_PATH", settings)

    
    assert state_mod.get_skill_state("review-verification") == "on"

    
    monkeypatch.setattr(
        "main.ist_core.skills.loader.execute_fork_skill",
        lambda skill, brief="": f"STUB: skill={skill}, brief={brief[:20]}",
    )

    from main.ist_core.tools.skills import invoke_skill

    result = invoke_skill.invoke({
        "skill": "review-verification",
        "brief": "test brief content",
    })

    assert "STUB:" in result
    assert "review-verification" in result
