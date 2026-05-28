"""PlanPanel 单元测试 — 覆盖隐藏 / 显示 / 整列重渲染 / 状态图标 / 截断。"""

from __future__ import annotations

import pytest

from main.qa_agent.ink.components.plan_panel import PlanPanel


def _texts(panel: PlanPanel) -> list[str]:
    """从 panel DOM 抽出每行 TextNode 的 value，便于断言。"""
    out: list[str] = []
    for child in panel.node.children:
        for grand in getattr(child, "children", []) or []:
            value = getattr(grand, "value", None)
            if value is not None:
                out.append(value)
    return out


def test_initial_hidden() -> None:
    panel = PlanPanel()
    assert panel.node.style.height == 0
    assert panel.is_visible is False
    assert len(panel.node.children) == 0


def test_update_sets_height() -> None:
    panel = PlanPanel()
    panel.update([
        {"status": "completed", "content": "step 1"},
        {"status": "in_progress", "content": "step 2"},
        {"status": "pending", "content": "step 3"},
    ])
    # 标题 1 行 + 3 项 todos
    assert panel.node.style.height == 4
    assert panel.is_visible is True
    assert len(panel.node.children) == 4


def test_clear_resets() -> None:
    panel = PlanPanel()
    panel.update([{"status": "pending", "content": "a"}])
    panel.clear()
    assert panel.node.style.height == 0
    assert panel.is_visible is False
    assert len(panel.node.children) == 0


@pytest.mark.parametrize(
    "status,glyph,ansi",
    [
        ("completed", "●", "\x1b[32m"),
        ("in_progress", "◉", "\x1b[33m"),
        ("pending", "○", "\x1b[2m"),
    ],
)
def test_status_icons(status: str, glyph: str, ansi: str) -> None:
    panel = PlanPanel()
    panel.update([{"status": status, "content": "x"}])
    rows = _texts(panel)
    # rows[0] 是标题，rows[1] 是第一项 todo
    assert glyph in rows[1]
    assert ansi in rows[1]


def test_content_truncated_to_70() -> None:
    panel = PlanPanel()
    long = "a" * 200
    panel.update([{"status": "pending", "content": long}])
    rows = _texts(panel)
    # rows[1] 形如 "   ○ aaaa..."，截断后正文最多 70 个 a
    assert rows[1].count("a") == 70


def test_update_replaces_previous_rows() -> None:
    """整列重渲染：第二次 update 应该完全替换第一次的内容。"""
    panel = PlanPanel()
    panel.update([
        {"status": "pending", "content": "old A"},
        {"status": "pending", "content": "old B"},
    ])
    panel.update([{"status": "completed", "content": "new only"}])
    assert panel.node.style.height == 2
    rows = _texts(panel)
    assert any("new only" in r for r in rows)
    assert not any("old A" in r or "old B" in r for r in rows)
