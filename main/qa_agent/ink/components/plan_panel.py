"""PlanPanel — 钉在输入框横线上方的 todo 列表。

触发于 ``write_todos`` 工具：sink 把 ``TodoListMessage`` 派给 IstInkApp，IstInkApp
直接调 ``PlanPanel.update(todos)`` 整列重渲染，**不再** append 到 transcript，
所以 plan 不会随对话滚走。状态切换（pending → in_progress → completed）也是
原地刷新 ● ◉ ○ 三态图标。
"""

from __future__ import annotations

from main.qa_agent.ink.dom import NodeType, create_element, create_text


def _icon(status: str) -> str:
    if status == "completed":
        return "\x1b[32m●\x1b[0m"
    if status == "in_progress":
        return "\x1b[33m◉\x1b[0m"
    return "\x1b[2m○\x1b[0m"


class PlanPanel:
    """常驻 plan 面板。``update`` 走整列重渲染；list ≤10 项不需要单行 diff。"""

    def __init__(self) -> None:
        self._node = create_element(NodeType.BOX)
        self._node.style.height = 0
        self._todos: list[dict[str, str]] = []

    @property
    def node(self):
        return self._node

    @property
    def is_visible(self) -> bool:
        return bool(self._todos)

    def update(self, todos: list[dict[str, str]]) -> None:
        self._todos = list(todos or [])
        self._node.clear_children()
        if not self._todos:
            self._node.style.height = 0
            return
        title_box = create_element(NodeType.BOX)
        title_box.style.height = 1
        title_box.append_child(create_text(" \x1b[1m⏺ Plan\x1b[0m"))
        self._node.append_child(title_box)
        for t in self._todos:
            row = create_element(NodeType.BOX)
            row.style.height = 1
            content = (t.get("content") or "")[:70]
            row.append_child(create_text(f"   {_icon(t.get('status', 'pending'))} {content}"))
            self._node.append_child(row)
        self._node.style.height = len(self._todos) + 1

    def clear(self) -> None:
        self.update([])
