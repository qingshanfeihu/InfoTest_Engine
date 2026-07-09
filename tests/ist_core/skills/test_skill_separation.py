"""Skill 内容分层（对齐 Anthropic 官方 fork skill 设计）：

- skills/test-list-review/SKILL.md   → inline skill，主 agent 工作流
- skills/review-verifier/SKILL.md → fork skill 任务定义（含 $ARGUMENTS）
- agents/review-verifier.md           → subagent 容器（system_prompt + tools + model）
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SKILLS = _PROJECT_ROOT / "main" / "ist_core" / "skills"
_AGENTS = _PROJECT_ROOT / "main" / "ist_core" / "agents"


def test_test_list_review_inline_skill_no_verifier_prompt():
    """inline skill 的 body 不应包含 verifier system_prompt 内容。"""
    body = (_SKILLS / "test-list-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "Your output IS the user-facing" not in body
    assert "try to break it" not in body


def test_review_verification_skill_is_thin_task_definition():
    """fork skill SKILL.md 只是任务定义，含 $ARGUMENTS 占位符；
    所有 verifier 行为约束已移到 agents/review-verifier.md。
    """
    text = (_SKILLS / "review-verifier" / "SKILL.md").read_text(encoding="utf-8")
    assert "context: fork" in text
    assert "agent: review-verifier" in text
    assert "user-invocable: false" in text
    assert "$ARGUMENTS" in text


def test_review_verifier_subagent_has_verifier_behavior():
    """agents/review-verifier.md 包含核心 verifier 行为约束。"""
    body = (_AGENTS / "review-verifier.md").read_text(encoding="utf-8")
    assert "try to break it" in body
    assert "VERDICT:" in body
    assert "Bucket discipline" in body
    
    assert "research material" in body or "research report" in body


def test_review_verifier_outputs_research_material_not_user_report():
    """对齐 Anthropic Explore 模式：verifier 输出研究材料，主 agent 复述给用户。"""
    body = (_AGENTS / "review-verifier.md").read_text(encoding="utf-8")
    
    assert "Your output IS the user-facing" not in body
    
    assert "caller" in body.lower()


def test_review_verifier_subagent_frontmatter_official_fields():
    """subagent .md 只用 Anthropic 官方字段：name, description, tools, model."""
    text = (_AGENTS / "review-verifier.md").read_text(encoding="utf-8")
    assert "name: review-verifier" in text
    assert "description:" in text
    assert "tools:" in text
    assert "model:" in text
