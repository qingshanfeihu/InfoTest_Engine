"""LLM endpoint detection helpers shared across the codebase.

Only depends on stdlib — no heavy imports.
"""

from __future__ import annotations

# Substrings that identify endpoints supporting the ``thinking`` parameter
# (MiMo / XiaoMi / DeepSeek).
_THINKING_ENDPOINT_KEYWORDS: tuple[str, ...] = ("mimo", "xiaomi", "deepseek")


def supports_thinking_toggle(url: str) -> bool:
    """Return True if *url* points to an endpoint that accepts ``thinking``."""
    u = (url or "").lower()
    return any(k in u for k in _THINKING_ENDPOINT_KEYWORDS)
