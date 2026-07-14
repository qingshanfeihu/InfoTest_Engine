"""Keyboard event parsing — terminal input to semantic key events.

Parses raw terminal input (from tokenizer) into KeyPress events.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Literal

from .termio.tokenize import Token, Tokenizer

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class KeyPress:
    """A parsed keyboard event."""
    key: str
    char: str = ""
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    meta: bool = False


@dataclass(slots=True)
class MouseEvent:
    """A parsed mouse event (SGR format)."""
    type: Literal["press", "release", "move", "wheel"]
    button: int = 0
    x: int = 0
    y: int = 0
    shift: bool = False
    alt: bool = False
    ctrl: bool = False


@dataclass(slots=True)
class PasteEvent:
    """Bracketed paste content."""
    text: str = ""


@dataclass(slots=True)
class UploadEvent:
    """Out-of-band file-upload signal.

    Web Terminal 上传文件后，前端经 ws 发结构化 upload 消息，web_server 把它
    包成自定义 OSC 序列 ``ESC ] 7001 ; <base64(filename)> BEL`` 写进 PTY，
    本解析器识别后产出该事件。文件名走 base64 → 不受空格 / 引号 / 中文 / 分隔符
    干扰，彻底替代"在自由文本里用正则猜文件名"的脆弱方案。
    """
    filename: str = ""


@dataclass(slots=True)
class SwitchConversationEvent:
    """Web 前端切换对话信号。

    web_server 收到前端 ``switch_conversation`` 消息后，激活对话并通过
    OSC 7003 序列通知 TUI 切换上下文。
    """
    conversation_id: str = ""


InputEvent = KeyPress | MouseEvent | PasteEvent | UploadEvent | SwitchConversationEvent



_CSI_KEYS: dict[str, str] = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end",
    "1~": "home", "2~": "insert", "3~": "delete",
    "4~": "end", "5~": "pageup", "6~": "pagedown",
    "Z": "shift+tab",
}


_SS3_KEYS: dict[str, str] = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end",
    "P": "f1", "Q": "f2", "R": "f3", "S": "f4",
}

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"

# 自定义 OSC 上传信号：ESC ] 7001 ; <base64(utf-8 filename)> (BEL | ESC \)
# 7001 是私有 OSC 码（标准 OSC 用 0-9/52 等，7001 不与之冲突）。
_OSC_UPLOAD_CODE = "7001"
# OSC 7003: 前端切换对话信号，payload 为 base64(conversation_id)
_OSC_SWITCH_CONV_CODE = "7003"


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
        
        events = _coalesce_alt_enter(events)
        
        
        
        
        events = coalesce_paste_runs(events)
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


def _coalesce_alt_enter(events: list[InputEvent]) -> list[InputEvent]:
    """Merge a stray ``escape`` + ``enter`` pair into a single ``shift+enter``.

    The tokenizer treats ``\\x1b\\r`` as ``ESC`` (terminating an empty escape
    sequence) followed by a literal ``CR``, so users pressing Shift+Enter (or
    Option+Enter on macOS terminals that emit ESC+CR) would otherwise see the
    escape clear the prompt and the enter immediately submit. Collapsing them
    here keeps the alt-enter / shift-enter equivalence working with whatever
    the terminal happens to send, without touching the lower-level tokenizer.
    """
    if len(events) < 2:
        return events
    out: list[InputEvent] = []
    i = 0
    while i < len(events):
        ev = events[i]
        nxt = events[i + 1] if i + 1 < len(events) else None
        if (
            isinstance(ev, KeyPress)
            and ev.key == "escape"
            and isinstance(nxt, KeyPress)
            and nxt.key == "enter"
        ):
            out.append(KeyPress(key="shift+enter", shift=True))
            i += 2
            continue
        out.append(ev)
        i += 1
    return out


def coalesce_paste_runs(events: list[InputEvent]) -> list[InputEvent]:
    """Synthesize a ``PasteEvent`` from a run of printable / LF KeyPress
    events that arrived in a single input batch.

    Bracketed paste mode (``\\x1b[?2004h``) is supposed to wrap pasted
    content in ``ESC [ 200 ~`` ... ``ESC [ 201 ~`` so the parser emits one
    ``PasteEvent``. Some terminals / multiplexers / SSH paths drop the
    markers, leaving a raw stream of characters where ``LF`` (0x0A) is
    parsed as ``ctrl+j``. Without this coalescer, those pastes flood the
    prompt with individual ``↵`` markers (visible single-line overflow)
    and bypass the ``[Pasted text #N +K lines]`` placeholder folding.

    Heuristic: a contiguous run of (printable char | ctrl+j) ≥ 4 chars
    that contains at least one ctrl+j newline is treated as a paste.
    A pure-text run without newlines must be ≥ 64 chars to qualify —
    real typing rarely fills 64 chars in a single ``os.read`` while a
    paste comfortably does.

    A bare single ``ctrl+j`` (Shift+Enter / Ctrl+J for in-input newline)
    falls below both thresholds and stays a normal KeyPress.
    """
    if not events:
        return events
    out: list[InputEvent] = []
    i = 0
    n = len(events)
    while i < n:
        ev = events[i]
        if not isinstance(ev, KeyPress) or not _is_paste_run_char(ev):
            out.append(ev)
            i += 1
            continue
        
        chars: list[str] = []
        has_newline = False
        j = i
        while j < n:
            ev_j = events[j]
            if not isinstance(ev_j, KeyPress) or not _is_paste_run_char(ev_j):
                break
            if ev_j.key == "ctrl+j":
                chars.append("\n")
                has_newline = True
            else:
                
                chars.append(ev_j.char)
            j += 1
        
        run_len = j - i
        looks_like_paste = (has_newline and run_len >= 4) or run_len >= 64
        if looks_like_paste:
            out.append(PasteEvent(text="".join(chars)))
            i = j
        else:
            out.append(events[i])
            i += 1
    return out


def _is_paste_run_char(kp: KeyPress) -> bool:
    """Return True if this KeyPress could plausibly be part of a pasted
    text run (printable single character or LF-as-ctrl+j)."""
    if kp.key == "ctrl+j":
        return True
    return bool(kp.char) and len(kp.char) == 1 and kp.char.isprintable()


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
        
        letter = chr(code + 0x60)
        return KeyPress(key=f"ctrl+{letter}", ctrl=True, char=letter)
    return KeyPress(key=ch, char=ch)


def _parse_osc(body: str) -> InputEvent | None:
    """Parse an OSC sequence body (after ``ESC ]``).

    只识别自定义信号 ``7001;<base64>``（上传）和 ``7003;<base64>``（切换对话）。
    其他 OSC（标题设置等）忽略，返回 None。
    """
    # 去掉可能残留的终止符 BEL(\x07) 或 ST(\x1b\\)
    body = body.rstrip("\x07")
    if body.endswith("\x1b\\"):
        body = body[:-2]

    code, sep, payload = body.partition(";")
    if not sep:
        return None

    if code == _OSC_UPLOAD_CODE:
        try:
            filename = base64.b64decode(payload.encode("ascii")).decode("utf-8")
        except Exception:
            logger.warning("OSC upload payload 解码失败，忽略")
            return None
        filename = filename.strip()
        if not filename:
            return None
        return UploadEvent(filename=filename)

    if code == _OSC_SWITCH_CONV_CODE:
        try:
            conv_id = base64.b64decode(payload.encode("ascii")).decode("utf-8")
        except Exception:
            logger.warning("OSC switch_conversation payload 解码失败，忽略")
            return None
        conv_id = conv_id.strip()
        if not conv_id:
            return None
        return SwitchConversationEvent(conversation_id=conv_id)

    return None


def _parse_sequence(seq: str) -> InputEvent | None:
    """Parse an escape sequence into an InputEvent."""
    if not seq.startswith("\x1b"):
        return None


    if seq == PASTE_START:
        return None

    rest = seq[1:]

    # OSC 上传信号：ESC ] 7001 ; <base64> (BEL | ESC \)
    if rest.startswith("]"):
        return _parse_osc(rest[1:])


    if rest.startswith("["):
        return _parse_csi(rest[1:])

    
    if rest.startswith("O"):
        body = rest[1:]
        key = _SS3_KEYS.get(body)
        if key:
            return KeyPress(key=key)
        return None

    
    
    
    
    if rest in ("\r", "\n"):
        return KeyPress(key="shift+enter", shift=True)

    
    if len(rest) == 1:
        ch = rest[0]
        return KeyPress(key=f"alt+{ch}", char=ch, alt=True)

    return None


def _parse_csi(body: str) -> InputEvent | None:
    """Parse CSI sequence body (after ESC [)."""
    if not body:
        return None

    
    if body.startswith("<"):
        return _parse_sgr_mouse(body[1:])

    
    
    if body.endswith("u") and ";" in body:
        try:
            cp_str, mod_str = body[:-1].split(";", 1)
            cp = int(cp_str)
            mod = int(mod_str)
        except ValueError:
            cp = 0
            mod = 0
        
        if cp == 13 and (mod - 1) & 1:
            return KeyPress(key="shift+enter", shift=True)

    
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
        col = int(parts[1]) - 1
        row = int(parts[2]) - 1
    except ValueError:
        return None

    shift = bool(btn_code & 4)
    alt = bool(btn_code & 8)
    ctrl = bool(btn_code & 16)
    button = btn_code & 3

    if btn_code & 64:
        
        direction = btn_code & 1
        return MouseEvent(type="wheel", button=direction, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
    if btn_code & 32:
        return MouseEvent(type="move", button=button, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
    if is_release:
        return MouseEvent(type="release", button=button, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
    return MouseEvent(type="press", button=button, x=col, y=row, shift=shift, alt=alt, ctrl=ctrl)
