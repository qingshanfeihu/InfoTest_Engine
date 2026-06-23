"""Anthropic skill spec 兼容性测试：frontmatter 字段 + listing 行为."""

from __future__ import annotations

from pathlib import Path

from main.ist_core.middleware.per_turn_skill_reminder import _skill_eligible_for_listing
from main.ist_core.skills.loader import read_skill_frontmatter

_SKILLS = Path(__file__).resolve().parents[3] / "main" / "ist_core" / "skills"


def test_review_verification_is_fork_skill():
    """review-verification 是 fork skill，引用 review-verifier subagent。"""
    fm = read_skill_frontmatter(_SKILLS / "review-verification" / "SKILL.md")
    assert fm is not None
    assert fm.get("context") == "fork"
    assert fm.get("agent") == "review-verifier"
    assert fm.get("user-invocable") is False


def test_review_verification_listed_to_model():
    """对齐标准：user-invocable: false 仍进模型 listing。

    "仅本智能体可调用此 skill" — 模型可见，用户菜单不可见。
    这样 test-list-review Step 7 引导模型调 review-verification 时，模型知道这个 skill存在。
    """
    fm = read_skill_frontmatter(_SKILLS / "review-verification" / "SKILL.md")
    meta = {
        "context": fm.get("context", "inline"),
        "user-invocable": str(fm.get("user-invocable", "true")),
        "disable-model-invocation": str(fm.get("disable-model-invocation", "false")),
    }
    
    assert _skill_eligible_for_listing(meta)


def test_invoke_skill_allows_test_list_review():
    from main.ist_core.tools.skills import invoke_skill
    out = invoke_skill.invoke({"skill": "test-list-review", "brief": ""})
    assert "ERROR: skill" not in out.split("\n", 1)[0]
    assert "# Skill loaded: test-list-review" in out


def test_listing_excludes_disable_model_invocation_inline():
    assert not _skill_eligible_for_listing(
        {
            "context": "inline",
            "user-invocable": "true",
            "disable-model-invocation": "true",
        }
    )


def test_listing_allows_fork_without_disable():
    """对齐 Anthropic: fork 本身不是过滤条件，只要没 disable-model-invocation 且 user-invocable=true。"""
    assert _skill_eligible_for_listing(
        {
            "context": "fork",
            "user-invocable": "true",
            "disable-model-invocation": "false",
        }
    )


def test_no_legacy_extension_fields():
    """确保 review-verification 不含已废弃的 IST-Core 扩展字段。"""
    fm = read_skill_frontmatter(_SKILLS / "review-verification" / "SKILL.md")
    assert "depends-on" not in fm, "depends-on 已被 skillOverrides 替代"
    assert "inherit-parent-prompt" not in fm, "subagent 已有完整 system_prompt"
    assert "recursion-limit" not in fm, "已移到 subagent 配置"
