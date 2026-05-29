"""Line-range text reader with bounded memory for large files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


FAST_PATH_MAX_SIZE = 10 * 1024 * 1024


@dataclass(frozen=True)
class TextRange:
    lines: list[str]
    total_lines: int
    offset: int
    limit: int


def _clean_line(line: str) -> str:
    return line.rstrip("\n").rstrip("\r")


def read_text_range(path: Path, *, offset: int, limit: int) -> TextRange:
    """Read a numbered line range while still counting total lines."""
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 200), 1000))
    end = offset + limit

    stat = path.stat()
    if stat.st_size < FAST_PATH_MAX_SIZE:
        text = path.read_text(encoding="utf-8", errors="replace")
        raw_lines = text.splitlines()
        selected = [f"{idx + 1}: {line}" for idx, line in enumerate(raw_lines[offset:end], start=offset)]
        return TextRange(lines=selected, total_lines=len(raw_lines), offset=offset, limit=limit)

    selected: list[str] = []
    total = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for idx, line in enumerate(handle):
            total = idx + 1
            if offset <= idx < end:
                selected.append(f"{idx + 1}: {_clean_line(line)}")
    return TextRange(lines=selected, total_lines=total, offset=offset, limit=limit)
