"""InkApp — main render loop for the Python Ink renderer.

Port of cc-haha src/ink/ink.tsx (core render loop).
Ties together: DOM tree, layout, render, screen buffer, diff, terminal IO.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from typing import Any, Callable

from .cursor import CursorManager
from .dom import DOMElement, NodeType, Rect, create_element
from .layout.engine import compute_layout
from .log_update import render_frame, render_full
from .output import Output
from .parse_keypress import InputEvent, InputParser
from .render import render_tree
from .screen import CharPool, Screen, StylePool
from .termio.dec import (
    DBP,
    DFE,
    EBP,
    EFE,
    ENTER_ALT_SCREEN,
    EXIT_ALT_SCREEN,
    HIDE_CURSOR,
    SHOW_CURSOR,
)
from .termio.csi import erase_in_display
from .termio.terminal import Terminal


class InkApp:
    """Main application class — manages render loop and terminal state.

    Usage:
        app = InkApp()
        app.root.append_child(...)
        app.start()
        # ... handle input events via app.on_input ...
        app.stop()
    """

    def __init__(
        self,
        *,
        alt_screen: bool = True,
        mouse: bool = False,
    ) -> None:
        self._terminal = Terminal()
        self._alt_screen = alt_screen
        self._mouse = mouse

        # Thread safety for render
        self._render_lock = threading.Lock()
        self._last_render_time = 0.0

        # Pools (shared across frames)
        self._char_pool = CharPool()
        self._style_pool = StylePool()

        # Double-buffered screens
        self._width = self._terminal.columns
        self._height = self._terminal.rows
        self._prev_screen = Screen(self._width, self._height, self._char_pool, self._style_pool)
        self._curr_screen = Screen(self._width, self._height, self._char_pool, self._style_pool)

        # DOM root
        self.root = create_element(NodeType.ROOT)
        self.root.style.flex_direction = "column"

        # Cursor
        self.cursor = CursorManager()

        # Input
        self._input_parser = InputParser()
        self._on_input: Callable[[InputEvent], None] | None = None

        # Render scheduling
        self._render_pending = False
        self._running = False
        self._input_thread: threading.Thread | None = None

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def on_input(self) -> Callable[[InputEvent], None] | None:
        return self._on_input

    @on_input.setter
    def on_input(self, handler: Callable[[InputEvent], None] | None) -> None:
        self._on_input = handler

    def start(self) -> None:
        """Enter terminal UI mode and start render loop."""
        self._running = True
        self._terminal.set_raw_mode(True)

        init_seq = ""
        if self._alt_screen:
            init_seq += ENTER_ALT_SCREEN
        init_seq += HIDE_CURSOR + EBP + EFE
        init_seq += erase_in_display(2)
        self._terminal.write(init_seq)

        # Handle terminal resize
        signal.signal(signal.SIGWINCH, self._on_resize)

        # Start input reader thread
        self._input_thread = threading.Thread(
            target=self._read_input, daemon=True, name="ink-input",
        )
        self._input_thread.start()

        # Initial render
        self.render()

    def stop(self) -> None:
        """Exit terminal UI mode and restore terminal state."""
        self._running = False

        cleanup = SHOW_CURSOR + DBP + DFE
        if self._alt_screen:
            cleanup += EXIT_ALT_SCREEN
        self._terminal.write(cleanup)
        self._terminal.restore()

    def render(self) -> None:
        """Perform a full render cycle: layout → render → diff → output.

        Thread-safe and throttled: multiple rapid calls are coalesced into
        one actual render at ~16ms intervals (like cc-haha's lodash.throttle).
        """
        with self._render_lock:
            now = time.time()
            elapsed = now - self._last_render_time
            if elapsed < 0.016:
                # Too soon — schedule a trailing render
                if not self._render_pending:
                    self._render_pending = True
                    threading.Timer(0.016 - elapsed, self._do_render).start()
                return
            self._do_render_inner()

    def _do_render(self) -> None:
        """Trailing-edge render (called from timer)."""
        with self._render_lock:
            if self._render_pending:
                self._do_render_inner()

    def _do_render_inner(self) -> None:
        """Actual render implementation (must hold _render_lock)."""
        self._render_pending = False
        self._last_render_time = time.time()

        # Recompute layout
        self._width = self._terminal.columns
        self._height = self._terminal.rows
        compute_layout(self.root, self._width, self._height)

        # Resize screens if needed
        if self._curr_screen.width != self._width or self._curr_screen.height != self._height:
            self._prev_screen = Screen(self._width, self._height, self._char_pool, self._style_pool)
            self._curr_screen = Screen(self._width, self._height, self._char_pool, self._style_pool)

        # Render DOM tree to current screen
        output = Output(self._width, self._height, self._char_pool, self._style_pool, self._curr_screen)
        render_tree(self.root, output, self._char_pool, self._style_pool)
        output.apply()

        # Diff and write to terminal
        ansi = render_frame(self._prev_screen, self._curr_screen, self._style_pool, self._char_pool)
        if ansi:
            self._terminal.write(ansi)

        # Position cursor for IME
        cursor_seq = self.cursor.get_cursor_sequence()
        if cursor_seq:
            self._terminal.write(cursor_seq + SHOW_CURSOR)

        # Swap buffers
        self._prev_screen, self._curr_screen = self._curr_screen, self._prev_screen

    def _force_full_render(self) -> None:
        """Force a full screen redraw (Ctrl+L). Clears prev screen so diff outputs everything."""
        with self._render_lock:
            self._prev_screen = Screen(self._width, self._height, self._char_pool, self._style_pool)
        self.render()

    def schedule_render(self) -> None:
        """Schedule a render on the next frame (debounced)."""
        if not self._render_pending and self._running:
            self._render_pending = True
            threading.Timer(0.016, self._do_scheduled_render).start()

    def _do_scheduled_render(self) -> None:
        if self._running and self._render_pending:
            self.render()

    def _on_resize(self, signum: int, frame: Any) -> None:
        """Handle terminal resize (SIGWINCH)."""
        if self._running:
            self.render()

    def _read_input(self) -> None:
        """Background thread: read stdin and dispatch input events."""
        fd = self._terminal.input_fd
        while self._running:
            try:
                data = os.read(fd, 4096)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                events = self._input_parser.feed(text)
                handler = self._on_input
                if handler:
                    for event in events:
                        handler(event)
            except OSError:
                break
