"""Screen Buffer — double-buffered cell grid with diff engine.

Port of Claude Code src/ink/screen.ts.
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
        # Selection overlay (Claude Code withSelectionBg). Cleared on
        # set_selection_bg() so a theme switch invalidates stale entries.
        self._selection_bg_codes: list[str] = ["\x1b[48;5;238m"]
        self._selection_bg_cache: dict[int, int] = {}

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

    # ------------------------------------------------------------------
    # Selection overlay — Claude Code withSelectionBg port
    # ------------------------------------------------------------------

    def set_selection_bg(self, codes: list[str] | None) -> None:
        """Configure the selection-highlight background SGR codes.

        Pass an empty list / None to fall back to inverse-style behavior
        (the cache is cleared either way so a theme change invalidates
        old entries).
        """
        new_codes = list(codes) if codes else []
        if new_codes == self._selection_bg_codes:
            return
        self._selection_bg_codes = new_codes
        self._selection_bg_cache.clear()

    def with_selection_bg(self, base_id: int) -> int:
        """Return a style id that REPLACES base_id's bg with the selection
        bg while preserving fg / bold / italic / dim / underline / etc.

        Matches Claude Code's withSelectionBg: filter out any existing bg
        codes (\\x1b[49m reset, \\x1b[48;... explicit bg) and any inverse
        (\\x1b[27m reset, \\x1b[7m set), then append the selection bg.
        Cache by base_id so on drag the only work per cell is a dict
        lookup + style_id write.
        """
        cached = self._selection_bg_cache.get(base_id)
        if cached is not None:
            return cached
        sel_bg = self._selection_bg_codes
        if not sel_bg:
            # No theme bg configured — fall back to inverse so the overlay
            # still renders (Claude Code withInverse path).
            kept = [c for c in self.get(base_id) if c != "\x1b[7m" and c != "\x1b[27m"]
            kept.append("\x1b[7m")
            new_id = self.intern(kept)
            self._selection_bg_cache[base_id] = new_id
            return new_id
        kept = [
            c for c in self.get(base_id)
            if not _is_bg_or_inverse_code(c)
        ]
        kept.extend(sel_bg)
        new_id = self.intern(kept)
        self._selection_bg_cache[base_id] = new_id
        return new_id

    def clear_selection_bg_cache(self) -> None:
        self._selection_bg_cache.clear()


def _is_bg_or_inverse_code(code: str) -> bool:
    """Return True for SGR codes that set/reset background or inverse.

    We want with_selection_bg to drop these so the selection bg wins.
    Includes:
      - \\x1b[49m  (default bg reset)
      - \\x1b[48;...m (explicit bg, 256-color or RGB)
      - \\x1b[40m..\\x1b[47m (8-color bg)
      - \\x1b[100m..\\x1b[107m (bright bg)
      - \\x1b[7m / \\x1b[27m  (inverse on/off)
    """
    if code in ("\x1b[49m", "\x1b[7m", "\x1b[27m"):
        return True
    if code.startswith("\x1b[48;"):
        return True
    if code.startswith("\x1b[4") and code.endswith("m") and len(code) == 5:
        # \x1b[40m .. \x1b[47m
        digit = code[3]
        if digit.isdigit() and "0" <= digit <= "7":
            return True
    if code.startswith("\x1b[10") and code.endswith("m") and len(code) == 6:
        # \x1b[100m .. \x1b[107m
        digit = code[4]
        if digit.isdigit() and "0" <= digit <= "7":
            return True
    return False


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
        # Per-cell noSelect bitmap (True = exclude from selection copy +
        # highlight). Marked by gutter / sigil widgets via mark_no_select.
        self.no_select: list[list[bool]] = [
            [False] * width for _ in range(height)
        ]
        # Per-row soft-wrap continuation marker (Claude Code screen.softWrap).
        # softWrap[r] = N > 0 means row r is a wrap continuation of row r-1
        # AND row r-1's written content ends at absolute col N (exclusive).
        # 0 means row r starts a new logical line. Read by selection's
        # extractRowText/getSelectedText to join wrapped rows back into
        # logical lines and to know where padding starts on the prior row.
        self.soft_wrap_starts_at: list[int] = [0] * height

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
            self.soft_wrap_starts_at[i] = 0
        for row in self.no_select:
            for x in range(len(row)):
                row[x] = False

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

    def set_soft_wrap_continuation(self, y: int, content_end_col: int) -> None:
        """Mark row y as a soft-wrap continuation; content_end_col is the
        EXCLUSIVE column where the previous row's written content ends
        (Claude Code softWrap[y] semantics). Pass 0 to clear."""
        if 0 <= y < self.height:
            self.soft_wrap_starts_at[y] = max(0, content_end_col)

    def mark_no_select(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Mark a rectangular region [x0..x1] × [y0..y1] (inclusive) as
        noSelect — those cells are skipped by selection copy + highlight.
        Out-of-bounds is silently clamped."""
        x_lo = max(0, min(x0, x1))
        x_hi = min(self.width - 1, max(x0, x1))
        y_lo = max(0, min(y0, y1))
        y_hi = min(self.height - 1, max(y0, y1))
        for y in range(y_lo, y_hi + 1):
            row = self.no_select[y]
            for x in range(x_lo, x_hi + 1):
                row[x] = True

    def is_no_select(self, x: int, y: int) -> bool:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.no_select[y][x]
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
        new_starts = [0] * height
        new_no_sel: list[list[bool]] = [[False] * width for _ in range(height)]
        for y in range(min(height, self.height)):
            new_wrap[y] = self._soft_wrap_flags[y]
            new_starts[y] = self.soft_wrap_starts_at[y]
            old_row = self.no_select[y]
            new_row = new_no_sel[y]
            for x in range(min(width, self.width)):
                new_row[x] = old_row[x]
        self._soft_wrap_flags = new_wrap
        self.soft_wrap_starts_at = new_starts
        self.no_select = new_no_sel
        self.width = width
        self.height = height


def set_cell_style_id(screen: Screen, x: int, y: int, style_id: int) -> None:
    """Replace the style_id of cell (x, y) without touching char/hyperlink/width.

    Port of Claude Code setCellStyleId. Used by apply_selection_overlay to swap
    in the selection-bg style; the diff engine will pick up the change as
    a normal cell update.
    """
    if 0 <= x < screen.width and 0 <= y < screen.height:
        screen._cells[y][x].style_id = style_id


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
