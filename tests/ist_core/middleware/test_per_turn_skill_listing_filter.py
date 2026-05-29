"""PerTurnSkillReminder listing 过滤（对齐 Anthropic 官方 spec）。

只过滤 disable-model-invocation: true；fork / user-invocable: false 仍进模型 listing。
"""

from __future__ import annotations

from pathlib import Path

from main.ist_core.middleware.per_turn_skill_reminder import (
    _load_skills_from_dir,
    _skill_eligible_for_listing,
)


def test_skill_eligible_for_listing():
    
    assert _skill_eligible_for_listing({"context": "inline", "user-invocable": "true"})
    
    assert _skill_eligible_for_listing({"context": "fork", "user-invocable": "false"})
    
    assert _skill_eligible_for_listing({"context": "fork", "user-invocable": "true"})
    
    assert not _skill_eligible_for_listing({"disable-model-invocation": "true"})


def test_load_skills_from_dir_excludes_fork_only():
    """skills/ 目录下的所有 skill 都加载（fork + inline 都进 listing）。

    对齐 Anthropic：listing 只过滤 disable-model-invocation: true 的 skill。
    user-invocable: false 仍进模型 listing（用户菜单不显示）。
    """
    skills_dir = Path(__file__).resolve().parents[3] / "main" / "ist_core" / "skills"
    names = {m["name"] for m in _load_skills_from_dir(skills_dir)}
    assert "test-list-review" in names
    assert "review-verification" in names
