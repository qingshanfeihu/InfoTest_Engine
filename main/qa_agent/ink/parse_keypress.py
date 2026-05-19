"""Keyboard event parsing — terminal input to semantic key events.

Port of cc-haha src/ink/parse-keypress.ts (simplified).
Parses raw terminal input (from tokenizer) into KeyPress events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .termio.tokenize import Token, Tokenizer


@dataclass(slots=True)
class KeyPress:
    """A parsed keyboard event."""
    key: str  # "a", "enter", "up", "ctrl+c", "f1", etc.
    char: str = ""  # printable character (empty for special keys)
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False


@dataclass(slots=True)
class MouseEvent:
    """A parsed mouse event (SGR format)."""
    type: Literal["press", "release", "move", "wheel"]
    button: int = 0  # 0=left, 1=middle, 2=right
    x: int = 0
    y: int = 0
    shift: bool = False
    alt: bool = False
    ctrl: bool = False


@dataclass(slots=True)
class PasteEvent:
    """Bracketed paste content."""
    text: str = ""


InputEvent = KeyPress | MouseEvent | PasteEvent


# CSI sequence → key name mapping
_CSI_KEYS: dict[str, str] = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end",
    "1~": "home", "2~": "insert", "3~": "delete",
    "4~": "end", "5~": "pageup", "6~": "pagedown",
    "Z": "shift+tab",
}

# SS3 sequence → key name
_SS3_KEYS: dict[str, str] = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end",
    "P": "f1", "Q": "f2", "R": "f3", "S": "f4",
}

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"


class InputParser:
    """Parses raw terminal input into semantic InputEvents."""

    def __init__(self) -> None:
        self._tokenizer = Tokenizer(x10_mouse=True)
        self._in_paste = False
        self._paste_buf: list[str] = []

    def feed(self, data: str) -> list[InputEvent]:
        """Feed raw input data and return parsed events."""
        tokens = self._tokenizer.feed(data)
        events: list[InputEvent] = []
        for token in tokens:
            self._process_token(token, events)
        return events

    def _process_token(self, token: Token, events: list[InputEvent]) -> None:
        if self._in_paste:
            if token.type == "sequence" and token.value == PASTE_END:
                self._in_paste = False
                events.append(PasteEvent(text="".join(self._paste_buf)))
                self._paste_buf.clear()
            else:
                self._paste_buf.append(token.value)
            return

        if token.type == "sequence" and token.value == PASTE_START:
            self._in_paste = True
            return

        if token.type == "text":
            for ch in token.value:
                events.append(_parse_char(ch))
        elif token.type == "sequence":
            ev = _parse_sequence(token.value)
            if ev is not None:
                events.append(ev)


def _parse_char(ch: str) -> KeyPress:
    """Parse a single character into a KeyPress."""
    code = ord(ch)
    if code == 0x0D:
        return KeyPress(key="enter", char="\r")
    if code == 0x1B:
        return KeyPress(key="escape")
    if code == 0x09:
        return KeyPress(key="tab", char="\t")
    if code == 0x7F:
        return KeyPress(key="backspace")
    if code < 0x20:
        # Ctrl+letter: 0x01=ctrl+a, 0x02=ctrl+b, etc.
        letter = chr(code + 0x60)
        return KeyPress(key=f"ctrl+{letter}", ctrl=True, char=letter)
    return KeyPress(key=ch, char=ch)


def _parse_sequence(seq: str) -> InputEvent | None:
    """Parse an escape sequence into an InputEvent."""
    if not seq.startswith("\x1b"):
        return None

    # Bracketed paste
    if seq == PASTE_START:
        return None  # handled by state machine in InputParser

    rest = seq[1:]

    # CSI sequences: ESC [ ...
    if rest.startswith("["):
        return _parse_csi(rest[1:])

    # SS3 sequences: ESC O ...
    if rest.startswith("O"):
        body = rest[1:]
        key = _SS3_KEYS.get(body)
        if key:
            return KeyPress(key=key)
        return None

    # Alt+char: ESC + char
    if len(rest) == 1:
        ch = rest[0]
        return KeyPress(key=f"alt+{ch}", char=ch, alt=True)

    return None


def _parse_csi(body: str) -> InputEvent | None:
    """Parse CSI sequence body (after ESC [)."""
    if not body:
        return None

    # SGR mouse: < btn;col;row M/m
    if body.startswith("<"):
        return _parse_sgr_mouse(body[1:])

    # Function keys with modifiers: e.g. 1;5A = Ctrl+Up
    if ";" in body and body[-1:].isalpha():
        parts = body[:-1].split(";")
        final = body[-1]
        if len(parts) == 2:
            modifier = int(parts[1]) - 1 if parts[1].isdigit() else 0
            base_key = _CSI_KEYS.get(final, "")
            if not base_key:
                base_key = _CSI_KEYS.get(parts[0] + "~", final)
            if base_key:
                kp = KeyPress(key=base_key)
                if modifier & 1:
                    kp.shift = True
                    kp.key = f"shift+{kp.key}"
                if modifier & 2:
                    kp.alt = True
                    kp.key = f"alt+{kp.key}"
                if modifier & 4:
                    kp.ctrl = True
                    kp.key = f"ctrl+{kp.key}"
                return kp

    # Simple CSI: A, B, C, D, H, F, 2~, 3~, etc.
    key = _CSI_KEYS.get(body)
    if key:
        return KeyPress(key=key)

    return None


def _parse_sgr_mouse(body: str) -> MouseEvent | None:
    """Parse SGR mouse event: btn;col;row M/m."""
    if not body or body[-1] not in "Mm":
        return None
    is_release = body[-1] == "m"
    parts = body[:-1].split(";")
    if len(parts) != 3:
        return None
    try:
        btn_code = int(parts[0])
        col = int(parts[1]) - 1  # 0-indexed
        row = int(parts[2]) - 1
    except ValueError:
        return None

    shift = bool(btn_code & 4)
    alt = bool(btn_code & 8)
    ctrl = bool(btn_code & 16)
    button = btn_code & 3

    if btn_code & 64:
        # Wheel event
        direction = btn_code & 1  # 0=up, 1=down
        return MouseEvent(type="wheel", button=direction, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
    if btn_code & 32:
        return MouseEvent(type="move", button=button, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
    if is_release:
        return MouseEvent(type="release", button=button, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
    return MouseEvent(type="press", button=button, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
