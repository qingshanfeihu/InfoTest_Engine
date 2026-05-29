"""ESC Sequence Parser.

"""

from __future__ import annotations

from typing import Any


def parse_esc(chars: str) -> dict[str, Any] | None:
    """Parse a simple ESC sequence (chars after ESC, not including ESC)."""
    if not chars:
        return None

    first = chars[0]

    if first == "c":
        return {"type": "reset"}

    if first == "7":
        return {"type": "cursor", "action": {"type": "save"}}

    if first == "8":
        return {"type": "cursor", "action": {"type": "restore"}}

    if first == "D":
        return {"type": "cursor", "action": {"type": "move", "direction": "down", "count": 1}}

    if first == "M":
        return {"type": "cursor", "action": {"type": "move", "direction": "up", "count": 1}}

    if first == "E":
        return {"type": "cursor", "action": {"type": "nextLine", "count": 1}}

    if first == "H":
        return None

    if first in "()" and len(chars) >= 2:
        return None

    return {"type": "unknown", "sequence": f"\x1b{chars}"}
