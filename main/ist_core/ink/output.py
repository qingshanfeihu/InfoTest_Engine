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
                # 软换行续接列:保留本逻辑行的前导缩进,让续接对齐到内容列而非回到 op.x。
                # ⎿ 工具结果块的续接行有 5 空格缩进 → 软换行后仍对齐到内容列(和 Claude Code 一致);
                # ⎿ 块外的普通行无缩进(indent=0)→ 续接回 op.x(第 0 列)从头另起。
                # 这正是"长行尾字(如'线')跑到最左列"的根因:旧实现一律回 op.x,丢掉了缩进。
                n_lead = len(line) - len(line.lstrip(" "))
                wrap_col = op.x + n_lead
                if wrap_col >= self._width:  # 极端缩进吃满整行宽 → 退回 op.x 防止续接无处可写
                    wrap_col = op.x
                for ch in line:
                    if col >= self._width:
                        col = wrap_col
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
                    # 行末宽字符防溢出:最后一列放不下 2 列宽的字符——物理终端会把它
                    # wrap 到下一行开头(污染下一行第 0-1 列)或渲染半字,而网格只记了
                    # 头 cell → 模型与终端永久失同步、增量 diff 修不回(V轮乱码实证:
                    # 输入行开头被上一行行尾的字符/数字污染)。改为:头 cell 位置留空格、
                    # 字符落到下一行,网格与物理逐格一致。
                    if w == 2 and col + 1 >= self._width:
                        self._screen.set_cell(col, row_y, 0, current_style)
                        col = wrap_col
                        row_y += 1
                        if row_y >= self._height:
                            break
                        if op.clip_rect:
                            cx, cy, cw, ch_h = op.clip_rect
                            if not (cx <= col < cx + cw and cy <= row_y < cy + ch_h):
                                col += w
                                continue
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


# 宽度判定统一走 string_width.char_width——此前这里维护了一份缺 east_asian_width
# W/F 兜底(且少 0x3400-0x4DBF 等段)的副本,与 wrapped_row_count(布局算行数)对部分
# 宽字符判宽不一致:布局认 2 列、写格认 1 列(或反之)即列错位,diff 增量渲染下错位
# 永不自愈(V轮乱码取证的成因之一)。单一事实源。
from .string_width import char_width as _char_width  # noqa: E402
