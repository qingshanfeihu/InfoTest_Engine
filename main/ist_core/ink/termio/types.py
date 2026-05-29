"""ANSI Parser - Semantic Types.

These types represent the semantic meaning of ANSI escape sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class NamedColor(str, Enum):
    BLACK = "black"
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    BLUE = "blue"
    MAGENTA = "magenta"
    CYAN = "cyan"
    WHITE = "white"
    BRIGHT_BLACK = "brightBlack"
    BRIGHT_RED = "brightRed"
    BRIGHT_GREEN = "brightGreen"
    BRIGHT_YELLOW = "brightYellow"
    BRIGHT_BLUE = "brightBlue"
    BRIGHT_MAGENTA = "brightMagenta"
    BRIGHT_CYAN = "brightCyan"
    BRIGHT_WHITE = "brightWhite"


@dataclass(frozen=True, slots=True)
class NamedColorValue:
    type: Literal["named"] = "named"
    name: NamedColor = NamedColor.WHITE


@dataclass(frozen=True, slots=True)
class IndexedColor:
    index: int = 0
    type: Literal["indexed"] = "indexed"


@dataclass(frozen=True, slots=True)
class RGBColor:
    r: int = 0
    g: int = 0
    b: int = 0
    type: Literal["rgb"] = "rgb"
