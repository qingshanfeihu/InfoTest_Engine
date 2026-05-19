"""Transcript — scrollable message list component.

Displays the conversation history (AI responses, user inputs, tool calls).
Supports overflow scroll with sticky-scroll (auto-pin to bottom).
"""

from __future__ import annotations

from ..dom import DOMElement, NodeType, TextNode, create_element, create_text


class Transcript:
    """Scrollable transcript area showing conversation messages."""

    def __init__(self) -> None:
        self._node = create_element(NodeType.BOX)
        self._node.style.flex_grow = 1
        self._node.style.overflow = "scroll"
        self._node.sticky_scroll = True
        self._messages: list[str] = []

    @property
    def node(self) -> DOMElement:
        return self._node

    def append_message(self, text: str, *, style: str = "") -> None:
        """Append a message to the transcript."""
        self._messages.append(text)
        msg_node = create_text(text)
        self._node.append_child(msg_node)
        # Auto-scroll to bottom
        if self._node.sticky_scroll:
            self._scroll_to_bottom()

    def update_last_message(self, text: str) -> None:
        """Update the last message (for streaming tokens)."""
        if self._node.children:
            last = self._node.children[-1]
            if isinstance(last, TextNode):
                last.set_value(text)
                if self._messages:
                    self._messages[-1] = text

    def clear(self) -> None:
        """Clear all messages."""
        self._node.clear_children()
        self._messages.clear()
        self._node.scroll_top = 0

    def scroll_up(self, lines: int = 3) -> None:
        self._node.scroll_top = max(0, self._node.scroll_top - lines)

    def scroll_down(self, lines: int = 3) -> None:
        self._node.scroll_top += lines

    def update_message_at(self, idx: int, text: str) -> None:
        """Update a specific message by index."""
        if 0 <= idx < len(self._messages):
            self._messages[idx] = text
            children = list(self._node.children)
            if idx < len(children):
                child = children[idx]
                if isinstance(child, TextNode):
                    child.set_value(text)

    def replace_range(self, start_idx: int, count: int, new_lines: list[str]) -> None:
        """Replace `count` messages starting at `start_idx` with `new_lines`."""
        self._messages[start_idx:start_idx + count] = new_lines
        # Rebuild DOM children
        self._node.clear_children()
        for msg in self._messages:
            self._node.append_child(create_text(msg))
        if self._node.sticky_scroll:
            self._scroll_to_bottom()

    def message_count(self) -> int:
        """Return number of messages in transcript."""
        return len(self._messages)

    def _scroll_to_bottom(self) -> None:
        content_h = len(self._messages)
        viewport_h = self._node.rect.height if self._node.rect.height > 0 else 20
        self._node.scroll_top = max(0, content_h - viewport_h)
