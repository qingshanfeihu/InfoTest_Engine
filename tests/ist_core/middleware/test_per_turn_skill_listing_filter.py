"""PerTurnSkillReminder listing 过滤。

只过滤 disable-model-invocation: true（完全不可见，qa_invoke_skill 也拒）。
user-invocable: false 的 fork 子流程（ist_compile_draft/run/grade、review-verification）
仍进主 agent listing——它们由 inline 编排 skill 的 body 引导主 agent 经 qa_invoke_skill
派发，派发者就是主 agent，必须对模型可见；只是不进 TUI /skill 用户菜单。
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
    # inline + user-invocable → 进 listing
    assert _skill_eligible_for_listing({"context": "inline", "user-invocable": "true"})
    # fork + user-invocable: false → 仍进主 agent listing（由编排 skill body 引导主 agent 派发）
    assert _skill_eligible_for_listing({"context": "fork", "user-invocable": "false"})
    # fork + user-invocable: true → 进 listing
    assert _skill_eligible_for_listing({"context": "fork", "user-invocable": "true"})
    # disable-model-invocation: true → 不进 listing（唯一过滤条件）
    assert not _skill_eligible_for_listing({"disable-model-invocation": "true"})
    # user-invocable 缺省视为 true → 进 listing
    assert _skill_eligible_for_listing({"context": "inline"})


def test_load_skills_from_dir_includes_fork_subflows():
    """fork 子流程 skill（user-invocable: false）仍进主 agent listing。

    它们由 inline 编排 skill（ist_compile_orchestrate / test-list-review）的 body 引导
    主 agent 经 qa_invoke_skill 派发，派发者是主 agent，必须对模型可见。
    listing 唯一过滤条件是 disable-model-invocation: true。
    """
    skills_dir = Path(__file__).resolve().parents[3] / "main" / "ist_core" / "skills"
    names = {m["name"] for m in _load_skills_from_dir(skills_dir)}
    assert "test-list-review" in names
    assert "ist_compile_orchestrate" in names
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


# ── 触发词提取（回归保护：曾因 when_to_use 被空格 join 成一行而永远提取不到）──


def test_trigger_keywords_extracted_into_listing():
    """when_to_use 含 'Trigger keywords:' 行时，触发词必须出现在 listing 的 [触发: ...]。

    回归点：_parse_skill_frontmatter 须保留 \\n，_format_skill_list 才能 split 出该行。
    """
    meta = [{
        "name": "demo",
        "description": "做某事",
        "when_to_use": "Use when 用户要做某事。\nTrigger keywords: 编译, 改编, case.xlsx。\nSKIP when: 别的场景。",
    }]
    out = _format_skill_list(meta)
    assert "[触发:" in out
    assert "编译" in out and "case.xlsx" in out


def test_trigger_keywords_case_and_colon_variants():
    """大小写无关 + 中英冒号都能提取（Trigger phrases / trigger keywords / 全角：）。"""
    for when in (
        "trigger keywords: 甲, 乙。",
        "Trigger phrases: 甲, 乙。",
        "Trigger keywords： 甲, 乙。",  # 全角冒号
    ):
        out = _format_skill_list([{"name": "s", "description": "d", "when_to_use": when}])
        assert "[触发: 甲, 乙" in out, f"未提取: {when!r} → {out!r}"


def test_real_orchestrate_skill_listing_has_triggers():
    """真实 ist_compile_orchestrate skill：listing 必须含描述 + 编译类触发词。

    这是用户报告「编译脑图用例没命中 ist_compile_orchestrate」的端到端回归保护。
    """
    skills_dir = Path(__file__).resolve().parents[3] / "main" / "ist_core" / "skills"
    metas = _load_skills_from_dir(skills_dir)
    out = _format_skill_list(metas)
    orch_line = next((l for l in out.splitlines() if "ist_compile_orchestrate" in l), "")
    assert orch_line, "ist_compile_orchestrate 未出现在 listing"
    # 用户高频用词进了 description 或触发词
    assert "编译" in orch_line
    assert "[触发:" in orch_line and ("excel" in orch_line.lower() or "case.xlsx" in orch_line)
