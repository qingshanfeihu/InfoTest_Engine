"""AskUserPanel 单元测试 — 隐藏/显示 + 长选项行软换行(不再被单行行盒截断)。

2026-07-02 实测:决策面板的长选项(label+description 超终端宽)被 height=1 行盒
截成半句(「用 show stat」)。修复=TextNode 直挂面板 + auto 高度,布局引擎按
软换行真实行数估高、渲染层原生折行。本测试锁定该行为。
"""

from __future__ import annotations

from main.ist_core.ink.components.ask_user_panel import AskUserPanel
from main.ist_core.ink.dom import NodeType, create_element
from main.ist_core.ink.layout.engine import compute_layout


def test_initial_hidden() -> None:
    panel = AskUserPanel()
    assert panel.node.style.height == 0
    assert panel.is_visible is False


def test_clear_hides() -> None:
    panel = AskUserPanel()
    panel.update(["line"])
    assert panel.is_visible is True
    panel.clear()
    assert panel.node.style.height == 0
    assert panel.is_visible is False


def test_long_option_line_wraps_instead_of_truncating() -> None:
    panel = AskUserPanel()
    long_line = " 1. 改过程 (Recommended) — " + "请求数加到覆盖完整一轮并用统计命令验证分布," * 6
    short_line = " 2. 改预期"
    panel.update([long_line, short_line])

    # auto 高度:不再是 len(lines)+1 的固定值
    assert panel.node.style.height is None

    # 窄终端下布局:长行应折成多行,面板总高 > 行数+1(顶部空行)
    root = create_element(NodeType.BOX)
    root.style.flex_direction = "column"
    root.append_child(panel.node)
    width = 60
    compute_layout(root, width, 40)
    assert panel.node.rect.height > 3  # 1 空行 + 长行折出的多行 + 短行

    # 行内容原样保留(未被 [:N] 截断)
    values = [getattr(c, "value", "") for c in panel.node.children]
    assert long_line in values and short_line in values
