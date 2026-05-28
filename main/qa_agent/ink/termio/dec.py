"""DEC (Digital Equipment Corporation) Private Mode Sequences.

Port of Claude Code src/ink/termio/dec.ts.
"""

from __future__ import annotations

from .csi import csi


class DEC:
    """DEC private mode numbers."""
    CURSOR_VISIBLE = 25
    ALT_SCREEN = 47
    ALT_SCREEN_CLEAR = 1049
    MOUSE_NORMAL = 1000
    MOUSE_BUTTON = 1002
    MOUSE_ANY = 1003
    MOUSE_SGR = 1006
    FOCUS_EVENTS = 1004
    BRACKETED_PASTE = 2004
    SYNCHRONIZED_UPDATE = 2026


def decset(mode: int) -> str:
    """CSI ? N h — set mode."""
    return csi(f"?{mode}h")


def decreset(mode: int) -> str:
    """CSI ? N l — reset mode."""
    return csi(f"?{mode}l")


# Pre-generated sequences
BSU = decset(DEC.SYNCHRONIZED_UPDATE)
ESU = decreset(DEC.SYNCHRONIZED_UPDATE)
EBP = decset(DEC.BRACKETED_PASTE)
DBP = decreset(DEC.BRACKETED_PASTE)
EFE = decset(DEC.FOCUS_EVENTS)
DFE = decreset(DEC.FOCUS_EVENTS)
SHOW_CURSOR = decset(DEC.CURSOR_VISIBLE)
HIDE_CURSOR = decreset(DEC.CURSOR_VISIBLE)
ENTER_ALT_SCREEN = decset(DEC.ALT_SCREEN_CLEAR)
EXIT_ALT_SCREEN = decreset(DEC.ALT_SCREEN_CLEAR)

ENABLE_MOUSE_TRACKING = (
    decset(DEC.MOUSE_NORMAL)
    + decset(DEC.MOUSE_BUTTON)
    + decset(DEC.MOUSE_ANY)
    + decset(DEC.MOUSE_SGR)
)
DISABLE_MOUSE_TRACKING = (
    decreset(DEC.MOUSE_SGR)
    + decreset(DEC.MOUSE_ANY)
    + decreset(DEC.MOUSE_BUTTON)
    + decreset(DEC.MOUSE_NORMAL)
)

# Wheel-only tracking: 1000 reports button press / release / wheel only,
# 1006 switches to SGR encoding. We deliberately skip 1002 (button-motion
# drag) and 1003 (any-motion). When 1002/1003 are active, terminals like
# macOS Terminal.app and tmux stop forwarding drag-selection to their own
# native text-selection engine — copy-on-select / drag-to-select stops
# working without forcing the user to hold a modifier key. With only
# 1000+1006 enabled, the terminal still emits wheel events to the app
# but lets click-drag fall through to native selection on most terminals.
ENABLE_WHEEL_ONLY_TRACKING = (
    decset(DEC.MOUSE_NORMAL)
    + decset(DEC.MOUSE_SGR)
)
DISABLE_WHEEL_ONLY_TRACKING = (
    decreset(DEC.MOUSE_SGR)
    + decreset(DEC.MOUSE_NORMAL)
)
