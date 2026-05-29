"""PlanPanel 单元测试 — 覆盖隐藏 / 显示 / 整列重渲染 / 状态图标 / 截断。"""

from __future__ import annotations

import pytest

from main.ist_core.ink.components.plan_panel import PlanPanel


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
    # 布局：top_gap + title + N rows + bottom_gap = N + 3
    assert panel.node.style.height == 6
    assert panel.is_visible is True
    assert len(panel.node.children) == 6


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
    # rows: [top_gap "", title, row1, bottom_gap ""] → 第一条 todo 在 index 2
    assert glyph in rows[2]
    assert ansi in rows[2]


def test_content_truncated_to_70() -> None:
    panel = PlanPanel()
    long = "a" * 200
    panel.update([{"status": "pending", "content": long}])
    rows = _texts(panel)

    assert rows[2].count("a") == 70


def test_update_replaces_previous_rows() -> None:
    """整列重渲染：第二次 update 应该完全替换第一次的内容。"""
    panel = PlanPanel()
    panel.update([
        {"status": "pending", "content": "old A"},
        {"status": "pending", "content": "old B"},
    ])
    panel.update([{"status": "completed", "content": "new only"}])
    # 单条 todo：top_gap + title + 1 row + bottom_gap = 4
    assert panel.node.style.height == 4
    rows = _texts(panel)
    assert any("new only" in r for r in rows)
    assert not any("old A" in r or "old B" in r for r in rows)
