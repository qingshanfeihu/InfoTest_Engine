"""IstInkApp — IST-Core TUI using the Python Ink renderer.

Replaces the Textual-based IstApp. Uses Python Ink renderer for:
- Real terminal cursor positioning (IME follows cursor)
- Full mouse capture (DEC 1000+1002+1003+1006) with a self-implemented
  selection engine (selection.py) — drag-to-select, double-click word,
  triple-click line, release-copy via OSC 52 + pbcopy/xclip, Ctrl+C
  re-copy when a selection is active. Same UX as Claude Code.
- Efficient incremental screen updates
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from main.qa_agent.ink.app import InkApp
from main.qa_agent.ink.components.footer import FooterPane
from main.qa_agent.ink.components.plan_panel import PlanPanel
from main.qa_agent.ink.components.prompt_input import PromptInput
from main.qa_agent.ink.components.transcript import Transcript
from main.qa_agent.ink.dom import NodeType, create_element, create_text
from main.qa_agent.ink.parse_keypress import (
    InputEvent,
    KeyPress,
    MouseEvent,
    PasteEvent,
)

# ---------------------------------------------------------------------------
# 工具短名 + 工具特定渲染
# ---------------------------------------------------------------------------

_TOOL_SHORT_NAMES: dict[str, str] = {
    "qa_deepagent_read_file": "Read",
    "qa_deepagent_grep": "Grep",
    "qa_deepagent_glob": "Glob",
    "qa_deepagent_ls": "Ls",
    "qa_deepagent_write_file": "Write",
    "qa_deepagent_edit_file": "Edit",
    "qa_bash": "Bash",
    "qa_exec": "Exec",
    "qa_invoke_skill": "Skill",
    "qa_footprint_lookup": "Footprint",
    "web_bug_search": "BugSearch",
    "write_todos": "TodoWrite",
    "task": "Agent",
}


def _tool_short_name(raw: str) -> str:
    return _TOOL_SHORT_NAMES.get(raw, raw)


def _tool_display_arg(name: str, args: dict) -> str:
    """工具特定参数摘要。"""
    if not args:
        return ""
    if name in ("qa_deepagent_read_file", "qa_deepagent_write_file",
                "qa_deepagent_edit_file"):
        path = args.get("file_path") or args.get("path") or ""
        if isinstance(path, str) and path:
            parts = path.replace("\\", "/").split("/")
            return "/".join(parts[-2:]) if len(parts) > 2 else path
    if name == "qa_deepagent_grep":
        return str(args.get("pattern") or args.get("query") or "")[:60]
    if name == "qa_deepagent_glob":
        return str(args.get("pattern") or "")[:60]
    if name in ("qa_bash", "qa_exec"):
        cmd = str(args.get("command") or "")
        return (cmd[:60] + "…") if len(cmd) > 60 else cmd
    if name == "qa_invoke_skill":
        return str(args.get("skill") or "")[:40]
    first_val = next(iter(args.values()), "")
    if isinstance(first_val, str) and len(first_val) > 60:
        return first_val[:60] + "…"
    return str(first_val) if first_val else ""


def _tool_result_summary(name: str, output: str) -> list[str] | None:
    """工具特定结果摘要。返回 None = 通用截断；返回 list = 摘要替代。"""
    if name == "qa_deepagent_read_file":
        n = output.count("\n") + (1 if output and not output.endswith("\n") else 0)
        return [f"Read \x1b[1m{n}\x1b[0m lines"]
    if name == "qa_deepagent_glob":
        matches = [l for l in output.split("\n") if l.strip()]
        if len(matches) <= 6:
            return matches or ["(no matches)"]
        return matches[:5] + [f"\x1b[2m… +{len(matches) - 5} matches\x1b[0m"]
    return None


class IstInkApp:
    """IST-Core TUI application using Python Ink renderer."""

    def __init__(
        self,
        *,
        thread_id: str | None = None,
        initial_query: str | None = None,
        task_type: str = "QA",
    ) -> None:
        self._thread_id = thread_id
        self._initial_query = initial_query
        self._task_type = task_type

        # Ink app — full mouse capture so the self-implemented selection
        # engine (selection.py) can do drag-to-select / multi-click /
        # release-copy without relying on terminal-native selection.
        self._app = InkApp(alt_screen=True, mouse=True)

        # Components
        self._transcript = Transcript()
        self._prompt = PromptInput(
            cursor_manager=self._app.cursor,
            on_submit=self._on_submit,
            placeholder="输入消息（/ 触发补全）",
        )
        # Plan panel — 钉在 thinking_line 上方，承载 write_todos 整列重渲染
        # 与 thinking_line 可同时显示：plan 是阶段结构、thinking 是即时心跳
        self._plan_panel = PlanPanel()

        # Thinking status line (above divider, like Claude Code)
        self._thinking_line = create_element(NodeType.BOX)
        self._thinking_line.style.height = 0  # hidden by default
        self._thinking_text = create_text("")
        self._thinking_line.append_child(self._thinking_text)

        # Footer (must be created AFTER _thinking_line since it calls _update_thinking_line)
        self._footer = FooterPane(render_callback=self._app.render, thinking_text_cb=self._update_thinking_line)

        # Divider above input (dim line) — width set dynamically on render
        self._divider_top = create_element(NodeType.BOX)
        self._divider_top.style.height = 1
        self._divider_top.text_styles.dim = True
        self._divider_text = create_text("")
        self._divider_top.append_child(self._divider_text)

        # Divider below input (dim line)
        self._divider_bottom = create_element(NodeType.BOX)
        self._divider_bottom.style.height = 1
        self._divider_bottom.text_styles.dim = True
        self._divider_bottom_text = create_text("")
        self._divider_bottom.append_child(self._divider_bottom_text)

        # Assemble layout: transcript + plan_panel + thinking_line + divider_top + prompt + divider_bottom + footer
        # plan_panel 位于 thinking_line 上方：plan 是结构性内容（停留更久），
        # thinking 是即时心跳（每秒刷新）；plan 紧贴 transcript 历史、thinking 紧贴输入框横线
        self._app.root.append_child(self._transcript.node)
        self._app.root.append_child(self._plan_panel.node)
        self._app.root.append_child(self._thinking_line)
        self._app.root.append_child(self._divider_top)
        self._app.root.append_child(self._prompt.node)
        self._app.root.append_child(self._divider_bottom)
        self._app.root.append_child(self._footer.node)

        # Wire input handler
        self._app.on_input = self._handle_input

        # State
        self._is_loading = False
        self._bridge: Any = None
        self._streaming_buf: list[str] = []
        self._last_md_render_ts: float = 0.0
        self._md_renderer: Any = None
        self._model: str = ""
        self._welcome_shown: bool = False
        self._last_ctrl_c: float = 0.0
        self._tokens_used: int = 0
        self._run_start_time: float = 0.0
        self._tool_outputs_expanded: bool = False
        self._tool_output_blocks: list[dict] = []
        # 当前 AI 流式消息行号；任何非 token 事件（tool_start / append / finalize_ai）
        # 必须 reset 它，否则下一个 llm_token 会用 update_last_message 把刚 append
        # 的工具行内容覆盖掉——表现就是"AI 独白消失，只剩工具行"
        self._ai_stream_idx: int = -1

        # Persistent history (reuse old TUI's InputHistory)
        from main.qa_agent.tui.input_history import InputHistory
        self._input_history = InputHistory()
        self._history_idx = -1

        # TUI 全局可变状态 —— slash commands (/model /cost /compact) 通过 app.tui_state 读写
        from main.qa_agent.tui.state import TuiState
        self.tui_state = TuiState(thread_id=self._thread_id or "")

    def append_transcript_info(self, text: str) -> None:
        """线程安全地向 transcript 追加一行（供 KMS 等后台任务回写进度）。"""
        with self._app.lock:
            self._transcript.append_message(f" {text}")
            self._app.render()

    def set_background_status(self, text: str | None) -> None:
        """后台任务进度（显示在输入框上方 thinking 行，不刷屏 transcript）。"""
        with self._app.lock:
            self._update_thinking_line(text)
            self._app.render()

    def run(self) -> None:
        """Start the TUI (blocking)."""
        import warnings
        import sys
        import os

        # Suppress warnings that leak to terminal in raw mode
        warnings.filterwarnings("ignore")
        # Redirect stderr to devnull to prevent any stray output
        devnull = open(os.devnull, "w")
        old_stderr = sys.stderr
        sys.stderr = devnull

        try:
            self._app.start()
            self._show_welcome()
            if self._initial_query:
                self._submit(self._initial_query)
            self._wait_for_exit()
        except KeyboardInterrupt:
            pass
        finally:
            # 退出前先取消并等 bridge 后台 worker 结束，避免主进程
            # shutdown 时还有 daemon 线程在 submit 新 future
            try:
                if self._bridge is not None:
                    self._bridge.cancel()
                    self._bridge.join(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
            sys.stderr = old_stderr
            devnull.close()
            self._app.stop()
            # 如果 bridge worker 仍然活着（langgraph finalize 超时），
            # 用 os._exit 强制退出，跳过 threading._shutdown / _python_exit。
            # 否则 Python atexit 会设全局 _shutdown=True，daemon 线程里
            # 的 executor.submit() 会 raise RuntimeError 并打印大段堆栈。
            if self._bridge is not None and self._bridge.is_running:
                import os as _os
                _os._exit(0)

    def _wait_for_exit(self) -> None:
        """Block until the app is stopped."""
        import time
        while self._app._running:
            time.sleep(0.1)

    def _show_welcome(self) -> None:
        from main.qa_agent.agents._llm import qa_agent_default_model
        import os
        model = qa_agent_default_model()
        self._model = model
        self._footer.update(model=model)

        w = self._app.width

        # Update divider lines to match terminal width
        self._divider_text.set_value("─" * w)
        self._divider_bottom_text.set_value("─" * w)

        # Simple, clean welcome — no heavy box
        self._transcript.append_message("")
        self._transcript.append_message(f"  \x1b[1mInfoTest Engine v1.0.2\x1b[0m")
        self._transcript.append_message(f"  \x1b[2m{model} · {os.getcwd()}\x1b[0m")
        self._transcript.append_message("")
        self._transcript.append_message(f"  \x1b[2m输入自然语言描述测试分析需求，自动调用工具查阅知识库。\x1b[0m")
        self._transcript.append_message(f"  \x1b[2m/help 查看命令 · /init 初始化项目 · /model 切换模型\x1b[0m")
        self._transcript.append_message("")
        self._app.render()
        self._welcome_shown = True

    def _handle_input(self, event: InputEvent) -> None:
        """Dispatch input events to appropriate handlers."""
        # 输入读取在 ink-input 后台线程触发；DOM 修改必须和 bridge worker
        # 投来的 update_ai_token / append / tool_done 等事件互斥，否则
        # children 列表 / TextNode.value 会出现部分写入交织（典型表现：
        # AI 流式 token 和工具行字符互相穿插）
        with self._app.lock:
            if isinstance(event, KeyPress):
                self._handle_key(event)
            elif isinstance(event, MouseEvent):
                self._handle_mouse(event)
            elif isinstance(event, PasteEvent):
                self._prompt.handle_paste(event.text)
                self._app.render()

    def _handle_key(self, kp: KeyPress) -> None:
        """Handle keyboard events."""
        import time as _time

        # Reverse-i-search mode swallows most input until exited
        if self._input_history.in_search_mode:
            if self._handle_search_key(kp):
                return

        # Selection-active shortcuts: Ctrl+C re-copies, Esc clears.
        # Both checks must run BEFORE the global Ctrl+C abort branch so
        # users can copy a highlighted result without aborting a query.
        from main.qa_agent.ink.selection import clear_selection, has_selection
        if has_selection(self._app.selection):
            if kp.key == "ctrl+c":
                self._copy_selection(clear_after=False)
                return
            if kp.key == "escape":
                clear_selection(self._app.selection)
                self._app.notify_selection_change()
                self._app.render()
                return

        # Global keys
        if kp.key == "ctrl+c":
            now = _time.time()
            if self._is_loading:
                self._cancel_query()
                self._last_ctrl_c = now
            elif now - getattr(self, '_last_ctrl_c', 0) < 1.5:
                # 双 ctrl+c 退出 —— 让 _wait_for_exit 跳出回 run() finally 统一处理 cleanup。
                self._app._running = False
            else:
                self._last_ctrl_c = now
                self._transcript.append_message(" \x1b[2m(press ctrl+c again to exit)\x1b[0m")
                self._app.render()
            return
        if kp.key == "ctrl+d":
            self._app._running = False
            return
        if kp.key == "escape":
            if self._is_loading:
                self._cancel_query()
            else:
                self._prompt.clear()
                # Force a full redraw — when a long paste expanded inline
                # past the prompt's single-line viewport, the terminal's
                # auto-wrap left visible content on the lines below the
                # input box. Those rows are NOT in the ink screen buffer,
                # so a normal diff render won't erase them. Clearing the
                # prev frame makes the next render write every cell from
                # scratch, which paints over the leftover wrap.
                self._app._force_full_render()
            return
        if kp.key == "ctrl+o":
            self._toggle_expand()
            return
        if kp.key == "ctrl+l":
            self._app._force_full_render()
            return
        if kp.key == "pageup":
            self._scroll_transcript(-self._half_viewport())
            return
        if kp.key == "pagedown":
            self._scroll_transcript(self._half_viewport())
            return
        if kp.key == "ctrl+r":
            self._enter_or_advance_search()
            return
        if kp.key == "up":
            self._history_up()
            self._app.render()
            return
        if kp.key == "down":
            self._history_down()
            self._app.render()
            return
        if kp.key == "tab":
            self._tab_complete()
            return

        # Delegate to prompt
        consumed = self._prompt.handle_key(kp.key, kp.char)
        if consumed:
            self._app.render()

    def _handle_mouse(self, me: "MouseEvent") -> None:
        """Handle mouse events: wheel scrolls transcript; left button does
        the Claude-Code-style selection (single drag = char, double-click =
        word, triple-click = line, release auto-copies)."""
        # Translate screen y to a transcript-content row by accounting for
        # the transcript widget's vertical position and current scroll.
        col, row = self._mouse_to_screen_coords(me.x, me.y)

        if me.type == "wheel":
            # button=0 wheel-up, button=1 wheel-down (parse_keypress).
            if me.button == 0:
                self._scroll_transcript(-3)
            elif me.button == 1:
                self._scroll_transcript(3)
            return

        # We only care about the left button (button=0) for selection.
        if me.button != 0:
            return

        if me.type == "press":
            self._handle_left_press(col, row, alt=me.alt)
            return

        if me.type == "move":
            # Drag motion. Ink emits "move" events while a button is held
            # (1002 button-motion mode). Only act if the selection is
            # actively dragging — bare hover should not extend selection.
            sel = self._app.selection
            if not sel.is_dragging:
                return
            if sel.anchor_span is not None:
                from main.qa_agent.ink.selection import extend_selection
                extend_selection(sel, self._app._curr_screen, col, row)
            else:
                from main.qa_agent.ink.selection import update_selection
                update_selection(sel, col, row)
            self._app.notify_selection_change()
            self._app.render()
            return

        if me.type == "release":
            from main.qa_agent.ink.selection import (
                finish_selection,
                has_selection,
            )
            sel = self._app.selection
            was_dragging = sel.is_dragging
            finish_selection(sel)
            # Auto-copy on release if a real selection exists. Claude Code
            # clears after copy, but we keep the highlight so a second
            # Ctrl+C can re-copy without re-dragging.
            if was_dragging and has_selection(sel):
                self._copy_selection(clear_after=False)
            self._app.notify_selection_change()
            self._app.render()
            return

    def _handle_left_press(self, col: int, row: int, *, alt: bool) -> None:
        """Single / double / triple-click dispatch. Uses a 300 ms
        same-cell window to escalate click count.
        """
        import time as _time
        now = _time.monotonic()
        last = getattr(self, "_last_click_meta", None)
        click_count = 1
        if (
            last is not None
            and now - last[0] < 0.3
            and last[1] == col
            and last[2] == row
        ):
            click_count = last[3] + 1
        # Cap at 3 — further clicks repeat line selection (same
        # behavior).
        if click_count > 3:
            click_count = 3

        from main.qa_agent.ink.selection import (
            select_line_at,
            select_word_at,
            start_selection,
        )

        sel = self._app.selection
        # Any new mouse-down resets prior highlight in the natural way.
        sel.scrolled_off_above = []
        sel.scrolled_off_below = []
        sel.scrolled_off_above_sw = []
        sel.scrolled_off_below_sw = []

        screen = self._app._curr_screen
        if click_count == 1:
            start_selection(sel, col, row, alt=alt)
        elif click_count == 2:
            select_word_at(sel, screen, col, row)
        else:
            select_line_at(sel, screen, row)

        self._last_click_meta = (now, col, row, click_count)
        self._app.notify_selection_change()
        self._app.render()

    def _mouse_to_screen_coords(self, x: int, y: int) -> tuple[int, int]:
        """SGR mouse coords are already 0-indexed screen cells (see
        _parse_sgr_mouse). The selection state operates in the same
        coordinate space, so we pass the raw values through. Clamp to the
        current screen bounds to avoid out-of-range indexing during
        edge-of-viewport drags."""
        screen = self._app._curr_screen
        clamped_x = max(0, min(x, max(0, screen.width - 1)))
        clamped_y = max(0, min(y, max(0, screen.height - 1)))
        return clamped_x, clamped_y

    def _copy_selection(self, *, clear_after: bool) -> None:
        """Copy the current selection to the clipboard.

        clear_after=True drops the highlight after copying (Claude Code
        copySelection); False keeps it visible so subsequent Ctrl+C can
        re-copy the same range.
        """
        from main.qa_agent.ink.selection import (
            clear_selection,
            get_selected_text,
            has_selection,
        )
        from main.qa_agent.ink.termio.osc import set_clipboard

        sel = self._app.selection
        if not has_selection(sel):
            return
        text = get_selected_text(sel, self._app._curr_screen)
        if not text:
            return
        seq = set_clipboard(text)
        if seq:
            self._app._terminal.write(seq)
        # Show a brief toast on the footer.
        self._footer.set_toast(f"Copied {len(text)} chars", ttl_seconds=1.2)
        if clear_after:
            clear_selection(sel)
            self._app.notify_selection_change()
        self._app.render()

    def _half_viewport(self) -> int:
        return max(1, self._transcript.viewport_height() // 2)

    def _scroll_transcript(self, delta: int) -> None:
        if delta == 0:
            return
        self._transcript.scroll_by(delta)
        self._app.render()

    # -- Reverse-i-search ---------------------------------------------------

    def _enter_or_advance_search(self) -> None:
        if self._input_history.in_search_mode:
            result = self._input_history.search_next()
            self._update_search_ui(result)
        else:
            initial = self._prompt.value
            result = self._input_history.start_search(initial)
            self._update_search_ui(result)

    def _update_search_ui(self, match: str | None) -> None:
        query = self._input_history.search_query
        if match is not None:
            self._prompt.set_value(match)
        self._footer.set_search_state(query=query, match=match if match else "")
        self._app.render()

    def _handle_search_key(self, kp: KeyPress) -> bool:
        """Search-mode keystroke dispatcher. Returns True if event consumed."""
        key = kp.key
        # Ctrl+R cycles to next match — handled by the global branch below;
        # let it fall through.
        if key == "ctrl+r":
            return False
        if key == "escape":
            draft = self._input_history.exit_search(restore=True)
            self._prompt.set_value(draft)
            self._footer.set_search_state(query=None, match=None)
            self._app.render()
            return True
        if key == "enter":
            self._input_history.exit_search(restore=False)
            self._footer.set_search_state(query=None, match=None)
            text = self._prompt.value
            if text:
                self._prompt.clear()
                self._submit(text)
            else:
                self._app.render()
            return True
        if key == "backspace":
            new_q = self._input_history.search_query[:-1]
            result = self._input_history.update_search_query(new_q)
            self._update_search_ui(result)
            return True
        if key == "ctrl+c":
            # Cancel search instead of aborting query
            draft = self._input_history.exit_search(restore=True)
            self._prompt.set_value(draft)
            self._footer.set_search_state(query=None, match=None)
            self._app.render()
            return True
        # Printable char -> extend query
        if kp.char and len(kp.char) == 1 and kp.char.isprintable():
            new_q = self._input_history.search_query + kp.char
            result = self._input_history.update_search_query(new_q)
            self._update_search_ui(result)
            return True
        # Any other special key (up/down/tab/page*/etc.) — exit search keeping
        # the current match visible, then fall through to normal handling.
        self._input_history.exit_search(restore=False)
        self._footer.set_search_state(query=None, match=None)
        return False

    def _on_submit(self, text: str) -> None:
        """Called when user presses Enter in prompt."""
        self._submit(text)

    def _submit(self, text: str, *, pre_expanded: str | None = None) -> None:
        """Submit user input to the agent.

        ``pre_expanded`` is the original multi-line content when the caller
        already knows it (e.g. repeat-paste auto-submit). When set, the
        placeholder-expansion step is skipped and the LLM receives this
        text verbatim. ``text`` is still used for history / slash routing.
        """
        text = text.strip()
        if not text and not pre_expanded:
            return

        if text:
            # Save the placeholder form to history so the persistent log
            # stays compact (long pastes show as [Pasted text #N +K lines]).
            self._input_history.add(text)

            # Slash command? Slash commands operate on the typed text and
            # never carry pasted bodies, so don't expand placeholders here.
            if text.startswith("/"):
                self._handle_slash(text)
                return

        if pre_expanded is not None:
            expanded = pre_expanded
        else:
            # Expand any [Pasted text #N +K lines] placeholders back into
            # their original multi-line content before showing + sending to
            # the LLM. Also unwrap the ↵ visual newline marker we use for
            # short pastes / Shift+Enter.
            expanded = self._prompt.consume_pasted_refs(text).replace("↵", "\n")

        # Clear welcome box on first submit
        if self._welcome_shown:
            self._transcript.clear()
            self._welcome_shown = False

        # 输入预处理：检测文件路径，自动复制/转换到沙箱
        from main.qa_agent.tui.input_preprocessor import preprocess_file_paths
        import os as _os
        _session_dir = _os.environ.get("IST_SESSION_DIR")
        processed_text, preprocess_status = preprocess_file_paths(
            expanded,
            session_dir=Path(_session_dir) if _session_dir else None,
        )
        if preprocess_status:
            if preprocess_status.startswith("⬆ NEED_UPLOAD:"):
                filename = preprocess_status.removeprefix("⬆ NEED_UPLOAD:")
                if _session_dir:
                    msg = f"⬆ 文件 {filename} 不在本地，请通过 Web Terminal 上传"
                else:
                    msg = f"⬆ 文件 {filename} 不存在，请检查路径是否正确"
                self._transcript.append_message(f"  \x1b[33m{msg}\x1b[0m")
                self._app.render()
                return
            else:
                # 本地文件已处理，显示状态并用处理后的文本
                self._transcript.append_message(f"  \x1b[2m{preprocess_status}\x1b[0m")
                expanded = processed_text

        # Show user message (indented, no "> " prefix — matches old TUI)
        for line in expanded.split("\n"):
            self._transcript.append_message(f"  {line}")
        self._transcript.append_message("")
        # Placeholder for streaming AI response (will be updated by update_ai_token/append)
        self._transcript.append_message("")
        self._footer.update(status="esc to interrupt")
        self._is_loading = True
        self._run_start_time = __import__('time').time()
        self._app.render()

        # Run query via GraphBridge (same pattern as Textual app).
        # Use the placeholder-expanded form so the LLM sees the full
        # pasted content instead of the [Pasted text #N] short form.
        self._run_via_bridge(expanded)

    def _submit_expanded(self, expanded: str) -> None:
        """Submit raw multi-line content directly, bypassing the prompt
        editor. Used by repeat-paste auto-submit."""
        # Show a one-line summary in history so the persistent log stays
        # compact (we never round-tripped this through the prompt).
        num_lines = expanded.count("\n")
        history_label = (
            f"[Pasted text +{num_lines} lines]" if num_lines else expanded
        )
        self._input_history.add(history_label)
        # Reset prompt's paste store — the expansion consumed it.
        self._prompt.clear_pasted_refs()
        self._submit("", pre_expanded=expanded)

    def _run_via_bridge(self, text: str) -> None:
        """Run query through GraphBridge in background thread."""
        from langchain_core.messages import HumanMessage
        from main.qa_agent.tui.bridge import GraphBridge
        from main.qa_agent.tui.message_model import MessageSnapshot

        if self._bridge is None:
            thread_id = self._thread_id or uuid.uuid4().hex[:12]
            from main.qa_agent.sinks.jsonl_sink import JsonlFileSink
            from pathlib import Path
            jsonl_sink = JsonlFileSink(log_dir=Path("logs"))
            self._bridge = GraphBridge(
                graph_factory=self._build_graph,
                post=self._on_snapshot,
                thread_id=thread_id,
                extra_sinks=[jsonl_sink],
            )

        if self._bridge.is_running:
            self._transcript.append_message("(busy — 等待当前回合完成)")
            self._app.render()
            return

        initial_state = {
            "task_type": self._task_type,
            "user_input": text,
            "messages": [HumanMessage(content=text)],
        }
        self._streaming_buf = []
        self._transcript.append_message("")  # placeholder for streaming
        self._bridge.start(initial_state)

    @staticmethod
    def _build_graph():
        from main.qa_agent.graph import build_qa_agent_graph
        return build_qa_agent_graph(checkpointer=True)

    def _on_snapshot(self, snapshot: Any) -> None:
        """Handle MessageSnapshot from TuiSink (called from bridge thread).

        适配层：把 MessageSnapshot 翻译成旧 _on_ui_event_locked 的渲染调用。
        bridge worker 是后台线程；DOM 修改必须和 ink-input 线程串行化。
        """
        with self._app.lock:
            self._on_snapshot_locked(snapshot)

    def _on_snapshot_locked(self, snapshot: Any) -> None:
        """Diff snapshot against previous state and render changes."""
        from main.qa_agent.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_TOOL_RESULT, BLOCK_THINKING,
            BLOCK_PHASE_MARKER, BLOCK_EVIDENCE, BLOCK_FINDING,
        )
        prev = getattr(self, '_prev_snapshot', None)
        self._prev_snapshot = snapshot

        # --- streaming text update ---
        if snapshot.streaming_text is not None:
            self._flush_pending_tools()
            rendered = self._render_markdown(snapshot.streaming_text)
            if self._ai_stream_idx < 0:
                self._ai_stream_idx = self._transcript.message_count()
                self._transcript.append_message(f" ⏺ {rendered}")
            else:
                self._transcript.update_message_at(
                    self._ai_stream_idx, f" ⏺ {rendered}"
                )
            self._app.render()
            return

        # --- streaming ended (was streaming, now not) ---
        if prev and prev.streaming_text is not None and snapshot.streaming_text is None:
            self._ai_stream_idx = -1

        # --- new messages ---
        prev_count = len(prev.messages) if prev else 0
        new_msgs = snapshot.messages[prev_count:]
        for msg in new_msgs:
            for block in msg.content:
                self._render_content_block(block, msg)

        # --- usage update ---
        if snapshot.usage:
            input_t = snapshot.usage.get("input_tokens", 0) or 0
            output_t = snapshot.usage.get("output_tokens", 0) or 0
            total = snapshot.usage.get("total_tokens", 0) or (input_t + output_t)
            if total and total != self._tokens_used:
                self._tokens_used = total
                self._footer.update(
                    tokens_used=total,
                    input_tokens=input_t,
                    output_tokens=output_t,
                )

        # --- status change ---
        if snapshot.status == "done" and (not prev or prev.status != "done"):
            self._flush_pending_tools()
            self._is_loading = False
            self._ai_stream_idx = -1
            self._footer.update(status="ready")

        elif snapshot.status == "error" and (not prev or prev.status != "error"):
            self._flush_pending_tools()
            self._is_loading = False
            self._ai_stream_idx = -1
            # 从最后一条 message 找 error 信息
            if snapshot.messages:
                last = snapshot.messages[-1]
                for b in last.content:
                    if b.type == BLOCK_TEXT and b.text:
                        self._transcript.append_message(
                            f" \x1b[31m[error]\x1b[0m {b.text}"
                        )
                        break
            self._footer.update(status="error")

        self._app.render()

    def _render_content_block(self, block: Any, msg: Any) -> None:
        """Render a single ContentBlock to the transcript."""
        from main.qa_agent.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_TOOL_RESULT, BLOCK_THINKING,
            BLOCK_PHASE_MARKER, BLOCK_EVIDENCE, BLOCK_FINDING,
        )
        B = self._BOLD
        C = self._CYAN
        D = self._DIM
        X = self._RESET

        if block.type == BLOCK_TEXT and block.text:
            self._flush_pending_tools()
            rendered = self._render_markdown(block.text, final=True)
            self._ai_stream_idx = -1
            self._transcript.append_message(f" ⏺ {rendered}")

        elif block.type == BLOCK_THINKING and block.thinking:
            self._ai_stream_idx = -1
            if getattr(self, '_tool_outputs_expanded', False):
                self._transcript.append_message(
                    f" {D}\x1b[3m∴ {block.thinking.strip()}{X}"
                )
            else:
                self._transcript.append_message(
                    f" {D}\x1b[3m∴ Thinking{X} {D}(ctrl+o to expand){X}"
                )

        elif block.type == BLOCK_TOOL_USE:
            self._ai_stream_idx = -1
            raw_name = block.name or "tool"
            args = dict(block.input) if block.input else {}
            display_name = _tool_short_name(raw_name)
            first_val = _tool_display_arg(raw_name, args)
            arg_str = f"({C}{first_val}{X})" if first_val else ""
            idx = self._transcript.message_count()
            if block.status == "done":
                self._transcript.append_message(
                    f" \x1b[32m⏺\x1b[0m {B}{display_name}{X}{arg_str}"
                )
            elif block.status == "error":
                self._transcript.append_message(
                    f" \x1b[31m⏺\x1b[0m {B}{display_name}{X}{arg_str}"
                )
            else:
                self._transcript.append_message(
                    f" \x1b[5;33m⏺\x1b[0m {B}{display_name}{X}{arg_str}"
                )
                if not hasattr(self, '_tool_start_stack'):
                    self._tool_start_stack = []
                self._tool_start_stack.append((idx, display_name))

        elif block.type == BLOCK_TOOL_RESULT:
            self._ai_stream_idx = -1
            if block.output:
                raw_name = block.name or ""
                full_lines = block.output.split("\n")
                start_idx = self._transcript.message_count()
                expanded = getattr(self, '_tool_outputs_expanded', False)
                # 工具特定摘要
                summary = _tool_result_summary(raw_name, block.output)
                if summary is not None and not expanded:
                    for line in summary:
                        self._transcript.append_message(f"   {D}⎿{X} {line}")
                    display_count = len(summary)
                elif expanded or len(full_lines) <= 3:
                    for line in full_lines:
                        self._transcript.append_message(f"   {D}⎿{X} {line[:100]}")
                    display_count = len(full_lines)
                else:
                    for line in full_lines[:3]:
                        self._transcript.append_message(f"   {D}⎿{X} {line[:100]}")
                    self._transcript.append_message(
                        f"   {D}… +{len(full_lines) - 3} lines (ctrl+o to expand){X}"
                    )
                    display_count = 4
                if not hasattr(self, '_tool_output_blocks'):
                    self._tool_output_blocks = []
                self._tool_output_blocks.append({
                    "start_idx": start_idx,
                    "full_lines": full_lines,
                    "display_count": display_count,
                    "tool_name": raw_name,
                })

        elif block.type == BLOCK_PHASE_MARKER:
            phase = block.payload.get("phase", "") if block.payload else ""
            self._transcript.append_message(f" {B}[{phase}]{X}")

        elif block.type == BLOCK_EVIDENCE:
            text = block.payload.get("text", "") if block.payload else ""
            self._transcript.append_message(f"   {D}· evidence: {text[:120]}{X}")

        elif block.type == BLOCK_FINDING:
            text = block.payload.get("text", "") if block.payload else ""
            self._transcript.append_message(f"   {B}⚡ finding: {text[:120]}{X}")

        elif block.type == "todo_list":
            # Plan panel 更新（对齐旧 TodoListMessage 处理）
            todos = block.payload.get("todos") if block.payload else None
            if todos and hasattr(self, '_plan_panel'):
                self._plan_panel.update(todos)

    def _on_ui_event_locked(self, event: Any) -> None:
        kind = event.kind

        if kind == "update_ai_token":
            self._flush_pending_tools()
            chunk = (event.extra or {}).get("chunk", "")
            self._streaming_buf.append(chunk)
            import time as _t
            now = _t.monotonic()
            if self._ai_stream_idx >= 0 and (now - self._last_md_render_ts) < 0.05:
                return
            self._last_md_render_ts = now
            partial = "".join(self._streaming_buf)
            rendered = self._render_markdown(partial)
            # 第一次 token：append 一个新行作为这段 AI 独白的锚点；
            # 后续 token 用 update_message_at 改这一行——不能用 update_last_message，
            # 否则中间穿插的 tool_start 会被覆盖
            if self._ai_stream_idx < 0:
                self._ai_stream_idx = self._transcript.message_count()
                self._transcript.append_message(f" ⏺ {rendered}")
            else:
                self._transcript.update_message_at(
                    self._ai_stream_idx, f" ⏺ {rendered}"
                )
            self._app.render()

        elif kind == "finalize_ai":
            self._flush_pending_tools()
            final = "".join(self._streaming_buf)
            if final:
                rendered = self._render_markdown(final, final=True)
                if self._ai_stream_idx >= 0:
                    self._transcript.update_message_at(
                        self._ai_stream_idx, f" ⏺ {rendered}"
                    )
                else:
                    self._transcript.append_message(f" ⏺ {rendered}")
            self._streaming_buf.clear()
            self._ai_stream_idx = -1  # 下一段 AI 独白要新建一行
            # Accumulate tokens
            usage = (event.extra or {}).get("usage") or {}
            tokens = usage.get("total_tokens", 0) or usage.get("prompt_tokens", 0)
            if tokens:
                self._tokens_used += tokens
                self._footer.update(tokens_used=self._tokens_used)
            self._app.render()

        elif kind == "run_done":
            self._flush_pending_tools()
            self._ai_stream_idx = -1
            self._is_loading = False
            # Show completion line: ⏱ elapsed · tokens
            import time as _time
            elapsed = _time.time() - self._run_start_time if self._run_start_time else 0
            if elapsed > 0:
                from main.qa_agent.ink.components.footer import _format_elapsed
                elapsed_str = _format_elapsed(elapsed)
                self._transcript.append_message(
                    f" \x1b[2m⏱ {elapsed_str} · {self._tokens_used:,} tokens\x1b[0m"
                )
            self._footer.update(status="ready", tokens_used=self._tokens_used)
            self._tool_output_blocks.clear()
            self._app.render()

        elif kind == "run_error":
            self._ai_stream_idx = -1
            self._is_loading = False
            err = (event.extra or {}).get("error", "unknown error")
            self._transcript.append_message(f"[error] {err}")
            self._footer.update(status="error")
            self._app.render()

        elif kind == "append":
            if event.message:
                self._ai_stream_idx = -1
                self._format_and_append(event.message)
                self._app.render()

        elif kind == "tool_start":
            self._ai_stream_idx = -1
            tool_name = (event.extra or {}).get("tool_name", "tool")
            # Blinking yellow ⏺ = running
            idx = self._transcript.message_count()
            self._transcript.append_message(f" \x1b[5;33m⏺\x1b[0m \x1b[1m{tool_name}\x1b[0m...")
            # Track for green update on tool_done (use stack — LIFO)
            if not hasattr(self, '_tool_start_stack'):
                self._tool_start_stack = []
            self._tool_start_stack.append((idx, tool_name))
            self._app.render()

        elif kind == "tool_done":
            self._ai_stream_idx = -1
            extra = event.extra or {}
            tool_name = extra.get("tool_name", "")
            result = extra.get("result", "")
            # Update most recent tool_start line: blinking yellow → green (success)
            if hasattr(self, '_tool_start_stack') and self._tool_start_stack:
                idx, name = self._tool_start_stack.pop(0)  # FIFO: oldest first
                self._transcript.update_message_at(
                    idx, f" \x1b[32m⏺\x1b[0m \x1b[1m{name}\x1b[0m"
                )
            # write_todos 的 panel 渲染由 _format_and_append 中 TodoListMessage
            # 分支处理（tool_call 阶段就拿到完整 todos），这里不再二次解析 result
            if result:
                full_lines = str(result).split("\n")
                start_idx = self._transcript.message_count()
                expanded = getattr(self, '_tool_outputs_expanded', False)
                if expanded or len(full_lines) <= 5:
                    for line in full_lines:
                        self._transcript.append_message(f"   \x1b[2m⎿\x1b[0m {line[:75]}")
                    display_count = len(full_lines)
                else:
                    for line in full_lines[:5]:
                        self._transcript.append_message(f"   \x1b[2m⎿\x1b[0m {line[:75]}")
                    self._transcript.append_message(f"   \x1b[2m… +{len(full_lines) - 5} lines (ctrl+o to expand)\x1b[0m")
                    display_count = 6
                if not hasattr(self, '_tool_output_blocks'):
                    self._tool_output_blocks = []
                self._tool_output_blocks.append({
                    "start_idx": start_idx,
                    "full_lines": full_lines,
                    "display_count": display_count,
                })
            self._app.render()

    # ANSI color constants
    _GREEN = "\x1b[32m"   # success
    _RED = "\x1b[31m"     # error
    _CYAN = "\x1b[36m"    # paths, code
    _BOLD = "\x1b[1m"     # emphasis
    _DIM = "\x1b[2m"      # executing, secondary
    _RESET = "\x1b[0m"

    def _format_and_append(self, msg: Any) -> None:
        """Format a message object for display, matching old TUI style."""
        cls_name = type(msg).__name__
        G = self._GREEN
        R = self._RED
        C = self._CYAN
        B = self._BOLD
        D = self._DIM
        X = self._RESET

        # When a new message arrives, mark the previous executing tool as done (green)
        self._flush_pending_tools()

        if cls_name == "AIThinkingMessage":
            pass  # No separate indicator; footer timer shows activity

        elif cls_name == "ThinkingMessage":
            # thinking 默认折叠（Ctrl+O 展开时才显示）
            thinking = getattr(msg, "thinking", "") or ""
            if thinking.strip() and getattr(self, '_tool_outputs_expanded', False):
                self._ai_stream_idx = -1
                self._transcript.append_message(
                    f" \x1b[2m✶ {thinking.strip()}\x1b[0m"
                )

        elif cls_name == "AIFinalMessage":
            content = getattr(msg, "content", "") or ""
            if content:
                rendered = self._render_markdown(content, final=True)
                self._transcript.append_message(f" ⏺ {rendered}")

        elif cls_name == "ToolCallMessage":
            tool_name = getattr(msg, "tool_name", "tool")
            args = getattr(msg, "args", {})
            first_val = next(iter(args.values()), "") if args else ""
            if isinstance(first_val, str) and len(first_val) > 60:
                first_val = first_val[:60] + "..."
            arg_str = f"({C}{first_val}{X})" if first_val else ""
            # Blinking yellow ⏺ = executing; track index for green update
            idx = self._transcript.message_count()
            self._transcript.append_message(f" \x1b[5;33m⏺\x1b[0m {B}{tool_name}{X}{arg_str}")
            if not hasattr(self, '_tool_start_stack'):
                self._tool_start_stack = []
            self._tool_start_stack.append((idx, tool_name))

        elif cls_name == "SubAgentTaskMessage":
            subagent_type = getattr(msg, "subagent_type", "") or getattr(msg, "display_title", "task")
            desc = getattr(msg, "description", "")
            if desc and len(desc) > 60:
                desc = desc[:60] + "..."
            arg_str = f"({C}{desc}{X})" if desc else ""
            idx = self._transcript.message_count()
            self._transcript.append_message(f" \x1b[5;33m⏺\x1b[0m {B}{subagent_type}{X}{arg_str}")
            if not hasattr(self, '_tool_start_stack'):
                self._tool_start_stack = []
            self._tool_start_stack.append((idx, subagent_type))

        elif cls_name == "TodoListMessage":
            # Plan 走常驻 panel，整列重渲染；transcript 不再保留副本
            todos = getattr(msg, "todos", []) or []
            self._plan_panel.update(todos)

        elif cls_name == "FileReadMessage":
            path = getattr(msg, "path", "")
            content = getattr(msg, "content", "")
            lines = getattr(msg, "lines", 0)
            # Blinking yellow while pending, green if content already present
            idx = self._transcript.message_count()
            if content:
                dot = f"{G}⏺{X}"
            else:
                dot = f"\x1b[5;33m⏺\x1b[0m"
                if not hasattr(self, '_tool_start_stack'):
                    self._tool_start_stack = []
                self._tool_start_stack.append((idx, f"ReadFile({path})"))
            self._transcript.append_message(f" {dot} ReadFile({C}{path}{X})")
            if content:
                preview = content.split("\n")[:5]
                for line in preview:
                    self._transcript.append_message(f"   {D}⎿{X} {line[:75]}")
                if lines > 5:
                    self._transcript.append_message(f"   {D}… +{lines - 5} lines{X}")

        elif cls_name == "GrepHitsMessage":
            pattern = getattr(msg, "pattern", "")
            hits = getattr(msg, "hits", [])
            idx = self._transcript.message_count()
            if hits:
                dot = f"{G}⏺{X}"
            else:
                dot = f"\x1b[5;33m⏺\x1b[0m"
                if not hasattr(self, '_tool_start_stack'):
                    self._tool_start_stack = []
                self._tool_start_stack.append((idx, f"Grep({pattern})"))
            self._transcript.append_message(f" {dot} Grep({C}{pattern}{X})")
            for hit in hits[:5]:
                p = hit.get("path", "")
                ln = hit.get("line", "")
                pv = hit.get("preview", "")[:60]
                self._transcript.append_message(f"   {D}⎿{X} {C}{p}{X}:{ln} {pv}")
            if len(hits) > 5:
                self._transcript.append_message(f"   {D}… +{len(hits) - 5} hits{X}")

        elif cls_name == "LsTreeMessage":
            path = getattr(msg, "path", "")
            entries = getattr(msg, "entries", [])
            idx = self._transcript.message_count()
            if entries:
                dot = f"{G}⏺{X}"
            else:
                dot = f"\x1b[5;33m⏺\x1b[0m"
                if not hasattr(self, '_tool_start_stack'):
                    self._tool_start_stack = []
                self._tool_start_stack.append((idx, f"Ls({path})"))
            self._transcript.append_message(f" {dot} Ls({C}{path}{X})")
            for entry in entries[:8]:
                name = entry.get("name", "") or entry.get("file", "")
                self._transcript.append_message(f"   {D}⎿{X} {name}")
            if len(entries) > 8:
                self._transcript.append_message(f"   {D}… +{len(entries) - 8} entries{X}")

        elif cls_name == "BashExecMessage":
            command = getattr(msg, "command", "")[:60]
            stdout = getattr(msg, "stdout", "")
            rc = getattr(msg, "returncode", 0)
            dot = f"{G}⏺{X}" if rc == 0 else f"{R}⏺{X}"
            self._transcript.append_message(f" {dot} Bash({C}{command}{X})")
            if stdout:
                for line in stdout.split("\n")[:5]:
                    self._transcript.append_message(f"   {D}⎿{X} {line[:75]}")

        elif cls_name == "PythonExecMessage":
            code = getattr(msg, "code", "")[:60]
            stdout = getattr(msg, "stdout", "")
            rc = getattr(msg, "returncode", 0)
            dot = f"{G}⏺{X}" if rc == 0 else f"{R}⏺{X}"
            self._transcript.append_message(f" {dot} Python({C}{code}{X})")
            if stdout:
                for line in stdout.split("\n")[:5]:
                    self._transcript.append_message(f"   {D}⎿{X} {line[:75]}")

        elif cls_name == "PhaseMarkerMessage":
            phase = getattr(msg, "phase", "")
            if phase:
                self._transcript.append_message(f" {D}[{phase}]{X}")

        elif cls_name == "ErrorMessage":
            text = getattr(msg, "text", "") or ""
            self._transcript.append_message(f" {R}[error]{X} {text}")

        elif cls_name == "HumanInputMessage":
            text = getattr(msg, "text", "") or ""
            self._transcript.append_message(f"  {text}")

        else:
            text = getattr(msg, "content", None) or getattr(msg, "text", None)
            if text:
                self._transcript.append_message(f" {text}")

    def _flush_pending_tools(self) -> None:
        """Mark all pending tool dots as green (completed)."""
        if not hasattr(self, '_tool_start_stack'):
            self._tool_start_stack = []
            return
        G = self._GREEN
        B = self._BOLD
        X = self._RESET
        for idx, name in self._tool_start_stack:
            self._transcript.update_message_at(
                idx, f" {G}⏺{X} {B}{name}{X}"
            )
        self._tool_start_stack.clear()


    def _update_thinking_line(self, text: str | None) -> None:
        """Show/hide the thinking status line above the input divider."""
        if text:
            self._thinking_line.style.height = 1
            self._thinking_text.set_value(f" {text}")
        else:
            self._thinking_line.style.height = 0
            self._thinking_text.set_value("")

    def _render_markdown(self, text: str, *, final: bool = False) -> str:
        """Render markdown to ANSI. Streaming uses fast regex; final uses Rich."""
        if self._md_renderer is None:
            from main.qa_agent.ink.components.markdown_renderer import MarkdownRenderer
            w = self._transcript._node.rect.width or 80
            self._md_renderer = MarkdownRenderer(width=max(w - 4, 20))
        else:
            w = self._transcript._node.rect.width
            if w > 0:
                self._md_renderer.set_width(max(w - 4, 20))
        if final:
            return self._md_renderer.render_final(text)
        return self._md_renderer.render_streaming(text)

    def _handle_slash(self, text: str) -> None:
        """Handle slash commands."""
        from main.qa_agent.tui.slash_commands import (
            dispatch_slash_command, ParsedSlashCommand,
            ErrorResult, InfoResult, TextResult, ClearResult, ExitResult,
        )

        parts = text[1:].split(None, 1)
        cmd_name = parts[0] if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        if cmd_name == "exit":
            self._app._running = False
            return
        if cmd_name == "clear":
            self._transcript.clear()
            self._tool_output_blocks.clear()
            self._plan_panel.clear()
            self._app.render()
            return

        # Dispatch to slash_commands module
        parsed = ParsedSlashCommand(command_name=cmd_name, args=cmd_args)
        try:
            result = dispatch_slash_command(parsed, app=self)
            if isinstance(result, ExitResult):
                self._app._running = False
            elif isinstance(result, ClearResult):
                self._transcript.clear()
                self._tool_output_blocks.clear()
                self._plan_panel.clear()
            elif isinstance(result, ErrorResult):
                self._transcript.append_message(f" \x1b[31m✗\x1b[0m {result.text}")
            elif isinstance(result, (InfoResult, TextResult)):
                self._transcript.append_message(f" {result.text}")
        except Exception as e:
            self._transcript.append_message(f" \x1b[31m✗\x1b[0m /{cmd_name}: {e}")
        self._app.render()

    # -- KMS / background task progress API ------------------------------------

    def append_transcript_info(self, msg: str) -> None:
        """Thread-safe: append a status line to transcript (used by kms_command)."""
        with self._app.lock:
            self._transcript.append_message(f"  \x1b[2m{msg}\x1b[0m")
            self._app.render()

    def set_background_status(self, text: str | None) -> None:
        """Thread-safe: update the thinking line above input (used by kms_command)."""
        with self._app.lock:
            self._update_thinking_line(text)
            self._app.render()

    def _cancel_query(self) -> None:
        """Cancel the running query and stop the bridge thread."""
        if self._bridge and self._bridge.is_running:
            # 真正 cancel asyncio task —— bridge 内部走 loop.call_soon_threadsafe(task.cancel)，
            # graph.astream_events 会抛 CancelledError 中止
            self._bridge.cancel()
        self._is_loading = False
        self._streaming_buf.clear()
        self._transcript.append_message(" \x1b[2m[interrupted]\x1b[0m")
        self._footer.update(status="ready")
        self._app.render()

    def _toggle_expand(self) -> None:
        """Toggle expand/collapse all tool output blocks (Ctrl+O)."""
        self._tool_outputs_expanded = not self._tool_outputs_expanded
        # 持久化 verbose 状态
        self._persist_verbose()
        if not self._tool_output_blocks:
            return
        for i, block in enumerate(self._tool_output_blocks):
            start_idx = block["start_idx"]
            full_lines = block["full_lines"]
            old_count = block["display_count"]
            tool_name = block.get("tool_name", "")
            if self._tool_outputs_expanded:
                new_lines = [f"   \x1b[2m⎿\x1b[0m {l[:100]}" for l in full_lines]
            else:
                summary = _tool_result_summary(tool_name, "\n".join(full_lines))
                if summary is not None:
                    new_lines = [f"   \x1b[2m⎿\x1b[0m {l}" for l in summary]
                elif len(full_lines) <= 3:
                    new_lines = [f"   \x1b[2m⎿\x1b[0m {l[:100]}" for l in full_lines]
                else:
                    new_lines = [f"   \x1b[2m⎿\x1b[0m {l[:100]}" for l in full_lines[:3]]
                    new_lines.append(f"   \x1b[2m… +{len(full_lines) - 3} lines (ctrl+o to expand)\x1b[0m")
            self._transcript.replace_range(start_idx, old_count, new_lines)
            new_count = len(new_lines)
            delta = new_count - old_count
            block["display_count"] = new_count
            # Shift all subsequent blocks' start_idx by the delta
            if delta != 0:
                for j in range(i + 1, len(self._tool_output_blocks)):
                    self._tool_output_blocks[j]["start_idx"] += delta
        self._app.render()

    def _persist_verbose(self) -> None:
        """保存 verbose 状态到 ~/.ist/tui_config.json。"""
        try:
            import json
            config_dir = Path.home() / ".ist"
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / "tui_config.json"
            data = {}
            if config_file.exists():
                data = json.loads(config_file.read_text())
            data["verbose"] = self._tool_outputs_expanded
            config_file.write_text(json.dumps(data))
        except Exception:  # noqa: BLE001
            pass

    def _history_up(self) -> None:
        result = self._input_history.up(self._prompt.value)
        if result is not None:
            self._prompt.set_value(result)

    def _history_down(self) -> None:
        result = self._input_history.down(self._prompt.value)
        if result is not None:
            self._prompt.set_value(result)
        else:
            self._prompt.clear()

    def _tab_complete(self) -> None:
        """Tab completion for slash commands."""
        val = self._prompt.value
        if not val.startswith("/"):
            return
        from main.qa_agent.tui.slash_commands import BUILTIN_COMMANDS
        prefix = val[1:].lower()
        matches = [cmd for cmd in BUILTIN_COMMANDS if cmd.name.lower().startswith(prefix)]
        if not matches:
            return
        if len(matches) == 1:
            self._prompt.set_value(f"/{matches[0].name} ")
        else:
            # Show candidates in footer hint
            names = "  ".join(f"/{m.name}" for m in matches[:8])
            self._footer._hint_line.set_value(f" {names}  [Tab to fill · Enter to run]")
            self._prompt.set_value(f"/{matches[0].name} ")
        self._app.render()
