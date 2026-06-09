"""PerTurnSkillReminder listing 过滤（对齐 Anthropic 官方 spec）。

只过滤 disable-model-invocation: true；fork / user-invocable: false 仍进模型 listing。
"""

from __future__ import annotations

from pathlib import Path

from main.ist_core.middleware.per_turn_skill_reminder import (
    _format_skill_list,
    _load_skills_from_dir,
    _skill_eligible_for_listing,
    _truncate,
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


# ── 渐进披露预算（P0）─────────────────────────────────────────────────


def test_truncate_caps_length():
    assert _truncate("abcdefghij", 5) == "abcd…"
    assert _truncate("short", 100) == "short"
    assert _truncate("  spaced  ", 0) == "spaced"  # cap<=0 不截断


def test_listing_drops_when_to_use():
    """when_to_use 不进常驻 listing（触发后才从 SKILL.md body 读）。"""
    meta = [{"name": "s1", "description": "做某事", "when_to_use": "TRIGGER: 关键词一大串"}]
    out = _format_skill_list(meta)
    assert "s1" in out and "做某事" in out
    assert "TRIGGER" not in out and "when" not in out.lower()


def test_listing_per_skill_cap(monkeypatch):
    import main.ist_core.middleware.per_turn_skill_reminder as m

    monkeypatch.setattr(m, "_PER_SKILL_DESC_CAP", 10)
    monkeypatch.setattr(m, "_LISTING_CHAR_BUDGET", 10_000)
    out = m._format_skill_list([{"name": "s", "description": "x" * 50}])
    assert "…" in out and "x" * 50 not in out


def test_listing_global_budget_degrades_to_name_only(monkeypatch):
    """超全局预算的 skill 降级为 name-only（仅列名，不列描述）。"""
    import main.ist_core.middleware.per_turn_skill_reminder as m

    monkeypatch.setattr(m, "_PER_SKILL_DESC_CAP", 200)
    monkeypatch.setattr(m, "_LISTING_CHAR_BUDGET", 30)
    meta = [
        {"name": "first", "description": "占满预算的描述内容"},
        {"name": "second", "description": "这条应该被降级掉"},
    ]
    out = m._format_skill_list(meta)
    lines = out.splitlines()
    # 第一条带描述，第二条仅列名
    assert lines[0] == "- **first**: 占满预算的描述内容"
    assert lines[1] == "- **second**"
