"""PromptInput — single-line input component with IME cursor positioning.

Equivalent to the old Textual PromptInput widget, but uses the Python Ink
renderer's declared cursor system for proper IME candidate box positioning.
"""

from __future__ import annotations

from typing import Callable

from ..cursor import CursorManager
from ..dom import DOMElement, DOMNode, NodeType, TextNode, create_element, create_text


class PromptInput:
    """Single-line input with real terminal cursor for IME support."""

    def __init__(
        self,
        *,
        cursor_manager: CursorManager,
        on_submit: Callable[[str], None] | None = None,
        on_change: Callable[[str], None] | None = None,
        placeholder: str = "",
    ) -> None:
        self._cursor_mgr = cursor_manager
        self._on_submit = on_submit
        self._on_change = on_change
        self._placeholder = placeholder
        self._value = ""
        self._cursor_pos = 0
        self._node = create_element(NodeType.BOX)
        self._node.style.height = 1
        self._text_node = create_text("")
        self._node.append_child(self._text_node)
        self._refresh()

    @property
    def node(self) -> DOMElement:
        return self._node

    @property
    def value(self) -> str:
        return self._value

    @value.setter
    def value(self, v: str) -> None:
        self._value = v
        self._cursor_pos = min(self._cursor_pos, len(v))
        self._refresh()

    @property
    def cursor_pos(self) -> int:
        return self._cursor_pos

    def set_value(self, text: str, *, cursor: int | None = None) -> None:
        self._value = text
        self._cursor_pos = len(text) if cursor is None else max(0, min(cursor, len(text)))
        self._refresh()

    def clear(self) -> None:
        self.set_value("")

    def insert(self, ch: str) -> None:
        self._value = self._value[:self._cursor_pos] + ch + self._value[self._cursor_pos:]
        self._cursor_pos += len(ch)
        if self._on_change:
            self._on_change(self._value)
        self._refresh()

    def handle_key(self, key: str, char: str = "") -> bool:
        """Handle a key event. Returns True if consumed."""
        if key == "enter":
            if self._on_submit and self._value:
                self._on_submit(self._value)
                self.clear()
            return True
        if key == "backspace":
            if self._cursor_pos > 0:
                self._value = self._value[:self._cursor_pos - 1] + self._value[self._cursor_pos:]
                self._cursor_pos -= 1
                if self._on_change:
                    self._on_change(self._value)
                self._refresh()
            return True
        if key == "delete":
            if self._cursor_pos < len(self._value):
                self._value = self._value[:self._cursor_pos] + self._value[self._cursor_pos + 1:]
                if self._on_change:
                    self._on_change(self._value)
                self._refresh()
            return True
        if key == "left":
            if self._cursor_pos > 0:
                self._cursor_pos -= 1
                self._refresh()
            return True
        if key == "right":
            if self._cursor_pos < len(self._value):
                self._cursor_pos += 1
                self._refresh()
            return True
        if key in ("home", "ctrl+a"):
            self._cursor_pos = 0
            self._refresh()
            return True
        if key in ("end", "ctrl+e"):
            self._cursor_pos = len(self._value)
            self._refresh()
            return True
        if key == "ctrl+j":
            # Insert visual newline (↵) for multi-line input
            self.insert("↵")
            return True
        if key == "ctrl+u":
            # Kill line (clear input)
            self._value = ""
            self._cursor_pos = 0
            if self._on_change:
                self._on_change(self._value)
            self._refresh()
            return True
        # Printable character
        if char and len(char) == 1 and char.isprintable():
            self.insert(char)
            return True
        return False

    def handle_paste(self, text: str) -> None:
        """Handle bracketed paste."""
        clean = text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "↵")
        self.insert(clean)

    def _refresh(self) -> None:
        """Update the text node and cursor declaration."""
        from ..string_width import string_width

        if not self._value and self._placeholder:
            self._text_node.set_value(f"> {self._placeholder}")
        else:
            self._text_node.set_value(f"> {self._value}")
        # Cursor x = "> " prefix (2 cols) + display width of text before cursor
        text_before_cursor = self._value[:self._cursor_pos]
        cursor_x = 2 + string_width(text_before_cursor)
        self._cursor_mgr.declare(self._node, x=cursor_x, y=0)
