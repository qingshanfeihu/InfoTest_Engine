"""OSC (Operating System Command) sequence generation.

Port of cc-haha src/ink/termio/osc.ts. Three-tier clipboard write:
1. fire-and-forget native tool (pbcopy / wl-copy / xclip / xsel / clip)
2. tmux load-buffer (in tmux only) — sync, returns DCS-passthrough OSC 52
3. raw OSC 52 emission to stdout — caller writes the returned string

The returned string is what the caller should write to stdout. tmux
passthrough is preferred when available so the outer terminal also
receives the OSC 52; otherwise a raw OSC 52 is returned.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import threading
from typing import Literal

from .ansi import BEL, ESC, ESC_TYPE, SEP

OSC_PREFIX = ESC + chr(ESC_TYPE.OSC)
ST = ESC + "\\"


def osc(*parts: str | int) -> str:
    """Generate an OSC sequence: ESC ] p1;p2;...;pN BEL."""
    return f"{OSC_PREFIX}{SEP.join(str(p) for p in parts)}{BEL}"


def wrap_for_multiplexer(sequence: str) -> str:
    """Wrap escape sequence for tmux/screen passthrough."""
    if os.environ.get("TMUX"):
        escaped = sequence.replace("\x1b", "\x1b\x1b")
        return f"\x1bPtmux;{escaped}\x1b\\"
    if os.environ.get("STY"):
        return f"\x1bP{sequence}\x1b\\"
    return sequence


ClipboardPath = Literal["native", "tmux-buffer", "osc52"]


def get_clipboard_path() -> ClipboardPath:
    """Determine best clipboard write path. cc-haha gates pbcopy on
    SSH_CONNECTION (not SSH_TTY) — tmux panes inherit SSH_TTY forever
    after local reattach, but SSH_CONNECTION is in tmux's default
    update-environment set and gets cleared on local attach."""
    native_available = (
        sys.platform == "darwin" and not os.environ.get("SSH_CONNECTION")
    )
    if native_available:
        return "native"
    if os.environ.get("TMUX"):
        return "tmux-buffer"
    return "osc52"


def _tmux_passthrough(payload: str) -> str:
    """Wrap a sequence in tmux's DCS passthrough.

    Inner ESCs must be doubled. Requires `set -g allow-passthrough on`
    in ~/.tmux.conf; without it tmux silently drops the whole DCS.
    """
    return f"{ESC}Ptmux;{payload.replace(ESC, ESC + ESC)}{ST}"


# Linux clipboard tool: None = not yet probed; "" = none available.
# Probe order: wl-copy (Wayland) → xclip (X11) → xsel (X11 fallback).
# Cached after first attempt so repeated mouse-ups skip the probe chain.
_linux_copy: str | None = None


def _reset_linux_copy_cache() -> None:
    """Internal — for tests."""
    global _linux_copy
    _linux_copy = None


def _spawn_copy(argv: list[str], text: str) -> bool:
    """Pipe `text` into argv via stdin, fire-and-forget. Returns True if
    the subprocess was launched (not whether it succeeded)."""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except (FileNotFoundError, PermissionError, OSError):
        return False

    def _feed() -> None:
        try:
            assert proc.stdin is not None
            proc.stdin.write(text.encode("utf-8", errors="replace"))
            proc.stdin.close()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    threading.Thread(target=_feed, daemon=True).start()
    return True


def _copy_native_async(text: str) -> None:
    """Shell out to a native clipboard utility as a safety net for OSC 52.
    Only called when not in an SSH session. Fire-and-forget."""
    global _linux_copy
    if sys.platform == "darwin":
        _spawn_copy(["pbcopy"], text)
        return
    if sys.platform.startswith("linux"):
        if _linux_copy == "":
            return
        if _linux_copy == "wl-copy":
            _spawn_copy(["wl-copy"], text)
            return
        if _linux_copy == "xclip":
            _spawn_copy(["xclip", "-selection", "clipboard"], text)
            return
        if _linux_copy == "xsel":
            _spawn_copy(["xsel", "--clipboard", "--input"], text)
            return
        # Probe in order; cache the winner.
        for tool, args in (
            ("wl-copy", []),
            ("xclip", ["-selection", "clipboard"]),
            ("xsel", ["--clipboard", "--input"]),
        ):
            if _spawn_copy([tool, *args], text):
                _linux_copy = tool
                return
        _linux_copy = ""  # nothing worked
        return
    if sys.platform == "win32":
        # clip.exe is always available on Windows. Unicode handling is
        # imperfect (system locale) but good enough for a fallback.
        _spawn_copy(["clip"], text)
        return


def _tmux_load_buffer_sync(text: str) -> bool:
    """Run `tmux load-buffer -w -` synchronously. Returns True on success.
    -w (tmux 3.2+) propagates to the outer terminal's clipboard via
    tmux's own OSC 52. -w is dropped for iTerm2 (LC_TERMINAL=iTerm2)
    because tmux's emission crashes iTerm2 sessions over SSH."""
    if not os.environ.get("TMUX"):
        return False
    args = (
        ["load-buffer", "-"]
        if os.environ.get("LC_TERMINAL") == "iTerm2"
        else ["load-buffer", "-w", "-"]
    )
    try:
        result = subprocess.run(
            ["tmux", *args],
            input=text.encode("utf-8", errors="replace"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def set_clipboard(text: str) -> str:
    """Write text to the system clipboard via the best available path
    and return an OSC 52 sequence the caller should also write to stdout.

    Three layers (matches cc-haha setClipboard):
      1. Local native tool (pbcopy/wl-copy/xclip/xsel/clip) —
         fire-and-forget unless we're over SSH (SSH_CONNECTION set), in
         which case OSC 52 is the right path so we skip native.
      2. tmux load-buffer (sync, 2 s timeout) — when running inside tmux,
         loads the buffer so prefix+] paste works even if the outer
         terminal disabled OSC 52.
      3. Raw OSC 52 returned for the caller to write. When inside tmux,
         we DCS-passthrough-wrap it so the outer terminal still receives
         the clipboard sequence (assuming allow-passthrough on).
    """
    if not text:
        return ""

    b64 = base64.b64encode(text.encode("utf-8", errors="replace")).decode("ascii")
    raw = f"{ESC}]52;c;{b64}{BEL}"

    # Native first (fire-and-forget) so a quick focus-switch after
    # selecting doesn't race pbcopy.
    if not os.environ.get("SSH_CONNECTION"):
        _copy_native_async(text)

    tmux_loaded = _tmux_load_buffer_sync(text)

    if tmux_loaded:
        return _tmux_passthrough(raw)
    return raw
