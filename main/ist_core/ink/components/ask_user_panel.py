"""AskUserPanel — 钉在输入框横线上方的交互式问答面板。

仿 PlanPanel：qa_ask_user 触发时，IstInkApp 把 AskUserSession 的渲染行整块
塞进本面板（独立 Box 节点），**不再 append 到 transcript**——所以问答选项不会
随对话滚走，始终固定在输入框上方（对齐 cc-haha 的底部 permission dialog 位置）。

渲染内容由 AskUserSession.render_lines() 提供（含 ANSI 着色 / 高亮 / 选中态）。
面板只负责把这些行整列重渲染到固定区，状态机逻辑全在 AskUserSession。
"""

from __future__ import annotations

from main.ist_core.ink.dom import NodeType, create_element, create_text


class AskUserPanel:
    """常驻问答面板。``update(lines)`` 整列重渲染；空 lines 时隐藏。"""

    def __init__(self) -> None:
        self._node = create_element(NodeType.BOX)
        self._node.style.height = 0
        self._visible = False

    @property
    def node(self):
        return self._node

    @property
    def is_visible(self) -> bool:
        return self._visible

    def update(self, lines: list[str]) -> None:
        self._node.clear_children()
        if not lines:
            self._node.style.height = 0
            self._visible = False
            return
        # 顶部留一空行与上方对话隔开
        top_gap = create_element(NodeType.BOX)
        top_gap.style.height = 1
        top_gap.append_child(create_text(""))
        self._node.append_child(top_gap)
        for ln in lines:
            row = create_element(NodeType.BOX)
            row.style.height = 1
            row.append_child(create_text(ln))
            self._node.append_child(row)
        self._node.style.height = len(lines) + 1
        self._visible = True

    def clear(self) -> None:
        self.update([])
