"""DOM Tree — lightweight node tree for the Python Ink renderer.

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
    
    flex_direction: str = "column"
    flex_grow: float = 0
    flex_shrink: float = 1
    flex_basis: str | int = "auto"
    width: int | str | None = None
    height: int | str | None = None
    min_width: int | None = None
    min_height: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    
    padding_top: int = 0
    padding_bottom: int = 0
    padding_left: int = 0
    padding_right: int = 0
    
    margin_top: int = 0
    margin_bottom: int = 0
    margin_left: int = 0
    margin_right: int = 0
    
    border_style: str | None = None
    border_color: str | None = None
    
    overflow: str = "visible"
    
    display: str = "flex"


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
    wrap: str = "wrap"


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
        
        self.scroll_top: int = 0
        self.scroll_height: int = 0
        self.scroll_viewport_height: int = 0
        self.sticky_scroll: bool = False
        
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


def _sanitize_text_value(value: str) -> str:
    """TextNode 值的控制字符规格化(2026-07-17 team4 实弹:ask 面板题干携带设备回显
    原文里的 ``\\t``——char_width 按 1 列布局、真实终端却跳 8 列制表位且不清跳过区,
    屏上出现前帧字符碎片叠影「www.local.co0.md」「域名命中回…册与」)。

    ``\\t``→单空格(确定性 1 列,布局与终端一致);``\\r`` 剥除(回车会把光标拉回行首
    覆盖已渲染内容,是同族破坏者)。``\\n`` 保留(wrapped_rows 原生支持)。快速路径:
    无控制字符时零拷贝零开销(set_value 每帧高频)。"""
    if "\t" in value or "\r" in value:
        return value.replace("\t", " ").replace("\r", "")
    return value


class TextNode(DOMNode):
    """Text node — leaf node containing a string value."""

    def __init__(self, value: str = "") -> None:
        super().__init__("#text")
        self.value = _sanitize_text_value(value)
        self._rows_cache: tuple[int, int] | None = None  # (width, 行数):软换行行数缓存

    def set_value(self, value: str) -> None:
        value = _sanitize_text_value(value)
        if self.value != value:
            self.value = value
            self._rows_cache = None
            self.mark_dirty()

    def wrapped_rows(self, width: int) -> int:
        """本节点在给定列宽下占的视觉行数(含 \\n + 软换行),按 width 缓存。

        渲染每帧 + 内容高度都要对全部子节点求行数来定位/算滚动高度;若每次重算
        ``string_width`` 在大 transcript(几千行)下会让滚轮翻页特别卡 → 缓存。
        """
        c = self._rows_cache
        if c is not None and c[0] == width:
            return c[1]
        from .string_width import wrapped_row_count
        n = wrapped_row_count(self.value, width) if self.value else 1
        self._rows_cache = (width, n)
        return n


def create_element(node_type: NodeType = NodeType.BOX, **attrs: Any) -> DOMElement:
    """Factory for creating DOM elements."""
    el = DOMElement(node_type)
    for k, v in attrs.items():
        el.attributes[k] = v
    return el


def create_text(value: str = "") -> TextNode:
    """Factory for creating text nodes."""
    return TextNode(value)
