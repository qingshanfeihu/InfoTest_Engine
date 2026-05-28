"""Skill 内容分层：inline 工作流 vs fork verifier prompt."""

from __future__ import annotations

from pathlib import Path

_SKILLS = Path(__file__).resolve().parents[3] / "main" / "qa_agent" / "skills"


def test_test_case_review_skill_no_fork_user_facing_prompt():
    body = (_SKILLS / "test-case-review" / "SKILL.md").read_text(encoding="utf-8")
    assert "Your output IS the user-facing" not in body


def test_review_verification_fork_has_verdict_format():
    body = (_SKILLS / "review-verification" / "SKILL.md").read_text(encoding="utf-8")
    assert "try to break it" in body
    assert "VERDICT:" in body
    assert "Bucket discipline" in body
    assert "证据摘录" in body
    assert "qa_deepagent_grep" in body  # 出现在「禁止」说明中


def test_review_verification_forbids_tool_syntax_in_user_report():
    body = (_SKILLS / "review-verification" / "SKILL.md").read_text(encoding="utf-8")
    assert "Verification command" not in body.split("# Output format")[1].split("```")[0] or "禁止" in body
    assert "用户可见报告" in body


def test_review_verification_is_fork_not_user_invocable():
    text = (_SKILLS / "review-verification" / "SKILL.md").read_text(encoding="utf-8")
    assert "context: fork" in text
    assert "user-invocable: false" in text
