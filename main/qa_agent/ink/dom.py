"""DOM Tree — lightweight node tree for the Python Ink renderer.

Port of cc-haha src/ink/dom.ts (simplified).
No React reconciler — uses a declarative Python component model instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class NodeType(str, Enum):
    ROOT = "ink-root"
    BOX = "ink-box"
    TEXT = "ink-text"
    RAW_ANSI = "ink-raw-ansi"


@dataclass
class Styles:
    """Layout and visual styles for a DOM node."""
    # Flexbox layout
    flex_direction: str = "column"  # "row" | "column"
    flex_grow: float = 0
    flex_shrink: float = 1
    flex_basis: str | int = "auto"
    width: int | str | None = None
    height: int | str | None = None
    min_width: int | None = None
    min_height: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    # Padding
    padding_top: int = 0
    padding_bottom: int = 0
    padding_left: int = 0
    padding_right: int = 0
    # Margin
    margin_top: int = 0
    margin_bottom: int = 0
    margin_left: int = 0
    margin_right: int = 0
    # Border
    border_style: str | None = None  # "single"|"double"|"round"|"bold"
    border_color: str | None = None
    # Overflow
    overflow: str = "visible"  # "visible"|"hidden"|"scroll"
    # Display
    display: str = "flex"  # "flex"|"none"


@dataclass
class TextStyles:
    """Text-specific styles (inherited by children)."""
    color: str | None = None
    background_color: str | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    inverse: bool = False
    wrap: str = "wrap"  # "wrap"|"truncate"|"truncate-end"


@dataclass
class Rect:
    """Computed layout rectangle."""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class DOMNode:
    """Base class for all DOM nodes."""

    def __init__(self, node_type: NodeType | str) -> None:
        self.node_type = node_type
        self.parent: DOMElement | None = None
        self.style = Styles()
        self.rect = Rect()
        self.dirty = True

    def mark_dirty(self) -> None:
        self.dirty = True
        if self.parent:
            self.parent.mark_dirty()


class DOMElement(DOMNode):
    """Element node — can have children, styles, and layout."""

    def __init__(self, node_type: NodeType = NodeType.BOX) -> None:
        super().__init__(node_type)
        self.children: list[DOMNode] = []
        self.text_styles = TextStyles()
        self.attributes: dict[str, Any] = {}
        # Scroll state
        self.scroll_top: int = 0
        self.scroll_height: int = 0
        self.scroll_viewport_height: int = 0
        self.sticky_scroll: bool = False
        # Visibility
        self.is_hidden: bool = False

    def append_child(self, child: DOMNode) -> None:
        child.parent = self
        self.children.append(child)
        self.mark_dirty()

    def remove_child(self, child: DOMNode) -> None:
        if child in self.children:
            self.children.remove(child)
            child.parent = None
            self.mark_dirty()

    def insert_before(self, child: DOMNode, ref: DOMNode | None) -> None:
        child.parent = self
        if ref is None or ref not in self.children:
            self.children.append(child)
        else:
            idx = self.children.index(ref)
            self.children.insert(idx, child)
        self.mark_dirty()

    def clear_children(self) -> None:
        for child in self.children:
            child.parent = None
        self.children.clear()
        self.mark_dirty()


class TextNode(DOMNode):
    """Text node — leaf node containing a string value."""

    def __init__(self, value: str = "") -> None:
        super().__init__("#text")
        self.value = value

    def set_value(self, value: str) -> None:
        if self.value != value:
            self.value = value
            self.mark_dirty()


def create_element(node_type: NodeType = NodeType.BOX, **attrs: Any) -> DOMElement:
    """Factory for creating DOM elements."""
    el = DOMElement(node_type)
    for k, v in attrs.items():
        el.attributes[k] = v
    return el


def create_text(value: str = "") -> TextNode:
    """Factory for creating text nodes."""
    return TextNode(value)
