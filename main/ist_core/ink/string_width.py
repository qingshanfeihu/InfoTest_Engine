"""String width calculation for terminal display.

Handles CJK, emoji, and other double-wide characters.
"""

from __future__ import annotations

import unicodedata


def string_width(s: str) -> int:
    """Calculate the display width of a string in terminal columns."""
    width = 0
    for ch in s:
        width += char_width(ch)
    return width


def char_width(ch: str) -> int:
    """Get the display width of a single character (1 or 2)."""
    if not ch:
        return 0
    code = ord(ch[0])
    if code < 0x1100:
        return 1
    if (
        (0x1100 <= code <= 0x115F)
        or (0x2329 <= code <= 0x232A)
        or (0x2E80 <= code <= 0x303E)
        or (0x3040 <= code <= 0x33BF)
        or (0x3400 <= code <= 0x4DBF)
        or (0x4E00 <= code <= 0x9FFF)
        or (0xA000 <= code <= 0xA4CF)
        or (0xAC00 <= code <= 0xD7AF)
        or (0xF900 <= code <= 0xFAFF)
        or (0xFE10 <= code <= 0xFE6F)
        or (0xFF01 <= code <= 0xFF60)
        or (0xFFE0 <= code <= 0xFFE6)
        or (0x1F300 <= code <= 0x1F9FF)
        or (0x20000 <= code <= 0x2FA1F)
        or (0x30000 <= code <= 0x3134F)
    ):
        return 2
    ea = unicodedata.east_asian_width(ch[0])
    if ea in ("W", "F"):
        return 2
    return 1
