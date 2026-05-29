"""Declared cursor — component-level cursor positioning for IME.

Components declare where the terminal cursor should be placed.
The render loop writes a CUP sequence to position the real cursor there.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dom import DOMElement, Rect
from .termio.csi import cursor_position


@dataclass(slots=True)
class CursorDeclaration:
    """A cursor position declaration from a component."""
    node: DOMElement
    relative_x: int = 0
    relative_y: int = 0
    active: bool = True


class CursorManager:
    """Manages declared cursor positions from components.

    The active declaration determines where the terminal's real cursor
    is placed after each render frame — IME candidates follow this.
    """

    def __init__(self) -> None:
        self._declaration: CursorDeclaration | None = None

    def declare(self, node: DOMElement, x: int, y: int, *, active: bool = True) -> None:
        """Declare cursor position relative to a node."""
        if active:
            self._declaration = CursorDeclaration(node=node, relative_x=x, relative_y=y, active=True)
        elif self._declaration and self._declaration.node is node:
            self._declaration = None

    def clear(self, node: DOMElement | None = None) -> None:
        """Clear cursor declaration."""
        if node is None or (self._declaration and self._declaration.node is node):
            self._declaration = None

    def get_absolute_position(self) -> tuple[int, int] | None:
        """Get absolute terminal cursor position (0-indexed).

        Walks up the node tree to compute absolute position from
        the declared relative position + node's layout rect.
        """
        decl = self._declaration
        if decl is None or not decl.active:
            return None

        abs_x = decl.relative_x
        abs_y = decl.relative_y

        node: DOMElement | None = decl.node
        while node is not None:
            rect = node.rect
            abs_x += rect.x
            abs_y += rect.y
            
            if node.style.border_style:
                abs_x += 1
                abs_y += 1
            abs_x += node.style.padding_left
            abs_y += node.style.padding_top
            node = node.parent

        return (abs_x, abs_y)

    def get_cursor_sequence(self) -> str:
        """Get ANSI CUP sequence to position terminal cursor.

        Returns empty string if no active declaration.
        """
        pos = self.get_absolute_position()
        if pos is None:
            return ""
        x, y = pos
        return cursor_position(y + 1, x + 1)
