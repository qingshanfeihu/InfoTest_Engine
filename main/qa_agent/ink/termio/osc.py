"""OSC (Operating System Command) sequence generation.

Port of cc-haha src/ink/termio/osc.ts.
"""

from __future__ import annotations

import base64
import os
import subprocess
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
    """Determine best clipboard write path."""
    import sys
    native_available = (
        sys.platform == "darwin" and not os.environ.get("SSH_CONNECTION")
    )
    if native_available:
        return "native"
    if os.environ.get("TMUX"):
        return "tmux-buffer"
    return "osc52"


def set_clipboard(text: str) -> None:
    """Write text to system clipboard."""
    path = get_clipboard_path()
    if path == "native":
        subprocess.run(["pbcopy"], input=text.encode(), check=False)
    elif path == "tmux-buffer":
        subprocess.run(
            ["tmux", "load-buffer", "-"], input=text.encode(), check=False,
        )
    else:
        encoded = base64.b64encode(text.encode()).decode()
        seq = osc(52, "c", encoded)
        import sys
        sys.stdout.write(wrap_for_multiplexer(seq))
        sys.stdout.flush()
