"""CSI (Control Sequence Introducer) sequence generation.

Port of cc-haha src/ink/termio/csi.ts.
"""

from __future__ import annotations

from .ansi import ESC, SEP


def csi(params: str) -> str:
    """Generate a CSI sequence: ESC [ <params>."""
    return f"{ESC}[{params}"


def cursor_position(row: int, col: int) -> str:
    """CUP — move cursor to absolute position (1-indexed)."""
    return csi(f"{row}{SEP}{col}H")


def cursor_up(n: int = 1) -> str:
    return csi(f"{n}A")


def cursor_down(n: int = 1) -> str:
    return csi(f"{n}B")


def cursor_forward(n: int = 1) -> str:
    return csi(f"{n}C")


def cursor_backward(n: int = 1) -> str:
    return csi(f"{n}D")


def cursor_horizontal_absolute(col: int = 1) -> str:
    """CHA — move cursor to column (1-indexed)."""
    return csi(f"{col}G")


def erase_in_display(mode: int = 0) -> str:
    """ED — 0=below, 1=above, 2=all, 3=scrollback."""
    return csi(f"{mode}J")


def erase_in_line(mode: int = 0) -> str:
    """EL — 0=right, 1=left, 2=all."""
    return csi(f"{mode}K")


def scroll_up(n: int = 1) -> str:
    return csi(f"{n}S")


def scroll_down(n: int = 1) -> str:
    return csi(f"{n}T")


def is_csi_final(code: int) -> bool:
    """CSI final byte: 0x40-0x7E (@ through ~)."""
    return 0x40 <= code <= 0x7E


def is_csi_param(code: int) -> bool:
    """CSI parameter byte: 0x30-0x3F (0-9 : ; < = > ?)."""
    return 0x30 <= code <= 0x3F


def is_csi_intermediate(code: int) -> bool:
    """CSI intermediate byte: 0x20-0x2F (space through /)."""
    return 0x20 <= code <= 0x2F
