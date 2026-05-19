"""IstInkApp — IST-Core TUI using the Python Ink renderer.

Replaces the Textual-based IstApp. Uses Python Ink renderer for:
- Real terminal cursor positioning (IME follows cursor)
- No mouse capture (terminal native text selection works)
- Efficient incremental screen updates
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Callable

from main.qa_agent.ink.app import InkApp
from main.qa_agent.ink.components.footer import FooterPane
from main.qa_agent.ink.components.prompt_input import PromptInput
from main.qa_agent.ink.components.transcript import Transcript
from main.qa_agent.ink.dom import NodeType, create_element, create_text
from main.qa_agent.ink.parse_keypress import (
    InputEvent,
    KeyPress,
    MouseEvent,
    PasteEvent,
)


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

        # Ink app (no mouse capture)
        self._app = InkApp(alt_screen=True, mouse=False)

        # Components
        self._transcript = Transcript()
        self._prompt = PromptInput(
            cursor_manager=self._app.cursor,
            on_submit=self._on_submit,
            placeholder="输入消息（/ 触发补全）",
        )
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

        # Assemble layout: transcript + thinking_line + divider_top + prompt + divider_bottom + footer
        self._app.root.append_child(self._transcript.node)
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
                    self._bridge.join(timeout=2.0)
            except Exception:  # noqa: BLE001
                pass
            sys.stderr = old_stderr
            devnull.close()
            self._app.stop()

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
        self._transcript.append_message(f"  \x1b[1mInfoTest Engine v1.0.0\x1b[0m")
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
            elif isinstance(event, PasteEvent):
                self._prompt.handle_paste(event.text)
                self._app.render()

    def _handle_key(self, kp: KeyPress) -> None:
        """Handle keyboard events."""
        import time as _time

        # Global keys
        if kp.key == "ctrl+c":
            now = _time.time()
            if self._is_loading:
                self._cancel_query()
                self._last_ctrl_c = now
            elif now - getattr(self, '_last_ctrl_c', 0) < 1.5:
                # 退出前先把 bridge worker 收尾，避免 daemon 线程在
                # interpreter shutdown 阶段还在 submit 新 future
                if self._bridge is not None:
                    try:
                        self._bridge.cancel()
                        self._bridge.join(timeout=1.5)
                    except Exception:  # noqa: BLE001
                        pass
                self._app._running = False
            else:
                self._last_ctrl_c = now
                self._transcript.append_message(" \x1b[2m(press ctrl+c again to exit)\x1b[0m")
                self._app.render()
            return
        if kp.key == "ctrl+d":
            if self._bridge is not None:
                try:
                    self._bridge.cancel()
                    self._bridge.join(timeout=1.5)
                except Exception:  # noqa: BLE001
                    pass
            self._app._running = False
            return
        if kp.key == "escape":
            if self._is_loading:
                self._cancel_query()
            else:
                self._prompt.clear()
                self._app.render()
            return
        if kp.key == "ctrl+o":
            self._toggle_expand()
            return
        if kp.key == "ctrl+l":
            self._app._force_full_render()
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

    def _on_submit(self, text: str) -> None:
        """Called when user presses Enter in prompt."""
        self._submit(text)

    def _submit(self, text: str) -> None:
        """Submit user input to the agent."""
        text = text.strip()
        if not text:
            return

        # Save to history (persistent)
        self._input_history.add(text)

        # Slash command?
        if text.startswith("/"):
            self._handle_slash(text)
            return

        # Clear welcome box on first submit
        if self._welcome_shown:
            self._transcript.clear()
            self._welcome_shown = False

        # Show user message (indented, no "> " prefix — matches old TUI)
        self._transcript.append_message(f"  {text}")
        self._transcript.append_message("")
        # Placeholder for streaming AI response (will be updated by update_ai_token/append)
        self._transcript.append_message("")
        self._footer.update(status="esc to interrupt")
        self._is_loading = True
        self._run_start_time = __import__('time').time()
        self._app.render()

        # Run query via GraphBridge (same pattern as Textual app)
        self._run_via_bridge(text)

    def _run_via_bridge(self, text: str) -> None:
        """Run query through GraphBridge in background thread."""
        from main.qa_agent.tui.bridge import GraphBridge
        from main.qa_agent.tui.sink import IstUiEvent

        if self._bridge is None:
            thread_id = self._thread_id or uuid.uuid4().hex[:12]
            self._bridge = GraphBridge(
                graph_factory=self._build_graph,
                post=self._on_ui_event,
                thread_id=thread_id,
            )

        if self._bridge.is_running:
            self._transcript.append_message("(busy — 等待当前回合完成)")
            self._app.render()
            return

        initial_state = {
            "task_type": self._task_type,
            "user_input": text,
            "messages": [],
        }
        self._streaming_buf = []
        self._transcript.append_message("")  # placeholder for streaming
        self._bridge.start(initial_state)

    @staticmethod
    def _build_graph():
        from main.qa_agent.graph import build_qa_agent_graph
        return build_qa_agent_graph(checkpointer=True)

    def _on_ui_event(self, event: Any) -> None:
        """Handle UI events from TuiSink (called from bridge thread)."""
        # bridge worker 是后台线程；DOM 修改必须和 ink-input 线程的按键
        # 处理串行化，否则会和 _handle_input 同时改 children / TextNode，
        # 导致一行内 AI 输出和工具输出字符穿插。
        with self._app.lock:
            self._on_ui_event_locked(event)

    def _on_ui_event_locked(self, event: Any) -> None:
        kind = event.kind

        if kind == "update_ai_token":
            self._flush_pending_tools()
            chunk = (event.extra or {}).get("chunk", "")
            self._streaming_buf.append(chunk)
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
                rendered = self._render_markdown(final)
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
            if result:
                full_lines = str(result).split("\n")
                start_idx = self._transcript.message_count()
                expanded = getattr(self, '_tool_outputs_expanded', False)
                if expanded or len(full_lines) <= 5:
                    # Show all lines
                    for line in full_lines:
                        self._transcript.append_message(f"   \x1b[2m⎿\x1b[0m {line[:75]}")
                    display_count = len(full_lines)
                else:
                    # Collapsed: 5 lines + hint
                    for line in full_lines[:5]:
                        self._transcript.append_message(f"   \x1b[2m⎿\x1b[0m {line[:75]}")
                    self._transcript.append_message(f"   \x1b[2m… +{len(full_lines) - 5} lines (ctrl+o to expand)\x1b[0m")
                    display_count = 6
                # Track for Ctrl+O toggle
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
            # Qwen3.6 + enable_thinking 输出的 reasoning_content；DashScope OpenAI
            # 兼容端点把它放在 additional_kwargs.reasoning_content。渲染成 dim 灰
            # ✶ 前缀 + 整段保留换行，工具调用之间能看到模型的思考过程
            thinking = getattr(msg, "thinking", "") or ""
            if thinking.strip():
                self._ai_stream_idx = -1
                # 整段拼成单条多行消息（transcript 已按 \n 算视觉行高）
                self._transcript.append_message(
                    f" \x1b[2m✶ {thinking.strip()}\x1b[0m"
                )

        elif cls_name == "AIFinalMessage":
            content = getattr(msg, "content", "") or ""
            if content:
                rendered = self._render_markdown(content)
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

    def _render_markdown(self, text: str) -> str:
        """Basic Markdown rendering: bold, inline code, bullets."""
        import re
        B = self._BOLD
        C = self._CYAN
        R = self._RESET
        # Bold: **text** or __text__
        text = re.sub(r'\*\*(.+?)\*\*', f'{B}\\1{R}', text)
        text = re.sub(r'__(.+?)__', f'{B}\\1{R}', text)
        # Inline code: `code`
        text = re.sub(r'`([^`]+)`', f'{C}\\1{R}', text)
        # Bullet points: - item or * item at line start
        text = re.sub(r'^(\s*)[-*]\s', r'\1• ', text, flags=re.MULTILINE)
        return text

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
            elif isinstance(result, ErrorResult):
                self._transcript.append_message(f" \x1b[31m✗\x1b[0m {result.text}")
            elif isinstance(result, (InfoResult, TextResult)):
                self._transcript.append_message(f" {result.text}")
        except Exception as e:
            self._transcript.append_message(f" \x1b[31m✗\x1b[0m /{cmd_name}: {e}")
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
        if not self._tool_output_blocks:
            return
        # Process blocks in order; after each replacement, adjust subsequent block indices
        for i, block in enumerate(self._tool_output_blocks):
            start_idx = block["start_idx"]
            full_lines = block["full_lines"]
            old_count = block["display_count"]
            if self._tool_outputs_expanded:
                new_lines = [f"   \x1b[2m⎿\x1b[0m {l[:75]}" for l in full_lines]
            else:
                new_lines = [f"   \x1b[2m⎿\x1b[0m {l[:75]}" for l in full_lines[:5]]
                if len(full_lines) > 5:
                    new_lines.append(f"   \x1b[2m… +{len(full_lines) - 5} lines (ctrl+o to expand)\x1b[0m")
            self._transcript.replace_range(start_idx, old_count, new_lines)
            new_count = len(new_lines)
            delta = new_count - old_count
            block["display_count"] = new_count
            # Shift all subsequent blocks' start_idx by the delta
            if delta != 0:
                for j in range(i + 1, len(self._tool_output_blocks)):
                    self._tool_output_blocks[j]["start_idx"] += delta
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
