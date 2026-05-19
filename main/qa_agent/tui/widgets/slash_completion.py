"""SlashCompletion：footer pill 风格的 slash 命令补全。

照搬  ``findSlashCommandPositions`` 的行为：
- 输入 ``/`` 触发显示候选
- 输入更多字符过滤候选
- Tab 选中第一个填到输入框（不立即执行）
- 点击外部 / Backspace 清空 ``/`` 时隐藏

MVP：单行 Static，候选用 ``·`` 分隔（footer pill 视觉）。

注：用 ``height: 1 / height: 0`` 切换可见性；``display: none`` 在 Textual 0.89
对 dock 子元素行为不稳定。
"""

from __future__ import annotations

from textual.widgets import Static

from main.qa_agent.tui.slash_commands import filter_completions


class SlashCompletion(Static):
    """Footer pill 风格的补全候选条。"""

    DEFAULT_CSS = """
    SlashCompletion {
        dock: bottom;
        height: 0;
        background: $boost;
        color: $accent;
        padding: 0 1;
    }
    SlashCompletion.visible {
        height: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._current_input = ""

    def update_for_input(self, text: str) -> int:
        """根据当前输入框内容刷新候选条。返回候选数量。"""
        self._current_input = text
        if not text.startswith("/"):
            self._hide()
            return 0
        completions = filter_completions(text, limit=8)
        if not completions:
            self._hide()
            return 0
        bits = [f"/{c.name}" for c in completions]
        self.update("  ".join(bits) + "    [Tab to fill · Enter to run]")
        self.add_class("visible")
        return len(completions)

    def first_completion(self) -> str | None:
        """返回当前过滤后的第一个候选命令（Tab 触发用）。"""
        if not self._current_input.startswith("/"):
            return None
        completions = filter_completions(self._current_input, limit=1)
        if not completions:
            return None
        return f"/{completions[0].name}"

    def _hide(self) -> None:
        self.update("")
        self.remove_class("visible")
