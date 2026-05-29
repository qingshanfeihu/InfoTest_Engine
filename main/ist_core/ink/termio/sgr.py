"""SGR (Select Graphic Rendition) Parser.

Parses SGR parameters and applies them to a TextStyle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .types import NamedColor

NAMED_COLORS: list[str] = [
    "black", "red", "green", "yellow",
    "blue", "magenta", "cyan", "white",
    "brightBlack", "brightRed", "brightGreen", "brightYellow",
    "brightBlue", "brightMagenta", "brightCyan", "brightWhite",
]

UNDERLINE_STYLES: list[str] = [
    "none", "single", "double", "curly", "dotted", "dashed",
]


@dataclass
class TextStyle:
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: str = "none"
    blink: bool = False
    inverse: bool = False
    hidden: bool = False
    strikethrough: bool = False
    overline: bool = False
    fg: dict[str, Any] = field(default_factory=lambda: {"type": "default"})
    bg: dict[str, Any] = field(default_factory=lambda: {"type": "default"})
    underline_color: dict[str, Any] = field(default_factory=lambda: {"type": "default"})


def default_style() -> TextStyle:
    return TextStyle()


@dataclass
class _Param:
    value: int | None = None
    subparams: list[int] = field(default_factory=list)
    colon: bool = False


def _parse_params(s: str) -> list[_Param]:
    if s == "":
        return [_Param(value=0)]
    result: list[_Param] = []
    current = _Param()
    num = ""
    in_sub = False

    for i in range(len(s) + 1):
        c = s[i] if i < len(s) else None
        if c == ";" or c is None:
            n = int(num) if num else None
            if in_sub:
                if n is not None:
                    current.subparams.append(n)
            else:
                current.value = n
            result.append(current)
            current = _Param()
            num = ""
            in_sub = False
        elif c == ":":
            n = int(num) if num else None
            if not in_sub:
                current.value = n
                current.colon = True
                in_sub = True
            else:
                if n is not None:
                    current.subparams.append(n)
            num = ""
        elif c is not None and "0" <= c <= "9":
            num += c
    return result


def _parse_extended_color(params: list[_Param], idx: int) -> dict[str, Any] | None:
    if idx >= len(params):
        return None
    p = params[idx]
    if p.colon and len(p.subparams) >= 1:
        if p.subparams[0] == 5 and len(p.subparams) >= 2:
            return {"type": "indexed", "index": p.subparams[1]}
        if p.subparams[0] == 2 and len(p.subparams) >= 4:
            off = 1 if len(p.subparams) >= 5 else 0
            return {"type": "rgb", "r": p.subparams[1 + off], "g": p.subparams[2 + off], "b": p.subparams[3 + off]}
    if idx + 1 >= len(params):
        return None
    nxt = params[idx + 1]
    if nxt.value == 5 and idx + 2 < len(params) and params[idx + 2].value is not None:
        return {"type": "indexed", "index": params[idx + 2].value}
    if nxt.value == 2 and idx + 4 < len(params):
        r, g, b = params[idx + 2].value, params[idx + 3].value, params[idx + 4].value
        if r is not None and g is not None and b is not None:
            return {"type": "rgb", "r": r, "g": g, "b": b}
    return None


def apply_sgr(param_str: str, style: TextStyle) -> TextStyle:
    """Apply SGR parameters to a TextStyle, returning the updated style."""
    params = _parse_params(param_str)
    s = TextStyle(
        bold=style.bold, dim=style.dim, italic=style.italic,
        underline=style.underline, blink=style.blink, inverse=style.inverse,
        hidden=style.hidden, strikethrough=style.strikethrough,
        overline=style.overline,
        fg=dict(style.fg), bg=dict(style.bg),
        underline_color=dict(style.underline_color),
    )
    i = 0
    while i < len(params):
        p = params[i]
        code = p.value if p.value is not None else 0

        if code == 0:
            s = default_style()
        elif code == 1:
            s.bold = True
        elif code == 2:
            s.dim = True
        elif code == 3:
            s.italic = True
        elif code == 4:
            s.underline = UNDERLINE_STYLES[p.subparams[0]] if p.colon and p.subparams else "single"
        elif code in (5, 6):
            s.blink = True
        elif code == 7:
            s.inverse = True
        elif code == 8:
            s.hidden = True
        elif code == 9:
            s.strikethrough = True
        elif code == 21:
            s.underline = "double"
        elif code == 22:
            s.bold = False
            s.dim = False
        elif code == 23:
            s.italic = False
        elif code == 24:
            s.underline = "none"
        elif code == 25:
            s.blink = False
        elif code == 27:
            s.inverse = False
        elif code == 28:
            s.hidden = False
        elif code == 29:
            s.strikethrough = False
        elif code == 53:
            s.overline = True
        elif code == 55:
            s.overline = False
        elif 30 <= code <= 37:
            s.fg = {"type": "named", "name": NAMED_COLORS[code - 30]}
        elif code == 39:
            s.fg = {"type": "default"}
        elif 40 <= code <= 47:
            s.bg = {"type": "named", "name": NAMED_COLORS[code - 40]}
        elif code == 49:
            s.bg = {"type": "default"}
        elif 90 <= code <= 97:
            s.fg = {"type": "named", "name": NAMED_COLORS[code - 90 + 8]}
        elif 100 <= code <= 107:
            s.bg = {"type": "named", "name": NAMED_COLORS[code - 100 + 8]}
        elif code == 38:
            c = _parse_extended_color(params, i)
            if c:
                s.fg = c
                i += 1 if p.colon else (3 if c["type"] == "indexed" else 5)
                continue
        elif code == 48:
            c = _parse_extended_color(params, i)
            if c:
                s.bg = c
                i += 1 if p.colon else (3 if c["type"] == "indexed" else 5)
                continue
        elif code == 58:
            c = _parse_extended_color(params, i)
            if c:
                s.underline_color = c
                i += 1 if p.colon else (3 if c["type"] == "indexed" else 5)
                continue
        elif code == 59:
            s.underline_color = {"type": "default"}
        i += 1
    return s
