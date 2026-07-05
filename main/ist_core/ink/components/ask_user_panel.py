"""AskUserPanel — 钉在输入框横线上方的交互式问答面板。

仿 PlanPanel：ask_user 触发时，IstInkApp 把 AskUserSession 的渲染行整块
塞进本面板（独立 Box 节点），**不再 append 到 transcript**——所以问答选项不会
随对话滚走，始终固定在输入框上方（底部 permission dialog 位置）。

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
        # 顶部留一空行与上方对话隔开。用单空格而非空串:布局估算(_estimate_content_height)
        # 对空串 continue 记 0 行、渲染(wrapped_rows)却占 1 行,不一致会把末行挤出面板。
        self._node.append_child(create_text(" "))
        # TextNode 直挂面板节点 + auto 高度(不包 height=1 的行盒):布局引擎按软换行后的
        # 真实行数估高、渲染层对 BOX 直挂的 TextNode 原生折行——长选项行(ask_user 的
        # label+description 常超终端宽)不再被单行行盒截断(2026-07-02 实测决策面板选项断半句)。
        for ln in lines:
            self._node.append_child(create_text(ln))
        self._node.style.height = None
        self._visible = True

    def clear(self) -> None:
        self.update([])
