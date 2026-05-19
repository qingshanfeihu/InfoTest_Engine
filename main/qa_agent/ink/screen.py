"""Screen Buffer — double-buffered cell grid with diff engine.

Port of cc-haha src/ink/screen.ts.
Core data structures: CharPool, StylePool, Screen, diff algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CharPool:
    """String interning pool for characters (grapheme clusters).

    Shared across screens so interned IDs are valid across blit operations
    and diff can compare IDs as integers without string lookup.
    """

    def __init__(self) -> None:
        self._strings: list[str] = [" ", ""]  # 0=space, 1=empty(spacer)
        self._map: dict[str, int] = {" ": 0, "": 1}
        self._ascii: list[int] = [-1] * 128
        self._ascii[ord(" ")] = 0

    def intern(self, char: str) -> int:
        if len(char) == 1:
            code = ord(char)
            if code < 128:
                cached = self._ascii[code]
                if cached != -1:
                    return cached
                idx = len(self._strings)
                self._strings.append(char)
                self._ascii[code] = idx
                return idx
        existing = self._map.get(char)
        if existing is not None:
            return existing
        idx = len(self._strings)
        self._strings.append(char)
        self._map[char] = idx
        return idx

    def get(self, index: int) -> str:
        if 0 <= index < len(self._strings):
            return self._strings[index]
        return " "


class StylePool:
    """Style interning pool. Each unique style combination gets an integer ID.

    Bit 0 of the ID encodes whether the style has a visible effect on space
    characters (background, inverse, underline). This lets the renderer skip
    invisible spaces with a single bitmask check.
    """

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._styles: list[list[str]] = []
        self._transition_cache: dict[int, str] = {}
        self.none: int = self.intern([])

    def intern(self, codes: list[str]) -> int:
        key = "\0".join(codes) if codes else ""
        existing = self._ids.get(key)
        if existing is not None:
            return existing
        raw_id = len(self._styles)
        self._styles.append(codes[:] if codes else [])
        has_visible = any(_is_visible_on_space(c) for c in codes)
        encoded_id = (raw_id << 1) | (1 if has_visible else 0)
        self._ids[key] = encoded_id
        return encoded_id

    def get(self, encoded_id: int) -> list[str]:
        raw_id = encoded_id >> 1
        if 0 <= raw_id < len(self._styles):
            return self._styles[raw_id]
        return []

    def transition(self, from_id: int, to_id: int) -> str:
        if from_id == to_id:
            return ""
        cache_key = from_id * 0x100000 + to_id
        cached = self._transition_cache.get(cache_key)
        if cached is not None:
            return cached
        from_codes = self.get(from_id)
        to_codes = self.get(to_id)
        result = _diff_sgr(from_codes, to_codes)
        self._transition_cache[cache_key] = result
        return result


def _is_visible_on_space(code: str) -> bool:
    """Check if an SGR code produces visible effect on space characters."""
    return code in ("\x1b[7m", "\x1b[4m", "\x1b[9m", "\x1b[53m") or (
        code.startswith("\x1b[4") and code.endswith("m") and code != "\x1b[4m"
    ) or code.startswith("\x1b[48;")


def _diff_sgr(from_codes: list[str], to_codes: list[str]) -> str:
    """Generate minimal SGR transition from one style to another."""
    if not to_codes:
        return "\x1b[0m" if from_codes else ""
    if not from_codes:
        return "".join(to_codes)
    from_set = set(from_codes)
    to_set = set(to_codes)
    if from_set == to_set:
        return ""
    return "\x1b[0m" + "".join(to_codes)


# ---------------------------------------------------------------------------
# Screen Buffer
# ---------------------------------------------------------------------------

# Each cell is packed as 3 integers: char_id, style_id, hyperlink_id
# CellWidth markers for double-wide characters (CJK/emoji)
CELL_NORMAL = 0
CELL_WIDE = 1      # First column of a double-wide char
CELL_SPACER = 2    # Second column (placeholder, not rendered)


@dataclass(slots=True)
class Cell:
    char_id: int = 0       # interned character (CharPool)
    style_id: int = 0      # interned style (StylePool)
    hyperlink_id: int = 0  # interned hyperlink (0 = none)
    width: int = CELL_NORMAL
    soft_wrap: bool = False


class Screen:
    """2D cell grid representing one frame of terminal output.

    Supports double-buffering: render into one Screen, diff against previous.
    """

    def __init__(self, width: int, height: int, char_pool: CharPool, style_pool: StylePool) -> None:
        self.width = width
        self.height = height
        self.char_pool = char_pool
        self.style_pool = style_pool
        self._cells: list[list[Cell]] = [
            [Cell(char_id=0, style_id=style_pool.none) for _ in range(width)]
            for _ in range(height)
        ]
        self._soft_wrap_flags: list[bool] = [False] * height

    def reset(self) -> None:
        """Clear all cells to space with no style."""
        none = self.style_pool.none
        for row in self._cells:
            for cell in row:
                cell.char_id = 0
                cell.style_id = none
                cell.hyperlink_id = 0
                cell.width = CELL_NORMAL
                cell.soft_wrap = False
        for i in range(self.height):
            self._soft_wrap_flags[i] = False

    def set_cell(self, x: int, y: int, char_id: int, style_id: int, hyperlink_id: int = 0, width: int = CELL_NORMAL) -> None:
        """Set a single cell. Out-of-bounds writes are silently ignored."""
        if 0 <= x < self.width and 0 <= y < self.height:
            cell = self._cells[y][x]
            cell.char_id = char_id
            cell.style_id = style_id
            cell.hyperlink_id = hyperlink_id
            cell.width = width

    def get_cell(self, x: int, y: int) -> Cell:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self._cells[y][x]
        return Cell()

    def set_soft_wrap(self, y: int, value: bool) -> None:
        if 0 <= y < self.height:
            self._soft_wrap_flags[y] = value

    def get_soft_wrap(self, y: int) -> bool:
        if 0 <= y < self.height:
            return self._soft_wrap_flags[y]
        return False

    def resize(self, width: int, height: int) -> None:
        """Resize the screen, preserving content where possible."""
        none = self.style_pool.none
        new_cells: list[list[Cell]] = []
        for y in range(height):
            row: list[Cell] = []
            for x in range(width):
                if y < self.height and x < self.width:
                    row.append(self._cells[y][x])
                else:
                    row.append(Cell(char_id=0, style_id=none))
            new_cells.append(row)
        self._cells = new_cells
        new_wrap = [False] * height
        for y in range(min(height, self.height)):
            new_wrap[y] = self._soft_wrap_flags[y]
        self._soft_wrap_flags = new_wrap
        self.width = width
        self.height = height


# ---------------------------------------------------------------------------
# Diff Engine
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DiffOp:
    """A single diff operation: move cursor to (x,y) and write styled text."""
    x: int
    y: int
    content: str  # pre-rendered ANSI string for this span


def diff_screens(prev: Screen, curr: Screen, style_pool: StylePool, char_pool: CharPool) -> list[DiffOp]:
    """Compare two screens and produce minimal ANSI update operations.

    Only emits DiffOps for cells that changed between frames.
    """
    ops: list[DiffOp] = []
    height = min(prev.height, curr.height)
    width = min(prev.width, curr.width)

    for y in range(height):
        prev_row = prev._cells[y]
        curr_row = curr._cells[y]
        x = 0
        while x < width:
            pc = prev_row[x]
            cc = curr_row[x]
            if pc.char_id == cc.char_id and pc.style_id == cc.style_id and pc.hyperlink_id == cc.hyperlink_id:
                x += 1
                continue
            # Found a difference — collect contiguous changed span
            span_start = x
            buf: list[str] = []
            last_style_id = style_pool.none
            while x < width:
                pc2 = prev_row[x]
                cc2 = curr_row[x]
                if pc2.char_id == cc2.char_id and pc2.style_id == cc2.style_id and pc2.hyperlink_id == cc2.hyperlink_id:
                    break
                transition = style_pool.transition(last_style_id, cc2.style_id)
                buf.append(transition)
                buf.append(char_pool.get(cc2.char_id))
                last_style_id = cc2.style_id
                x += 1
            # Reset style at end of span
            if last_style_id != style_pool.none:
                buf.append("\x1b[0m")
            ops.append(DiffOp(x=span_start, y=y, content="".join(buf)))

    return ops
