"""Geometry utilities for layout.

"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Point:
    x: int = 0
    y: int = 0


@dataclass(slots=True)
class Size:
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class Rectangle:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.width and self.y <= py < self.y + self.height

    def intersect(self, other: "Rectangle") -> "Rectangle":
        x1 = max(self.x, other.x)
        y1 = max(self.y, other.y)
        x2 = min(self.x + self.width, other.x + other.width)
        y2 = min(self.y + self.height, other.y + other.height)
        if x2 <= x1 or y2 <= y1:
            return Rectangle(0, 0, 0, 0)
        return Rectangle(x1, y1, x2 - x1, y2 - y1)


def union_rect(a: Rectangle, b: Rectangle) -> Rectangle:
    if a.width == 0 and a.height == 0:
        return b
    if b.width == 0 and b.height == 0:
        return a
    x = min(a.x, b.x)
    y = min(a.y, b.y)
    right = max(a.x + a.width, b.x + b.width)
    bottom = max(a.y + a.height, b.y + b.height)
    return Rectangle(x, y, right - x, bottom - y)
