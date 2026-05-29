"""Output — operation collector for render tree.

Collects write/blit/clear/clip operations from the render tree,
then applies them to a Screen buffer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .screen import (
    CELL_NORMAL,
    CELL_SPACER,
    CELL_WIDE,
    CharPool,
    Screen,
    StylePool,
)
from .string_width import string_width


@dataclass(slots=True)
class WriteOp:
    type: str = "write"
    x: int = 0
    y: int = 0
    text: str = ""
    style_id: int = 0
    clip_rect: tuple[int, int, int, int] | None = None


@dataclass(slots=True)
class ClearOp:
    type: str = "clear"
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class ClipOp:
    type: str = "clip"
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


Operation = WriteOp | ClearOp | ClipOp


class Output:
    """Collects render operations and applies them to a Screen buffer.

    Usage:
        out = Output(width, height, char_pool, style_pool, screen)
        out.write(x, y, "Hello", style_id)
        out.write(x, y+1, "World", style_id)
        out.apply()  # flush all ops to screen
    """

    def __init__(
        self,
        width: int,
        height: int,
        char_pool: CharPool,
        style_pool: StylePool,
        screen: Screen,
    ) -> None:
        self._width = width
        self._height = height
        self._char_pool = char_pool
        self._style_pool = style_pool
        self._screen = screen
        self._ops: list[Operation] = []
        self._clip_stack: list[tuple[int, int, int, int]] = []

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def write(self, x: int, y: int, text: str, style_id: int = 0) -> None:
        """Write text at position. Respects current clip region."""
        clip = self._clip_stack[-1] if self._clip_stack else None
        self._ops.append(WriteOp(x=x, y=y, text=text, style_id=style_id, clip_rect=clip))

    def clear(self, x: int, y: int, width: int, height: int) -> None:
        """Clear a rectangular region to spaces."""
        self._ops.append(ClearOp(x=x, y=y, width=width, height=height))

    def push_clip(self, x: int, y: int, width: int, height: int) -> None:
        """Push a clip rectangle onto the stack."""
        self._clip_stack.append((x, y, width, height))

    def pop_clip(self) -> None:
        """Pop the most recent clip rectangle."""
        if self._clip_stack:
            self._clip_stack.pop()

    def apply(self) -> None:
        """Apply all collected operations to the screen buffer."""
        self._screen.reset()
        for op in self._ops:
            if isinstance(op, WriteOp):
                self._apply_write(op)
            elif isinstance(op, ClearOp):
                self._apply_clear(op)
        self._ops.clear()

    def _apply_write(self, op: WriteOp) -> None:
        """Render text into screen cells, handling multi-line, wrapping, clipping, and inline ANSI."""
        import re
        
        
        _ANSI_RE = re.compile(r'(\x1b\[[0-9;]*m)')
        segments = _ANSI_RE.split(op.text)

        row_y = op.y
        col = op.x
        current_style = op.style_id

        for segment in segments:
            if not segment:
                continue
            
            if segment.startswith("\x1b[") and segment.endswith("m"):
                
                if segment == "\x1b[0m":
                    current_style = op.style_id
                else:
                    
                    base_codes = self._style_pool.get(op.style_id)
                    current_style = self._style_pool.intern(base_codes + [segment])
                continue

            
            lines = segment.split("\n")
            for li, line in enumerate(lines):
                if li > 0:
                    row_y += 1
                    col = op.x
                if row_y >= self._height:
                    break
                for ch in line:
                    if col >= self._width:
                        col = op.x
                        row_y += 1
                        if row_y >= self._height:
                            break
                    if row_y < 0 or col < 0:
                        col += 1
                        continue
                    if op.clip_rect:
                        cx, cy, cw, ch_h = op.clip_rect
                        if not (cx <= col < cx + cw and cy <= row_y < cy + ch_h):
                            col += 1
                            continue
                    w = _char_width(ch)
                    char_id = self._char_pool.intern(ch)
                    self._screen.set_cell(col, row_y, char_id, current_style)
                    if w == 2 and col + 1 < self._width:
                        self._screen.set_cell(col + 1, row_y, 1, current_style, width=CELL_SPACER)
                    col += w
            if row_y >= self._height:
                break
        

    def _apply_clear(self, op: ClearOp) -> None:
        """Clear a region to spaces with no style."""
        none = self._style_pool.none
        for dy in range(op.height):
            row_y = op.y + dy
            if row_y < 0 or row_y >= self._height:
                continue
            for dx in range(op.width):
                col = op.x + dx
                if 0 <= col < self._width:
                    self._screen.set_cell(col, row_y, 0, none)


def _char_width(ch: str) -> int:
    """Quick character width (1 or 2). CJK and some emoji are width 2."""
    code = ord(ch)
    if code < 0x1100:
        return 1
    if (
        (0x1100 <= code <= 0x115F)
        or (0x2E80 <= code <= 0x9FFF)
        or (0xAC00 <= code <= 0xD7AF)
        or (0xF900 <= code <= 0xFAFF)
        or (0xFE10 <= code <= 0xFE6F)
        or (0xFF01 <= code <= 0xFF60)
        or (0xFFE0 <= code <= 0xFFE6)
        or (0x1F300 <= code <= 0x1F9FF)
        or (0x20000 <= code <= 0x2FA1F)
    ):
        return 2
    return 1
