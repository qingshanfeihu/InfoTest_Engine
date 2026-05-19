"""PromptInput: 风格输入行 widget。


- 单行 ``> {input_text}{cursor}`` 渲染
- 光标用反白（reverse video）一格表示，cursor 位置可在中间
- Backspace / Left / Right / Home / End / Ctrl+A / Ctrl+E 标准编辑
- Enter 提交（emit Submitted message）
- ``height: 1``（也是单行 row）

不用 Textual 内置 ``Input`` widget——它的 padding/border 行为和 不一致，
且字符渲染依赖 widget 内部 _value_text，黑底黑字看不见。

Mounting in IstApp::

    self._input = PromptInput(id="prompt")
    yield self._input

Receiving submission::

    @on(PromptInput.Submitted)
    def on_prompt_submitted(self, event: PromptInput.Submitted) -> None:
        self._submit_user_input(event.value)
"""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class PromptInput(Static):
    """Single-line input widget — PromptInput / TextInput equivalent."""

    DEFAULT_CSS = """
    PromptInput {
        height: 1;
        background: transparent;
        color: $text;
        padding: 0 1;
    }
    """

    class Submitted(Message):
        """Posted when user presses Enter on a non-empty input."""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class Changed(Message):
        """Posted whenever input value changes (any keystroke)."""
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    value: reactive[str] = reactive("")
    cursor: reactive[int] = reactive(0)

    NEWLINE_GLYPH = "↵"

    def __init__(self, *, placeholder: str = "", id: str | None = None) -> None:
        super().__init__("", id=id)
        self._placeholder = placeholder

    def on_mount(self) -> None:
        self.can_focus = True
        self.focus()
        self._refresh()

    # -- Public API for parent app ----------------------------------------

    def set_value(self, text: str, *, cursor: int | None = None) -> None:
        self.value = text
        self.cursor = len(text) if cursor is None else max(0, min(cursor, len(text)))
        self._refresh()

    def clear(self) -> None:
        self.set_value("")

    def insert(self, ch: str) -> None:
        self.value = self.value[: self.cursor] + ch + self.value[self.cursor :]
        self.cursor += len(ch)
        self.post_message(self.Changed(self.value))
        self._refresh()

    # -- Reactive watchers --------------------------------------------------

    def watch_value(self, _old: str, _new: str) -> None:
        self._refresh()

    def watch_cursor(self, _old: int, _new: int) -> None:
        self._refresh()

    # -- Key handling -------------------------------------------------------

    async def on_paste(self, event: events.Paste) -> None:
        """剪贴板粘贴：把 text 插入到 cursor 位置。

        等价：PromptInput.tsx 的 onPaste handler（imagePaste.ts:PASTE_THRESHOLD
        分图片 / 文本两路）。MVP 只处理文本。
        """
        text = event.text or ""
        if not text:
            return
        event.stop()
        # 多行 paste：把 \r\n / \r 都标准化为 \n，再用 ↵ 占位符（提交时还原）
        text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", self.NEWLINE_GLYPH)
        self.value = self.value[: self.cursor] + text + self.value[self.cursor :]
        self.cursor += len(text)
        self.post_message(self.Changed(self.value))
        self._refresh()

    async def on_key(self, event: events.Key) -> None:
        key = event.key

        # 直接调 app 上的 action（绕过 binding 系统，因为 widget Tab default 是 focus_next）
        if key == "tab":
            event.stop()
            self.app.action_tab_complete()
            return
        if key == "up":
            event.stop()
            self.app.action_history_up()
            return
        if key == "down":
            event.stop()
            self.app.action_history_down()
            return
        if key == "ctrl+r":
            event.stop()
            self.app.action_history_search()
            return
        if key == "ctrl+j":
            event.stop()
            self.app.action_newline_in_input()
            return
        if key == "shift+enter":
            event.stop()
            self.app.action_newline_in_input()
            return
        if key == "escape":
            event.stop()
            self.app.action_esc()
            return
        if key == "ctrl+c":
            event.stop()
            self.app.action_ctrl_c()
            return
        if key == "ctrl+d":
            event.stop()
            self.app.action_exit_now()
            return

        if key == "enter":
            event.stop()
            self.post_message(self.Submitted(self.value))
            self.clear()
            return
        if key == "backspace":
            event.stop()
            if self.cursor > 0:
                self.value = self.value[: self.cursor - 1] + self.value[self.cursor :]
                self.cursor -= 1
                self.post_message(self.Changed(self.value))
            return
        if key == "delete":
            event.stop()
            if self.cursor < len(self.value):
                self.value = self.value[: self.cursor] + self.value[self.cursor + 1 :]
                self.post_message(self.Changed(self.value))
            return
        if key == "left":
            event.stop()
            if self.cursor > 0:
                self.cursor -= 1
            return
        if key == "right":
            event.stop()
            if self.cursor < len(self.value):
                self.cursor += 1
            return
        if key in ("home", "ctrl+a"):
            event.stop()
            self.cursor = 0
            return
        if key in ("end", "ctrl+e"):
            event.stop()
            self.cursor = len(self.value)
            return
        # 普通字符插入 — 包括多字符（粘贴时某些 driver 会把整段作为一次 Key 事件）
        ch = event.character
        if ch is not None and ch and not _is_control_chars(ch):
            event.stop()
            # 多字符 paste 时把 \n 等转 ↵
            if "\n" in ch or "\r" in ch:
                ch = ch.replace("\r\n", "\n").replace("\r", "\n").replace("\n", self.NEWLINE_GLYPH)
            self.insert(ch)
            return
        # 未识别键：不 stop，让事件继续冒泡

    # -- Render -------------------------------------------------------------

    def _refresh(self) -> None:
        text = self.value
        cur = self.cursor
        # Textual Rich markup: [reverse]X[/]
        if not text and self._placeholder:
            # Placeholder dim color when input empty
            display = f"[dim]> {self._placeholder}[/dim]"
        else:
            # 单行渲染：> {before}{cursor_char}{after}
            before = text[:cur].replace("\n", self.NEWLINE_GLYPH)
            at_cursor = text[cur] if cur < len(text) else " "
            after = text[cur + 1 :].replace("\n", self.NEWLINE_GLYPH)
            # 反白光标
            display = f"> {before}[reverse]{at_cursor}[/reverse]{after}"
        self.update(display)

    def on_focus(self) -> None:
        self.add_class("focused")
        self._refresh()

    def on_blur(self) -> None:
        self.remove_class("focused")
        self._refresh()


def _is_control_chars(s: str) -> bool:
    """``s`` 是否全是控制字符（不可打印）。"""
    if not s:
        return True
    # 允许 \n / \t（粘贴常见）
    return all(not c.isprintable() and c not in ("\n", "\t", "\r") for c in s)
