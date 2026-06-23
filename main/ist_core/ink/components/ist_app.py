"""IstInkApp — IST-Core TUI using the Python Ink renderer.

Replaces the Textual-based IstApp. Uses Python Ink renderer for:
- Real terminal cursor positioning (IME follows cursor)
- Full mouse capture (DEC 1000+1002+1003+1006) with a self-implemented
  selection engine (selection.py) — drag-to-select, double-click word,
  triple-click line, release-copy via OSC 52 + pbcopy/xclip, Ctrl+C
  re-copy when a selection is active. Same native UX.
- Efficient incremental screen updates
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from main.ist_core.ink.app import InkApp
from main.ist_core.ink.components.footer import FooterPane
from main.ist_core.ink.components.plan_panel import PlanPanel
from main.ist_core.ink.components.prompt_input import PromptInput
from main.ist_core.ink.components.transcript import Transcript
from main.ist_core.ink.dom import NodeType, create_element, create_text
from main.ist_core.ink.parse_keypress import (
    InputEvent,
    KeyPress,
    MouseEvent,
    PasteEvent,
    UploadEvent,
)





_TOOL_SHORT_NAMES: dict[str, str] = {
    "fs_read": "Read",
    "fs_grep": "Grep",
    "fs_glob": "Glob",
    "fs_ls": "Ls",
    "fs_write": "Write",
    "fs_edit": "Edit",
    "run_shell": "Bash",
    "run_python": "Exec",
    "invoke_skill": "Skill",
    "kb_footprint": "Footprint",
    "kb_bug_search": "BugSearch",
    "write_todos": "TodoWrite",
    "task": "Agent",
}


def _tool_short_name(raw: str) -> str:
    return _TOOL_SHORT_NAMES.get(raw, raw)


def _is_known_fork_skill(skill_name: str) -> bool:
    """从 reducer 的 fork-skill 缓存查 skill 是不是 fork。

    fork skill 的 invoke_skill 调用显示为 Agent(<skill>)（对齐 task → Agent）。
    """
    try:
        from main.ist_core.tui.reducer import _get_fork_skill_names
        return skill_name in _get_fork_skill_names()
    except Exception:  # noqa: BLE001
        return False


def _extract_from_raw(args: dict, key: str) -> str:
    """从 {"raw": "{'key': 'value', ...}"} 中提取指定 key 的值。"""
    import re
    raw = args.get("raw") or ""
    if not isinstance(raw, str):
        return ""
    m = re.search(rf"""['"]?{key}['"]?\s*[:=]\s*['"]([^'"]+)['"]""", raw)
    return m.group(1) if m else ""


def _tool_display_arg(name: str, args: dict) -> str:
    """工具特定参数摘要。"""
    if not args:
        return ""
    if name in ("fs_read", "fs_write",
                "fs_edit", "fs_ls"):
        path = (args.get("file_path") or args.get("path")
                or _extract_from_raw(args, "path")
                or _extract_from_raw(args, "file_path"))
        if isinstance(path, str) and path:
            parts = path.replace("\\", "/").split("/")
            return "/".join(parts[-2:]) if len(parts) > 2 else path
    if name == "fs_grep":
        pattern = (args.get("pattern") or args.get("query")
                   or _extract_from_raw(args, "pattern")
                   or _extract_from_raw(args, "query"))
        return str(pattern)[:60] if pattern else ""
    if name == "fs_glob":
        pattern = args.get("pattern") or _extract_from_raw(args, "pattern")
        return str(pattern)[:60] if pattern else ""
    if name in ("run_shell", "run_python"):
        cmd = args.get("command") or _extract_from_raw(args, "command") or ""
        cmd = str(cmd)
        return (cmd[:60] + "…") if len(cmd) > 60 else cmd
    if name == "invoke_skill":
        skill = args.get("skill") or _extract_from_raw(args, "skill") or ""
        return str(skill)[:40]
    first_val = next(iter(args.values()), "")
    if isinstance(first_val, str) and len(first_val) > 60:
        return first_val[:60] + "…"
    return str(first_val) if first_val else ""


def _tool_result_summary(name: str, output: str) -> list[str] | None:
    """工具特定结果摘要。返回 None = 通用截断；返回 list = 摘要替代。"""
    if name == "fs_read":
        n = output.count("\n") + (1 if output and not output.endswith("\n") else 0)
        return [f"Read \x1b[1m{n}\x1b[0m lines"]
    if name == "fs_glob":
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

        
        
        
        self._app = InkApp(alt_screen=True, mouse=True)

        
        self._transcript = Transcript()
        self._prompt = PromptInput(
            cursor_manager=self._app.cursor,
            on_submit=self._on_submit,
            placeholder="输入消息（/ 触发补全）",
        )
        
        
        self._plan_panel = PlanPanel()

        from main.ist_core.ink.components.ask_user_panel import AskUserPanel
        self._ask_user_panel = AskUserPanel()

        
        self._thinking_line = create_element(NodeType.BOX)
        self._thinking_line.style.height = 0
        self._thinking_text = create_text("")
        self._thinking_line.append_child(self._thinking_text)

        
        self._footer = FooterPane(render_callback=self._app.render, thinking_text_cb=self._update_thinking_line)

        
        self._divider_top = create_element(NodeType.BOX)
        self._divider_top.style.height = 1
        self._divider_top.text_styles.dim = True
        self._divider_text = create_text("")
        self._divider_top.append_child(self._divider_text)

        
        self._divider_bottom = create_element(NodeType.BOX)
        self._divider_bottom.style.height = 1
        self._divider_bottom.text_styles.dim = True
        self._divider_bottom_text = create_text("")
        self._divider_bottom.append_child(self._divider_bottom_text)

        
        
        
        self._app.root.append_child(self._transcript.node)
        self._app.root.append_child(self._plan_panel.node)
        self._app.root.append_child(self._ask_user_panel.node)
        self._app.root.append_child(self._thinking_line)
        self._app.root.append_child(self._divider_top)
        self._app.root.append_child(self._prompt.node)
        self._app.root.append_child(self._divider_bottom)
        self._app.root.append_child(self._footer.node)

        
        self._app.on_input = self._handle_input

        
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
        self._outputs_snapshot: set[str] = set()
        self._tool_outputs_expanded: bool = False
        self._thinking_expanded: bool = False
        self._last_thinking_text: str = ""
        self._tool_output_blocks: list[dict] = []
        self._load_tui_config()
        # ask_user 交互式问答的活跃会话（None=非问答模式）
        self._ask_user: Any = None
        
        
        
        self._ai_stream_idx: int = -1

        
        from main.ist_core.tui.input_history import InputHistory
        self._input_history = InputHistory()
        self._history_idx = -1

        
        from main.ist_core.tui.state import TuiState
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

        
        warnings.filterwarnings("ignore")
        
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
            
            
            try:
                if self._bridge is not None:
                    self._bridge.cancel()
                    self._bridge.join(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
            # 关闭 JSONL sink 文件句柄，避免 fd 泄漏
            _jsonl_sink = getattr(self, "_jsonl_sink", None)
            if _jsonl_sink is not None:
                try:
                    _jsonl_sink.close()
                except Exception:  # noqa: BLE001
                    pass
            sys.stderr = old_stderr
            devnull.close()
            self._app.stop()
            
            
            
            
            if self._bridge is not None and self._bridge.is_running:
                import os as _os
                _os._exit(0)

    def _wait_for_exit(self) -> None:
        """Block until the app is stopped."""
        import time
        while self._app._running:
            time.sleep(0.1)

    def _show_welcome(self) -> None:
        from main.ist_core.agents._llm import ist_core_default_model
        import os
        model = ist_core_default_model()
        self._model = model
        self._footer.update(model=model)

        w = self._app.width

        
        self._divider_text.set_value("─" * w)
        self._divider_bottom_text.set_value("─" * w)

        
        self._transcript.append_message("")
        self._transcript.append_message(f"  \x1b[1mInfoTest Engine v1.0.4\x1b[0m")
        self._transcript.append_message(f"  \x1b[2m{model} · {os.getcwd()}\x1b[0m")
        self._transcript.append_message("")
        self._transcript.append_message(f"  \x1b[2m输入自然语言描述测试分析需求，自动调用工具查阅知识库。\x1b[0m")
        self._transcript.append_message(f"  \x1b[2m/help 查看命令 · /init 初始化项目 · /model 切换模型\x1b[0m")
        self._transcript.append_message("")
        self._app.render()
        self._welcome_shown = True

    def _handle_input(self, event: InputEvent) -> None:
        """Dispatch input events to appropriate handlers."""
        
        
        
        
        with self._app.lock:
            if isinstance(event, KeyPress):
                self._handle_key(event)
            elif isinstance(event, MouseEvent):
                self._handle_mouse(event)
            elif isinstance(event, PasteEvent):
                self._prompt.handle_paste(event.text)
                self._app.render()
            elif isinstance(event, UploadEvent):
                self._handle_upload(event)

    def _handle_upload(self, event: UploadEvent) -> None:
        """处理带外上传信号（Web Terminal 上传文件经 OSC 序列传入）。

        文件已由 web_server 落到 workspace/inputs/<filename>。这里把它的沙箱
        相对路径插入输入框（光标处），用户可继续补充指令再提交。agent 收到的
        是确定的 `inputs/<filename>` 路径，无需任何正则猜测。
        """
        filename = (event.filename or "").strip()
        if not filename:
            return
        # 仅取 basename 防御（前端已是 basename，双保险挡 OSC payload 注入路径）
        import os as _os
        safe = _os.path.basename(filename.replace("\\", "/"))
        if not safe or safe in (".", ".."):
            return
        ref = f"inputs/{safe}"
        # 插入到输入框：已有内容则加空格分隔，避免和用户已敲的字粘连
        existing = self._prompt.value
        if existing and not existing.endswith((" ", "\n")):
            self._prompt.handle_paste(" " + ref + " ")
        else:
            self._prompt.handle_paste(ref + " ")
        self._transcript.append_message(
            f"  \x1b[2m⬆ 已上传 {safe} → {ref}\x1b[0m"
        )
        self._app.render()

    @staticmethod
    def _outputs_dir() -> Path:
        return Path(__file__).resolve().parents[4] / "workspace" / "outputs"

    def _snapshot_outputs(self) -> set[str]:
        """快照 workspace/outputs/ 当前文件集合（用于 run 前后 diff 出新产物）。"""
        d = self._outputs_dir()
        try:
            return {f.name for f in d.iterdir() if f.is_file() and not f.name.startswith(".")}
        except OSError:
            return set()

    def _notify_new_outputs(self) -> None:
        """agent 回合结束后：检测 outputs 新文件，经 OSC 信号通知 Web 前端刷新下载面板。

        与上传方向对称：写文件这件事发生在 agent 工具层（与渲染解耦），所以在
        回合结束的渲染线程里做 diff + 发信号。OSC 7002 不占屏幕单元，穿过 PTY
        被前端识别。本地 TUI 收到该 OSC 会被 ink 解析器忽略（无害）。
        """
        try:
            current = self._snapshot_outputs()
            new_files = current - self._outputs_snapshot
            self._outputs_snapshot = current
            if not new_files:
                return
            import base64 as _b64
            for name in sorted(new_files):
                b64 = _b64.b64encode(name.encode("utf-8")).decode("ascii")
                self._app.write_passthrough(f"\x1b]7002;{b64}\x07")
            names = "、".join(sorted(new_files))
            self._transcript.append_message(
                f"  \x1b[2m⬇ 已生成 {names} → 可点「下载」获取\x1b[0m"
            )
        except Exception:  # noqa: BLE001
            pass

    def _handle_key(self, kp: KeyPress) -> None:
        """Handle keyboard events."""
        import time as _time

        # ask_user 问答模式：拦截按键到会话（Other 文本输入态除外，
        # 那时放行给 PromptInput 收文本，enter/esc 在此处理提交/取消）。
        if getattr(self, "_ask_user", None) is not None:
            if self._ask_user.in_other_input:
                if kp.key in ("return", "enter"):
                    text = self._prompt.value
                    self._prompt.clear()
                    self._ask_user.submit_other_text(text)
                    self._app.render()
                    return
                if kp.key == "escape":
                    self._prompt.clear()
                    self._ask_user.cancel_other_input()
                    return
                consumed = self._prompt.handle_key(kp.key, kp.char)
                if consumed:
                    self._app.render()
                return
            if self._ask_user.handle_key(kp.key, kp.char):
                return


        if self._input_history.in_search_mode:
            if self._handle_search_key(kp):
                return

        
        
        
        from main.ist_core.ink.selection import clear_selection, has_selection
        if has_selection(self._app.selection):
            if kp.key == "ctrl+c":
                self._copy_selection(clear_after=False)
                return
            if kp.key == "escape":
                clear_selection(self._app.selection)
                self._app.notify_selection_change()
                self._app.render()
                return

        
        if kp.key == "ctrl+c":
            now = _time.time()
            if self._is_loading:
                self._cancel_query()
                self._last_ctrl_c = now
            elif now - getattr(self, '_last_ctrl_c', 0) < 1.5:
                
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
                
                
                
                
                
                
                
                self._app._force_full_render()
            return
        if kp.key == "ctrl+o":
            self._toggle_expand()
            return
        if kp.key == "ctrl+t":
            self._toggle_thinking()
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

        
        consumed = self._prompt.handle_key(kp.key, kp.char)
        if consumed:
            self._app.render()

    def _handle_mouse(self, me: "MouseEvent") -> None:
        """Handle mouse events: wheel scrolls transcript; left button does
        the style-based selection (single drag = char, double-click =
        word, triple-click = line, release auto-copies)."""
        
        
        col, row = self._mouse_to_screen_coords(me.x, me.y)

        if me.type == "wheel":
            
            if me.button == 0:
                self._scroll_transcript(-3)
            elif me.button == 1:
                self._scroll_transcript(3)
            return

        
        if me.button != 0:
            return

        if me.type == "press":
            self._handle_left_press(col, row, alt=me.alt)
            return

        if me.type == "move":
            
            
            
            sel = self._app.selection
            if not sel.is_dragging:
                return
            if sel.anchor_span is not None:
                from main.ist_core.ink.selection import extend_selection
                extend_selection(sel, self._app._curr_screen, col, row)
            else:
                from main.ist_core.ink.selection import update_selection
                update_selection(sel, col, row)
            self._app.notify_selection_change()
            self._app.render()
            return

        if me.type == "release":
            from main.ist_core.ink.selection import (
                finish_selection,
                has_selection,
            )
            sel = self._app.selection
            was_dragging = sel.is_dragging
            finish_selection(sel)
            
            
            
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
        
        
        if click_count > 3:
            click_count = 3

        from main.ist_core.ink.selection import (
            select_line_at,
            select_word_at,
            start_selection,
        )

        sel = self._app.selection
        
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

        clear_after=True drops the highlight after copying; False keeps it 
        visible so subsequent Ctrl+C can re-copy the same range.
        """
        from main.ist_core.ink.selection import (
            clear_selection,
            get_selected_text,
            has_selection,
        )
        from main.ist_core.ink.termio.osc import set_clipboard

        sel = self._app.selection
        if not has_selection(sel):
            return
        text = get_selected_text(sel, self._app._curr_screen)
        if not text:
            return
        seq = set_clipboard(text)
        if seq:
            self._app._terminal.write(seq)
        
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
            
            draft = self._input_history.exit_search(restore=True)
            self._prompt.set_value(draft)
            self._footer.set_search_state(query=None, match=None)
            self._app.render()
            return True
        
        if kp.char and len(kp.char) == 1 and kp.char.isprintable():
            new_q = self._input_history.search_query + kp.char
            result = self._input_history.update_search_query(new_q)
            self._update_search_ui(result)
            return True
        
        
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
            
            
            self._input_history.add(text)

            
            
            if text.startswith("/"):
                self._handle_slash(text)
                return

        if pre_expanded is not None:
            expanded = pre_expanded
        else:
            
            
            
            
            expanded = self._prompt.consume_pasted_refs(text).replace("↵", "\n")

        
        if self._welcome_shown:
            self._transcript.clear()
            self._welcome_shown = False

        
        from main.ist_core.tui.input_preprocessor import preprocess_file_paths
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
                
                self._transcript.append_message(f"  \x1b[2m{preprocess_status}\x1b[0m")
                expanded = processed_text

        
        for line in expanded.split("\n"):
            self._transcript.append_message(f"  {line}")
        self._transcript.append_message("")
        
        self._transcript.append_message("")
        self._footer.update(status="esc to interrupt")
        self._is_loading = True
        self._run_start_time = __import__('time').time()
        # 快照 outputs 基线，回合结束时 diff 出 agent 新生成的可下载文件
        self._outputs_snapshot = self._snapshot_outputs()
        self._app.render()

        
        
        
        self._run_via_bridge(expanded)

    def _submit_expanded(self, expanded: str) -> None:
        """Submit raw multi-line content directly, bypassing the prompt
        editor. Used by repeat-paste auto-submit."""
        
        
        num_lines = expanded.count("\n")
        history_label = (
            f"[Pasted text +{num_lines} lines]" if num_lines else expanded
        )
        self._input_history.add(history_label)
        
        self._prompt.clear_pasted_refs()
        self._submit("", pre_expanded=expanded)

    def _run_via_bridge(self, text: str) -> None:
        """Run query through GraphBridge in background thread."""
        from langchain_core.messages import HumanMessage
        from main.ist_core.tui.bridge import GraphBridge
        from main.ist_core.tui.message_model import MessageSnapshot

        if self._bridge is None:
            thread_id = self._thread_id or uuid.uuid4().hex[:12]
            from main.ist_core.sinks.jsonl_sink import JsonlFileSink
            from pathlib import Path
            
            
            _project_root = Path(__file__).resolve().parents[4]
            jsonl_sink = JsonlFileSink(log_dir=_project_root / "runtime" / "logs")
            self._jsonl_sink = jsonl_sink
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
        self._last_thinking_idx = -1
        self._suppress_thinking_until_done = False
        self._subagent_inner_summaries = {}
        # B2：新 run 清空 tool_use 行号映射，避免旧行号污染本轮插入定位
        self._tool_use_row = {}
        self._transcript.append_message("")
        self._bridge.start(initial_state)

    @staticmethod
    def _build_graph():
        from main.ist_core.graph import build_ist_core_graph
        return build_ist_core_graph(checkpointer=True)

    def _on_snapshot(self, snapshot: Any) -> None:
        """Handle MessageSnapshot from TuiSink (called from bridge thread).

        适配层：把 MessageSnapshot 翻译成旧 _on_ui_event_locked 的渲染调用。
        bridge worker 是后台线程；DOM 修改必须和 ink-input 线程串行化。
        """
        with self._app.lock:
            self._on_snapshot_locked(snapshot)

    def _on_snapshot_locked(self, snapshot: Any) -> None:
        """Diff snapshot against previous state and render changes."""
        from main.ist_core.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_TOOL_RESULT, BLOCK_THINKING,
            BLOCK_PHASE_MARKER, BLOCK_EVIDENCE, BLOCK_FINDING,
        )
        prev = getattr(self, '_prev_snapshot', None)
        self._prev_snapshot = snapshot

        
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
            self._footer.update(
                llm_phase=snapshot.llm_phase or "output",
                output_token_count=snapshot.output_token_count,
            )
            self._app.render()
            return

        
        if prev and prev.streaming_text is not None and snapshot.streaming_text is None:
            self._ai_stream_idx = -1

        
        prev_count = len(prev.messages) if prev else 0
        new_msgs = snapshot.messages[prev_count:]
        for msg in new_msgs:
            for block in msg.content:
                self._render_content_block(block, msg)

        
        if snapshot.usage:
            input_t = snapshot.usage.get("input_tokens", 0) or 0
            output_t = snapshot.usage.get("output_tokens", 0) or 0
            cache_hit = snapshot.usage.get("prompt_cache_hit_tokens", 0) or 0
            total = snapshot.usage.get("total_tokens", 0) or (input_t + output_t)
            if total and total != self._tokens_used:
                self._tokens_used = total
                self._footer.update(
                    tokens_used=total,
                    input_tokens=input_t,
                    output_tokens=output_t,
                    llm_phase=snapshot.llm_phase,
                    output_token_count=snapshot.output_token_count,
                    cache_hit_tokens=cache_hit,
                )

        
        if snapshot.status == "done" and (not prev or prev.status != "done"):
            self._flush_pending_tools()
            self._is_loading = False
            self._ai_stream_idx = -1

            if self._plan_panel.is_visible:
                self._plan_panel.mark_all_done()
            self._footer.update(status="ready", llm_phase="", output_token_count=0)
            # 回合结束：检测 outputs 新文件，发 OSC 通知 Web 前端刷新下载面板。
            # 这是每轮真正的完成信号（snapshot.status done）；diff 后更新快照，
            # 故与其他完成路径重复调用也幂等（第二次 new_files 为空）。
            self._notify_new_outputs()

        elif snapshot.status == "error" and (not prev or prev.status != "error"):
            self._flush_pending_tools()
            self._is_loading = False
            self._ai_stream_idx = -1
            
            if snapshot.messages:
                last = snapshot.messages[-1]
                for b in last.content:
                    if b.type == BLOCK_TEXT and b.text:
                        self._transcript.append_message(
                            f" \x1b[31m[error]\x1b[0m {b.text}"
                        )
                        break
            self._footer.update(status="error", llm_phase="", output_token_count=0)

        self._app.render()

    def _place_result_lines(self, tool_use_id: str, lines: list[str]) -> int:
        """B2：把结果行放到对应 tool_use 行的「结果区」末尾，返回起始行号。

        - 找到该 tool_use 的 ⏺ 行号，结果插到它下方已有结果行之后
          （同一 tool 多段结果按序，且不串到下一个 tool 的 ⏺ 之前）。
        - 找不到对应行（无 tuid / 已被偏移丢失）→ 兜底 append 末尾。
        """
        row_map = getattr(self, "_tool_use_row", {})
        anchor = row_map.get(tool_use_id, -1) if tool_use_id else -1
        if anchor < 0:
            # 兜底：append 末尾（行为同改造前）
            at = self._transcript.message_count()
            for ln in lines:
                self._transcript.append_message(ln)
            return at
        # 插入点 = anchor 行下方，跳过该 tool 已插入的结果行（⎿ / … 开头），
        # 但遇到下一个 ⏺ 行就停（不串到别的 tool）
        insert_at = anchor + 1
        msgs = self._transcript._messages
        while insert_at < len(msgs):
            stripped = msgs[insert_at].lstrip()
            if stripped.startswith("⎿") or "⎿" in msgs[insert_at] or stripped.startswith("…"):
                insert_at += 1
            else:
                break
        self._insert_result_lines(insert_at, lines)
        return insert_at

    def _insert_result_lines(self, at_idx: int, lines: list[str]) -> None:
        """B2：在 at_idx 处插入结果行，并统一偏移所有 ≥ at_idx 的行索引状态。

        把 tool_result 的 ⎿ 行插到对应 tool_use 行下方（而非 append 末尾），
        使并行工具的每个 ⏺ 下面紧跟自己的结果。集中处理偏移，避免索引漂移。
        """
        n = len(lines)
        if n <= 0:
            return
        self._transcript.replace_range(at_idx, 0, lines)  # count=0 → 纯插入
        # 统一偏移所有受影响的行索引状态
        if getattr(self, "_ai_stream_idx", -1) >= at_idx:
            self._ai_stream_idx += n
        if getattr(self, "_last_thinking_idx", -1) >= at_idx:
            self._last_thinking_idx += n
        if hasattr(self, "_tool_use_row"):
            for k, v in self._tool_use_row.items():
                if v >= at_idx:
                    self._tool_use_row[k] = v + n
        if hasattr(self, "_tool_start_stack"):
            self._tool_start_stack = [
                (i + n if i >= at_idx else i, name)
                for (i, name) in self._tool_start_stack
            ]
        if hasattr(self, "_tool_output_blocks"):
            for blk in self._tool_output_blocks:
                if blk.get("start_idx", -1) >= at_idx:
                    blk["start_idx"] += n

    def _render_content_block(self, block: Any, msg: Any) -> None:
        """Render a single ContentBlock to the transcript."""
        from main.ist_core.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_TOOL_RESULT, BLOCK_THINKING,
            BLOCK_PHASE_MARKER, BLOCK_EVIDENCE, BLOCK_FINDING,
        )
        B = self._BOLD
        C = self._CYAN
        D = self._DIM
        X = self._RESET

        
        
        
        
        parent_id = getattr(msg, "parent_tool_use_id", "") or ""
        if parent_id:
            self._render_subagent_inner_block(block, parent_id)
            return

        if block.type == BLOCK_TEXT and block.text:
            self._flush_pending_tools()
            rendered = self._render_markdown(block.text, final=True)
            self._ai_stream_idx = -1
            self._transcript.append_message(f" ⏺ {rendered}")

        elif block.type == BLOCK_THINKING and block.thinking:

            if getattr(self, '_suppress_thinking_until_done', False):
                return
            self._ai_stream_idx = -1
            # 每条 thinking 独立 append（reducer 已按独立 message + uuid 管理）。
            # 不再删除上一条 thinking 行——thinking 之间几乎必夹 tool_use，
            # 旧的 replace_range 删除会误删/错位后续行，导致 thinking 显示消失。
            if self._thinking_expanded:
                self._transcript.append_message(
                    f" {D}\x1b[3m∴ {block.thinking.strip()}{X}"
                )
            else:
                self._transcript.append_message(
                    f" {D}\x1b[3m∴ Thinking{X} {D}(ctrl+t to expand){X}"
                )
            # 记录最后一条 thinking 的行号 + 全文，供 ctrl+t 展开/折叠切换
            self._last_thinking_idx = self._transcript.message_count() - 1
            self._last_thinking_text = block.thinking.strip()

        elif block.type == BLOCK_TOOL_USE:
            self._ai_stream_idx = -1
            raw_name = block.name or "tool"

            if raw_name == "write_todos":
                return
            # ask_user 的交互与结果完全由 ask_user 面板负责，
            # 不渲染标准工具行（避免重复 + 暴露内部工具名/参数）。
            if raw_name == "ask_user":
                return
            args = dict(block.input) if block.input else {}
            display_name = _tool_short_name(raw_name)
            
            
            if raw_name == "invoke_skill":
                skill_name = args.get("skill") or _extract_from_raw(args, "skill") or ""
                if skill_name and _is_known_fork_skill(skill_name):
                    display_name = "Agent"
            first_val = _tool_display_arg(raw_name, args)
            arg_str = f"({C}{first_val}{X})" if first_val else ""
            idx = self._transcript.message_count()
            display_full = f"{display_name}{X}{arg_str}"
            if block.status == "done":
                self._transcript.append_message(
                    f" \x1b[32m⏺\x1b[0m {B}{display_full}"
                )
            elif block.status == "error":
                self._transcript.append_message(
                    f" \x1b[31m⏺\x1b[0m {B}{display_full}"
                )
            else:
                self._transcript.append_message(
                    f" \x1b[5;33m⏺\x1b[0m {B}{display_full}"
                )
                if not hasattr(self, '_tool_start_stack'):
                    self._tool_start_stack = []
                self._tool_start_stack.append((idx, display_full))
            # B2：记录 tool_use_id → ⏺ 行号，供 tool_result 归位插到其下方
            tuid = getattr(block, "tool_use_id", "") or ""
            if tuid:
                if not hasattr(self, "_tool_use_row"):
                    self._tool_use_row = {}
                self._tool_use_row[tuid] = idx

        elif block.type == BLOCK_TOOL_RESULT:
            self._ai_stream_idx = -1
            # ask_user 结果由 ask_user 面板的完成提示负责，跳过标准结果行
            if (block.name or "") == "ask_user":
                return
            if block.output:
                raw_name = block.name or ""
                tuid = getattr(block, "tool_use_id", "") or ""
                # fork skill (verifier) 完成：折叠为单行 Done
                if (
                    raw_name == "invoke_skill"
                    and "VERDICT:" in block.output
                    and "LEVEL:" in block.output
                ):
                    self._suppress_thinking_until_done = True
                    self._place_result_lines(
                        tuid, [f"   {D}⎿{X} {D}Done (Agent completed){X}"]
                    )
                    return
                full_lines = block.output.split("\n")
                expanded = getattr(self, '_tool_outputs_expanded', False)

                summary = _tool_result_summary(raw_name, block.output)
                if summary is not None and not expanded:
                    result_lines = [f"   {D}⎿{X} {line}" for line in summary]
                elif expanded or len(full_lines) <= 3:
                    result_lines = [f"   {D}⎿{X} {line[:100]}" for line in full_lines]
                else:
                    result_lines = [f"   {D}⎿{X} {line[:100]}" for line in full_lines[:3]]
                    result_lines.append(
                        f"   {D}… +{len(full_lines) - 3} lines (ctrl+o to expand){X}"
                    )
                display_count = len(result_lines)
                # B2：把结果插到对应 tool_use 行下方（并行工具结果归位）
                start_idx = self._place_result_lines(tuid, result_lines)
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

            todos = block.payload.get("todos") if block.payload else None
            if todos and hasattr(self, '_plan_panel'):
                self._plan_panel.update(todos)

        elif block.type == "ask_user":
            payload = dict(block.payload) if block.payload else {}
            self._begin_ask_user(
                payload.get("question_id", ""),
                list(payload.get("questions", [])),
            )

    def _begin_ask_user(self, question_id: str, questions: list) -> None:
        """进入 ask_user 交互式问答模式（渲染到固定面板，不入 transcript）。"""
        if not question_id or not questions:
            return
        from main.ist_core.ink.components.ask_user_view import AskUserSession
        self._ask_user = AskUserSession(
            question_id,
            questions,
            render=self._render_ask_user,
            on_finish=self._finish_ask_user,
        )
        self._render_ask_user()

    def _render_ask_user(self) -> None:
        """把当前问答会话整列重渲染到固定面板（不随 transcript 滚动）。"""
        if self._ask_user is None:
            self._ask_user_panel.clear()
            self._app.render()
            return
        self._ask_user_panel.update(self._ask_user.render_lines())
        self._app.render()

    def _finish_ask_user(self) -> None:
        """问答结束（提交/取消）：清面板，在 transcript 留一行简洁结果。"""
        session = self._ask_user
        self._ask_user = None
        self._ask_user_panel.clear()
        # A3：留完成提示，让用户/对话历史看到选择结果
        try:
            if session is not None:
                summary = session.result_summary()
                if summary:
                    self._transcript.append_message(summary)
        except Exception:  # noqa: BLE001
            pass
        self._app.render()

    def _render_subagent_inner_block(self, block: Any, parent_id: str) -> None:
        """fork subagent 内部 ContentBlock 折叠成 ⎿ 进度行（接 snapshot 路径）。

        消费 ContentBlock 并进行展示：
        - BLOCK_TEXT / BLOCK_THINKING → ``⎿ ∴ Thinking``（verifier 研究报告全文不平铺）
        - BLOCK_TOOL_USE → ``⎿ <ShortName>(<arg>)``
        - BLOCK_TOOL_RESULT → 跳过（fork 内部工具结果不刷屏）
        每个 parent_id 最多显示 _SUBAGENT_INNER_MAX_LINES 行，超出折成省略提示。
        """
        from main.ist_core.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_THINKING,
        )
        D = self._DIM
        C = self._CYAN
        X = self._RESET

        line = ""
        if block.type in (BLOCK_TEXT, BLOCK_THINKING):
            line = f"   {D}⎿ ∴ Thinking{X}"
        elif block.type == BLOCK_TOOL_USE:
            raw_name = block.name or "tool"
            if raw_name == "write_todos":
                return
            display = _tool_short_name(raw_name)
            args = dict(block.input) if block.input else {}
            arg = _tool_display_arg(raw_name, args)
            line = f"   {D}⎿{X} {display}" + (f"({C}{arg}{X})" if arg else "")
        else:
            return

        if not hasattr(self, "_subagent_inner_summaries"):
            self._subagent_inner_summaries = {}
        count = self._subagent_inner_summaries.get(parent_id, 0)
        expanded = getattr(self, "_tool_outputs_expanded", False)
        if expanded or count < self._SUBAGENT_INNER_MAX_LINES:
            self._transcript.append_message(line)
        elif count == self._SUBAGENT_INNER_MAX_LINES:
            self._transcript.append_message(
                f"   {D}… (more subagent activity; ctrl+o to expand){X}"
            )
        
        self._subagent_inner_summaries[parent_id] = count + 1

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
            self._ai_stream_idx = -1
            
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
            
            import time as _time
            elapsed = _time.time() - self._run_start_time if self._run_start_time else 0
            if elapsed > 0:
                from main.ist_core.ink.components.footer import _format_elapsed
                elapsed_str = _format_elapsed(elapsed)
                self._transcript.append_message(
                    f" \x1b[2m⏱ {elapsed_str} · {self._tokens_used:,} tokens\x1b[0m"
                )
            self._footer.update(status="ready", tokens_used=self._tokens_used)
            self._tool_output_blocks.clear()
            self._notify_new_outputs()
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
            
            idx = self._transcript.message_count()
            self._transcript.append_message(f" \x1b[5;33m⏺\x1b[0m \x1b[1m{tool_name}\x1b[0m...")
            
            if not hasattr(self, '_tool_start_stack'):
                self._tool_start_stack = []
            self._tool_start_stack.append((idx, tool_name))
            self._app.render()

        elif kind == "tool_done":
            self._ai_stream_idx = -1
            extra = event.extra or {}
            tool_name = extra.get("tool_name", "")
            result = extra.get("result", "")
            
            if hasattr(self, '_tool_start_stack') and self._tool_start_stack:
                idx, name = self._tool_start_stack.pop(0)
                self._transcript.update_message_at(
                    idx, f" \x1b[32m⏺\x1b[0m \x1b[1m{name}\x1b[0m"
                )
            
            
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

    
    _GREEN = "\x1b[32m"
    _RED = "\x1b[31m"
    _CYAN = "\x1b[36m"
    _BOLD = "\x1b[1m"
    _DIM = "\x1b[2m"
    _RESET = "\x1b[0m"

    _SUBAGENT_INNER_MAX_LINES = 3

    def _render_subagent_inner_message(
        self,
        msg: Any,
        parent_id: str,
        cls_name: str,
        D: str,
        X: str,
        C: str,
    ) -> None:
        """fork subagent 内部消息折叠为简短摘要行。

        策略：
        - ToolCallMessage / FileReadMessage / GrepHitsMessage / LsTreeMessage：
          展示 "⎿ <ToolShortName>(<arg>)" 单行
        - AIThinkingMessage / ThinkingMessage：折叠为 "⎿ ∴ Thinking" 单行
        - AIFinalMessage（最后那条 5000+ 字研究报告）：折叠为 "⎿ +N lines (ctrl+o to expand)"
        - 重复同类消息合并（连续 grep 不刷屏）
        """
        
        if not hasattr(self, "_subagent_inner_summaries"):
            self._subagent_inner_summaries: dict[str, int] = {}
        count = self._subagent_inner_summaries.get(parent_id, 0)
        expanded = getattr(self, "_tool_outputs_expanded", False)

        line: str = ""
        if cls_name == "ToolCallMessage":
            tool_name = getattr(msg, "tool_name", "") or "tool"
            display = _tool_short_name(tool_name)
            args = {}
            try:
                content = getattr(msg, "content", None)
                if content and hasattr(content, "input"):
                    args = dict(content.input or {})
            except Exception:  # noqa: BLE001
                pass
            arg = _tool_display_arg(tool_name, args)
            line = f"   {D}⎿{X} {display}" + (f"({C}{arg}{X})" if arg else "")
        elif cls_name == "FileReadMessage":
            path = getattr(msg, "path", "")
            n = getattr(msg, "line_count", 0) or 0
            short = path.split("/")[-1] if path else ""
            line = f"   {D}⎿{X} Read {short} ({n} lines)"
        elif cls_name == "GrepHitsMessage":
            pat = getattr(msg, "pattern", "") or ""
            n = getattr(msg, "match_count", 0) or 0
            line = f"   {D}⎿{X} Grep {C}{pat[:40]}{X} → {n} matches"
        elif cls_name == "LsTreeMessage":
            path = getattr(msg, "path", "")
            line = f"   {D}⎿{X} Ls {C}{path}{X}"
        elif cls_name in ("AIThinkingMessage", "ThinkingMessage"):
            line = f"   {D}⎿ ∴ Thinking{X}"
        elif cls_name == "AIFinalMessage":
            text = getattr(msg, "text", "") or ""
            n = len(text.splitlines())
            line = f"   {D}⎿ +{n} lines (verifier report; ctrl+o to expand){X}"
        else:
            return

        if expanded or count < self._SUBAGENT_INNER_MAX_LINES:
            self._transcript.append_message(line)
        elif count == self._SUBAGENT_INNER_MAX_LINES:
            self._transcript.append_message(
                f"   {D}… (more subagent activity; ctrl+o to expand){X}"
            )
        

        self._subagent_inner_summaries[parent_id] = count + 1

    def _format_and_append(self, msg: Any) -> None:
        """Format a message object for display, matching old TUI style."""
        cls_name = type(msg).__name__
        G = self._GREEN
        R = self._RED
        C = self._CYAN
        B = self._BOLD
        D = self._DIM
        X = self._RESET

        
        self._flush_pending_tools()

        
        
        
        
        parent_id = getattr(msg, "parent_tool_use_id", "") or ""
        if parent_id:
            self._render_subagent_inner_message(msg, parent_id, cls_name, D, X, C)
            return

        if cls_name == "AIThinkingMessage":
            pass

        elif cls_name == "ThinkingMessage":
            thinking = getattr(msg, "thinking", "") or ""
            if thinking.strip() and self._thinking_expanded:
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
            
            todos = getattr(msg, "todos", []) or []
            self._plan_panel.update(todos)

        elif cls_name == "FileReadMessage":
            path = getattr(msg, "path", "")
            content = getattr(msg, "content", "")
            lines = getattr(msg, "lines", 0)
            
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
            from main.ist_core.ink.components.markdown_renderer import MarkdownRenderer
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
        from main.ist_core.tui.slash_commands import (
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
            
            
            self._bridge.cancel()
        self._is_loading = False
        self._streaming_buf.clear()
        self._transcript.append_message(" \x1b[2m[interrupted]\x1b[0m")
        self._footer.update(status="ready")
        self._app.render()

    def _toggle_expand(self) -> None:
        """Toggle expand/collapse all tool output blocks (Ctrl+O)."""
        self._tool_outputs_expanded = not self._tool_outputs_expanded
        
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
            
            if delta != 0:
                for j in range(i + 1, len(self._tool_output_blocks)):
                    self._tool_output_blocks[j]["start_idx"] += delta
        self._app.render()

    def _load_tui_config(self) -> None:
        """从 ~/.ist/tui_config.json 恢复持久化状态。"""
        try:
            import json
            config_file = Path.home() / ".ist" / "tui_config.json"
            if config_file.exists():
                data = json.loads(config_file.read_text())
                self._tool_outputs_expanded = bool(data.get("verbose", False))
                self._thinking_expanded = bool(data.get("thinking_expanded", False))
        except Exception:  # noqa: BLE001
            pass

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
            data["thinking_expanded"] = self._thinking_expanded
            config_file.write_text(json.dumps(data))
        except Exception:  # noqa: BLE001
            pass

    def _toggle_thinking(self) -> None:
        """Toggle expand/collapse the last thinking block (Ctrl+T)."""
        D = self._DIM
        X = self._RESET
        self._thinking_expanded = not self._thinking_expanded
        self._persist_verbose()
        idx = getattr(self, '_last_thinking_idx', -1)
        text = getattr(self, '_last_thinking_text', "")
        if idx < 0 or not text:
            return
        if self._thinking_expanded:
            new_line = f" {D}\x1b[3m∴ {text}{X}"
        else:
            new_line = f" {D}\x1b[3m∴ Thinking{X} {D}(ctrl+t to expand){X}"
        self._transcript.update_message_at(idx, new_line)
        self._app.render()

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
        from main.ist_core.tui.slash_commands import BUILTIN_COMMANDS
        prefix = val[1:].lower()
        matches = [cmd for cmd in BUILTIN_COMMANDS if cmd.name.lower().startswith(prefix)]
        if not matches:
            return
        if len(matches) == 1:
            self._prompt.set_value(f"/{matches[0].name} ")
        else:
            
            names = "  ".join(f"/{m.name}" for m in matches[:8])
            self._footer._hint_line.set_value(f" {names}  [Tab to fill · Enter to run]")
            self._prompt.set_value(f"/{matches[0].name} ")
        self._app.render()
