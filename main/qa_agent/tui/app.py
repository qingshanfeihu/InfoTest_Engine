"""IstApp v3 — 单栏 TUI 主壳。

核心交互模型：
- 单栏顺序流（无 sidebar，无 progress trail）
- 屏底输入框（``> ``） + 2 行 footer（spinner+tokens / keybinding 提示）
- Slash 命令：``/help`` ``/clear`` ``/threads`` ``/resume`` ``/continue`` ``/model``
  ``/cost`` ``/compact`` ``/plan`` ``/init`` ``/version`` ``/exit``（12 个内置）
- 输入 ``/`` 触发 footer 补全 pill；Tab 填入；Enter 执行
- Ctrl+C：第一次 abort 当前 query；第二次（无活动 query）退出
- Esc：上下文敏感（清空输入 / abort 流式 / abort 工具）
- LLM token 流式期 Markdown 实时渲染（无前缀图标）
- 工具调用单行 ``⏺ Name args``，结果独立块缩进 2 空格、50 行截断
- 完成 ``⏱ duration · tokens`` 行紧跟 AI 消息

业务层完全复用：messages.py / sink.py / bridge.py / cli.py / state.py。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from main.qa_agent.tui.bridge import GraphBridge
from main.qa_agent.tui.checkpoint_repo import CheckpointRepo
from main.qa_agent.tui.input_history import InputHistory
from main.qa_agent.tui.messages import (
    AIFinalMessage,
    ErrorMessage,
    HilDecisionMessage,
    HilRequestMessage,
    HumanInputMessage,
    InfoMessage,
    IstMessage,
    ToolCallMessage,
)
from main.qa_agent.tui.sink import IstUiEvent
from main.qa_agent.tui.slash_commands import (
    ClearResult,
    ErrorResult,
    ExitResult,
    InfoResult,
    InjectResult,
    InterceptResult,
    TextResult,
    dispatch_slash_command,
    parse_slash_command,
)
from main.qa_agent.tui.state import TuiState
from main.qa_agent.tui.widgets.footer_pane import FooterPane
from main.qa_agent.tui.widgets.inline_message import (
    CompletionLine,
    InlineMessage,
    ToolOutputBlock,
)
from main.qa_agent.tui.widgets.prompt_input import PromptInput
from main.qa_agent.tui.widgets.slash_completion import SlashCompletion
from main.qa_agent.tui.widgets.streaming_markdown import StreamingMarkdown


logger = logging.getLogger(__name__)


def _user_facing_norm(name: str) -> str:
    """Map raw tool name to user-facing display name (matches inline_renderer)."""
    mapping = {
        "qa_deepagent_read_file": "ReadFile",
        "qa_deepagent_grep": "Grep",
        "qa_deepagent_ls": "Ls",
        "qa_deepagent_glob": "Ls",
        "python_exec": "Python",
        "bash_exec": "Bash",
        "qa_platform_run_task": "PlatformTask",
    }
    return mapping.get(name, name)


# ---------------------------------------------------------------------------
# Cross-thread message envelope
# ---------------------------------------------------------------------------


class IstUiEventMessage(Message):
    """Bridge 后台线程通过 ``app.call_from_thread(post, ev)`` 投递。"""

    def __init__(self, event: IstUiEvent) -> None:
        super().__init__()
        self.event = event


# ---------------------------------------------------------------------------
# IstApp
# ---------------------------------------------------------------------------


class IstApp(App):
    """IST-Core 终端 UI v3 — 单栏风格。"""

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        # Global
        Binding("ctrl+c", "ctrl_c", "Abort/Exit", show=False),
        Binding("ctrl+d", "exit_now", "Exit", show=False),
        Binding("ctrl+l", "redraw", "Redraw screen", show=False),
        Binding("ctrl+o", "toggle_transcript", "Expand/collapse output", show=False),
        Binding("ctrl+r", "history_search", "Search history", show=False),
        # Chat
        Binding("ctrl+j", "newline_in_input", "Newline", show=False),
        Binding("shift+enter", "newline_in_input", "Newline", show=False),
        Binding("shift+tab", "cycle_mode", "Cycle plan/normal mode", show=False),
        Binding("ctrl+g", "external_editor", "Open in $EDITOR", show=False),
        Binding("escape", "esc", "Cancel/Clear", show=False),
        Binding("tab", "tab_complete", "Complete", show=False),
        Binding("up", "history_up", "Older", show=False),
        Binding("down", "history_down", "Newer", show=False),
    ]

    #: U+21B5 ↵ — 输入框里多行的 visual placeholder；提交时还原为 \n
    NEWLINE_GLYPH = "↵"

    def __init__(
        self,
        *,
        thread_id: str | None = None,
        initial_query: str | None = None,
        task_type: str = "QA",
    ) -> None:
        super().__init__()
        self.tui_state = TuiState(
            thread_id=thread_id or f"run-{uuid.uuid4().hex[:8]}",
            tokens_budget=int(os.environ.get("QA_AGENT_TOKEN_BUDGET", "128000")),
        )
        self._initial_query = initial_query
        self._task_type = task_type
        self._bridge: GraphBridge | None = None
        self._checkpoint_repo = CheckpointRepo()
        self._history = InputHistory()

        # Widget refs
        self._scroll: VerticalScroll | None = None
        self._input: Input | None = None
        self._completion: SlashCompletion | None = None
        self._footer: FooterPane | None = None

        # Streaming state
        self._streaming_widget: StreamingMarkdown | None = None
        self._streaming_started_at: float = 0.0
        self._streaming_tokens: int = 0
        self._tool_widgets: dict[str, InlineMessage] = {}  # by run_id+seq

        # HIL state
        self._pending_hil: HilRequestMessage | None = None

        # Mode flags
        self._plan_mode_armed = False  # /plan toggled, applies to next user input

        # Ctrl+C 双击退出 + abort 状态
        self._last_ctrl_c_at: float = 0.0
        self._CTRL_C_DOUBLE_WINDOW_S = 1.5

    # -- Lifecycle -----------------------------------------------------------

    def compose(self) -> ComposeResult:
        # 模仿 FullscreenLayout 布局：
        #   ScrollBox(flex-grow=1, stickyScroll) 占满 +
        #   bottom slot(flex-shrink=0) 固定在底部包 PromptInput / completion / footer
        # Textual 等价：Vertical 容器 = transcript(1fr) + bottom(auto)
        with Vertical(id="root"):
            self._scroll = VerticalScroll(id="transcript")
            self._scroll.can_focus = False  # 不抢焦点，键盘永远落在 PromptInput
            yield self._scroll
            with Vertical(id="bottom-slot"):
                # 真实视觉（用户截图确认）：裸 ``> `` + 反白光标，
                # **没有上下分隔线** —— 删除曾经的 prompt-divider-top/bottom
                self._input = PromptInput(placeholder="输入消息（/ 触发补全）", id="prompt")
                yield self._input
                self._completion = SlashCompletion()
                self._completion.id = "slash-completion"
                yield self._completion
                self._footer = FooterPane()
                self._footer.id = "footer"
                self._footer.tokens_budget = self.tui_state.tokens_budget
                yield self._footer

    def on_mount(self) -> None:
        # 焦点必须落到输入框；其他 widget 都 can_focus=False
        if self._input is not None:
            self.set_focus(self._input)
            # 第二次保险——某些情况下 mount 后 widget tree 重排会丢焦点
            self.call_after_refresh(self._input.focus)
        # 启动屏欢迎 box（简化版）
        self._mount_welcome()
        if self._initial_query:
            self.call_after_refresh(self._submit_user_input, self._initial_query)

    def _mount_welcome(self) -> None:
        """启动时挂一条 WelcomeMessage 到 transcript 顶部；首次提交后由
        ``_submit_user_input`` 移除。"""
        if self._scroll is None:
            return
        from main.qa_agent.tui.messages import WelcomeMessage

        cwd = os.getcwd()
        # 把 home 简写为 ~
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        model = os.environ.get("QA_AGENT_MODEL") or "qwen-plus"
        welcome = WelcomeMessage(
            run_id=self.tui_state.thread_id,
            cwd=cwd,
            model=model,
            tips=[
                "试试 `infotest --help` 看完整 CLI 用法",
                "输入 `/` 触发 slash 命令补全",
                "`Ctrl+O` 展开 / 收起所有工具结果",
                "`Ctrl+G` 用 $EDITOR 编辑长 prompt",
                "`Shift+Tab` 切换 plan / normal 模式",
            ],
        )
        widget = InlineMessage(welcome)
        self._welcome_widget = widget
        self._scroll.mount(widget)

    # -- Cross-thread event delivery ----------------------------------------

    def dispatch_ui_event(self, event: IstUiEvent) -> None:
        """供 TuiSink 调用（跨线程）。"""
        try:
            self.call_from_thread(self.post_message, IstUiEventMessage(event))
        except Exception:
            logger.debug("dispatch_ui_event after teardown — dropping")

    def on_ist_ui_event_message(self, event: IstUiEventMessage) -> None:
        ev = event.event
        kind = ev.kind

        if kind == "append" and ev.message is not None:
            self._append_message(ev.message)
            return

        if kind == "update_ai_token":
            chunk = (ev.extra or {}).get("chunk") or ""
            self._on_ai_token(chunk)
            return

        if kind == "finalize_ai":
            self._on_ai_finalize(ev.extra or {})
            return

        if kind == "tool_done":
            extra = ev.extra or {}
            self._on_tool_done(
                run_id=str(extra.get("run_id") or ""),
                tool_name=str(extra.get("tool_name") or ""),
                result=str(extra.get("result") or ""),
            )
            return

        if kind in {"node_start", "node_end"}:
            node = (ev.extra or {}).get("node") or ""
            if node:
                self.tui_state.phase = node
            return

        if kind == "run_start":
            run_id = (ev.extra or {}).get("run_id") or ""
            self.tui_state.reset_run(run_id=run_id)
            self._streaming_started_at = time.time()
            self._streaming_tokens = 0
            if self._footer is not None:
                self._footer.is_busy = True
            return

        if kind in {"run_end", "run_done"}:
            self.tui_state.phase = "done"
            if self._footer is not None:
                self._footer.is_busy = False
            # /model 临时 env 还原（如果上一轮被改过）
            self._restore_qa_model_env()
            return

        if kind == "run_error":
            err = (ev.extra or {}).get("error") or "unknown error"
            self._append_message(ErrorMessage(text=str(err)))
            if self._footer is not None:
                self._footer.is_busy = False
            self._restore_qa_model_env()
            return

        if kind == "hil_request":
            if isinstance(ev.message, HilRequestMessage):
                self._append_message(ev.message)
                self._pending_hil = ev.message
            return

        if kind in {"subagent_start", "subagent_end"}:
            if ev.message is not None:
                self._append_message(ev.message)
            return

    # -- Streaming + tool routing -------------------------------------------

    def _append_message(self, msg: IstMessage) -> None:
        if self._scroll is None:
            return
        # AI 流式 token 走专门的 StreamingMarkdown widget
        from main.qa_agent.tui.messages import (
            AIThinkingMessage as _AIThinking,
            ToolCallMessage as _Tool,
            FileReadMessage as _FR,
            XlsxSheetMessage as _XLSX,
            GrepHitsMessage as _GH,
            LsTreeMessage as _LS,
            PythonExecMessage as _PE,
            BashExecMessage as _BE,
            PlatformTaskMessage as _PT,
            SubAgentDispatchMessage as _SA,
        )

        if isinstance(msg, _AIThinking):
            # 新建 streaming widget；llm_end 时 finalize
            self._streaming_widget = StreamingMarkdown()
            self._scroll.mount(self._streaming_widget)
            self._scroll.scroll_end(animate=False)
            return

        widget = InlineMessage(msg)
        self._scroll.mount(widget)
        self._scroll.scroll_end(animate=False)
        # Tool messages: 记录 inflight，等 tool_done 时挂 ToolOutputBlock
        if isinstance(msg, (_Tool, _FR, _XLSX, _GH, _LS, _PE, _BE, _PT, _SA)):
            self._tool_widgets[f"{msg.run_id}:{msg.seq}"] = widget

    def _on_ai_token(self, chunk: str) -> None:
        if self._streaming_widget is None or self._scroll is None:
            return
        self._streaming_widget.append_chunk(chunk)
        self._scroll.scroll_end(animate=False)

    def _on_ai_finalize(self, extra: dict[str, Any]) -> None:
        # Usage 累计独立于 streaming widget——每次 LLM 调用都要更新 token 计数
        # （实时显示 footer token；不 mount 单独的完成行）
        usage = extra.get("usage") or {}
        total = int(
            usage.get("total_tokens")
            or (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
            or 0
        )
        if total > 0:
            self.tui_state.tokens_used += total
            self.tui_state.llm_calls += 1
            if self._footer is not None:
                self._footer.tokens_used = self.tui_state.tokens_used

        # Streaming widget 完成（仅在真正流式 widget 存在时——目前 sync 调用没有，
        # streaming widget 这条路是为未来 astream 流式 token 留的）
        if self._streaming_widget is None or self._scroll is None:
            return
        self._streaming_widget.finalize()
        self._streaming_widget = None

    def _on_tool_done(self, *, run_id: str, tool_name: str, result: str) -> None:
        if self._scroll is None:
            return
        is_error = result.lower().startswith(("error", "✗"))
        # 找匹配的 tool widget 切到 done/error
        target_key = None
        for key, w in self._tool_widgets.items():
            if not key.startswith(f"{run_id}:"):
                continue
            tool_msg = getattr(w.message, "tool_name", None) or self._user_facing_for(w.message)
            if tool_msg in {tool_name, _user_facing_norm(tool_name)} or tool_msg.lower() == tool_name.lower():
                target_key = key
                break
        if target_key is None:
            # fallback：最后一个 inflight
            keys = list(self._tool_widgets.keys())
            target_key = keys[-1] if keys else None
        if target_key:
            widget = self._tool_widgets.pop(target_key)
            widget.update_status("error" if is_error else "done")
        # Mount 输出块（独立消息，缩进 2 空格 + 50 行截断）
        if result.strip():
            self._scroll.mount(ToolOutputBlock(result))
            self._scroll.scroll_end(animate=False)
        self.tui_state.tool_calls += 1

    @staticmethod
    def _user_facing_for(msg: IstMessage) -> str:
        from main.qa_agent.tui.inline_renderer import _user_facing_tool_name
        return _user_facing_tool_name(msg)

    # -- Input handling ------------------------------------------------------

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        text = (event.value or "").strip()
        if not text:
            return
        # 还原 ↵ visual placeholder 为真实 \n（Shift+Enter 多行）
        text = text.replace(self.NEWLINE_GLYPH, "\n")
        if self._completion is not None:
            self._completion.update_for_input("")
        self._submit_user_input(text)

    def on_prompt_input_changed(self, event: PromptInput.Changed) -> None:
        # Slash 补全条实时更新
        if self._completion is not None:
            self._completion.update_for_input(event.value or "")

    def _submit_user_input(self, text: str) -> None:
        # 历史栈 + 重置 navigation
        self._history.add(text)
        # 首次提交时移除 WelcomeMessage（用户开始用了就把欢迎屏推开）
        welcome = getattr(self, "_welcome_widget", None)
        if welcome is not None:
            try:
                welcome.remove()
            except Exception:
                pass
            self._welcome_widget = None
        # 立即把用户输入回显到流里
        self._append_message(HumanInputMessage(
            text=text, run_id=self.tui_state.thread_id,
        ))

        # Slash 命令路由
        parsed = parse_slash_command(text)
        if parsed is not None:
            self._handle_slash(parsed)
            return

        # HIL 决策（用 /approve /edit /reject 已经在 _handle_slash；非 slash 直接提示）
        if self._pending_hil is not None:
            self._append_message(InfoMessage(
                text="(pending HIL — use /approve /edit /reject to decide)"
            ))
            return

        # 普通 query → 走 LLM
        self._submit_to_bridge(text)

    def _submit_to_bridge(self, text: str) -> None:
        # /plan armed → 在 prompt 前加 plan 模式 hint
        prompt_text = text
        if self._plan_mode_armed:
            prompt_text = (
                "[plan-only mode] 只设计方案不实施任何修改，"
                "用户的实际请求：\n" + text
            )
            self._plan_mode_armed = False

        # /model 接通：临时把 override_model 写进 env，bridge 跑完后还原
        override = self.tui_state.__dict__.get("override_model")
        prev_env = os.environ.get("QA_AGENT_MODEL")
        if override:
            os.environ["QA_AGENT_MODEL"] = override
            self._restore_qa_model_env_after_run = prev_env
        else:
            self._restore_qa_model_env_after_run = None

        if self._bridge is None:
            self._bridge = GraphBridge(
                graph_factory=lambda: self._build_graph(),
                post=self.dispatch_ui_event,
                thread_id=self.tui_state.thread_id,
            )

        if self._bridge.is_running:
            self._append_message(InfoMessage(
                text="(busy — finish current turn or Ctrl+C to abort)"
            ))
            return

        initial_state = {
            "task_type": self._task_type,
            "user_input": prompt_text,
            "messages": [],
        }
        self._bridge.start(initial_state)

    @staticmethod
    def _build_graph():
        from main.qa_agent.graph import build_qa_agent_graph
        return build_qa_agent_graph(checkpointer=True)

    def _restore_qa_model_env(self) -> None:
        """run_end / run_error 后还原 ``QA_AGENT_MODEL`` env（如果 /model 临时改过）。"""
        prev = getattr(self, "_restore_qa_model_env_after_run", None)
        if prev is None and "QA_AGENT_MODEL" in os.environ:
            # 之前没设 → 删除
            os.environ.pop("QA_AGENT_MODEL", None)
        elif prev is not None:
            os.environ["QA_AGENT_MODEL"] = prev
        self._restore_qa_model_env_after_run = None

    # -- Slash command dispatch --------------------------------------------

    def _handle_slash(self, parsed) -> None:
        # Special-case: HIL decisions
        if self._pending_hil is not None and parsed.command_name in {"approve", "edit", "reject"}:
            self._handle_hil_decision(parsed)
            return

        result = dispatch_slash_command(parsed, self)

        if isinstance(result, ClearResult):
            if self._scroll is not None:
                self._scroll.remove_children()
            return
        if isinstance(result, ExitResult):
            self.exit()
            return
        if isinstance(result, InfoResult):
            self._append_message(InfoMessage(text=result.text))
            return
        if isinstance(result, TextResult):
            # 多行文本块 — 用 Static 直接显示（不走 IstMessage 包装）
            if self._scroll is not None:
                self._scroll.mount(Static(result.text))
                self._scroll.scroll_end(animate=False)
            return
        if isinstance(result, ErrorResult):
            self._append_message(ErrorMessage(text=result.text))
            return
        if isinstance(result, InterceptResult):
            self._plan_mode_armed = (result.mode == "plan")
            self._append_message(InfoMessage(
                text=f"(mode armed: {result.mode}; next user message will be {result.mode}-only)"
            ))
            return
        if isinstance(result, InjectResult):
            self._submit_to_bridge(result.prompt)
            return

    # -- HIL decisions via slash -------------------------------------------

    def _handle_hil_decision(self, parsed) -> None:
        if self._pending_hil is None:
            self._append_message(InfoMessage(text="(no pending HIL request)"))
            return

        if parsed.command_name == "approve":
            decision = {"approved": True}
        elif parsed.command_name == "reject":
            decision = {"approved": False}
        elif parsed.command_name == "edit":
            override = parsed.args.strip() or self._pending_hil.draft_answer
            decision = {"override_answer": override}
        else:
            return

        self._append_message(HilDecisionMessage(
            run_id=self.tui_state.thread_id, decision=decision,
        ))
        self._pending_hil = None
        if self._bridge is not None:
            try:
                self._bridge.resume_with(decision)
            except Exception as exc:  # noqa: BLE001
                self._append_message(ErrorMessage(text=f"resume failed: {exc}"))

    # -- Thread switch ------------------------------------------------------

    def _on_thread_selected(self, tid: str) -> None:
        if not tid or tid == self.tui_state.thread_id:
            return
        if self._bridge is not None and self._bridge.is_running:
            self._append_message(InfoMessage(
                text="(busy — finish current turn before switching threads)"
            ))
            return
        self.tui_state.thread_id = tid
        # 清空当前 transcript + 试图回灌历史
        if self._scroll is not None:
            self._scroll.remove_children()
        state = self._checkpoint_repo.get_thread(tid)
        if state:
            preview = state.get("final_answer") or state.get("user_input") or ""
            self._append_message(InfoMessage(
                text=f"(restored thread {tid}) {str(preview)[:200]}"
            ))
        self._bridge = None  # 重新构造（thread_id 已变）

    # -- Actions / keybindings ----------------------------------------------

    def action_ctrl_c(self) -> None:
        """Ctrl+C: 第一次 abort，第二次（短时间内）退出。"""
        now = time.time()
        if self._bridge is not None and self._bridge.is_running:
            # 有活动 query → abort
            self._append_message(InfoMessage(text="[Request interrupted by user]"))
            try:
                # GraphBridge 没有 abort()，只能让 worker 自然退出；MVP 先做提示
                pass
            except Exception:
                pass
            self._last_ctrl_c_at = now
            return
        # 无活动 query：双击窗口内 → 退出；否则提示
        if now - self._last_ctrl_c_at <= self._CTRL_C_DOUBLE_WINDOW_S:
            self.exit()
            return
        self._last_ctrl_c_at = now
        self._append_message(InfoMessage(text="(Ctrl+C again to exit)"))

    def action_exit_now(self) -> None:
        """Ctrl+D：直接退出。"""
        self.exit()

    def action_toggle_transcript(self) -> None:
        """Ctrl+O：全局切换 transcript expand 状态。

        所有 ToolOutputBlock 切换 expand/collapse 模式：
        - collapsed: 5 行 + ``… +N lines (ctrl+o to expand)``
        - expanded:  完整 stdout/stderr，无截断

        同时切换 ThinkingMessage 折叠/展开。
        """
        from main.qa_agent.tui.widgets.inline_message import InlineMessage, ToolOutputBlock
        from main.qa_agent.tui.inline_renderer import render, set_thinking_expanded
        from main.qa_agent.tui.messages import ThinkingMessage

        self._transcript_expanded = not getattr(self, "_transcript_expanded", False)
        # 1. 工具输出块
        if self._scroll is not None:
            for block in self._scroll.query(ToolOutputBlock):
                block.set_expanded(self._transcript_expanded)
        # 2. Thinking blocks（全局标志 + 重新 render 已挂载的 ThinkingMessage widgets）
        set_thinking_expanded(self._transcript_expanded)
        if self._scroll is not None:
            for inline in self._scroll.query(InlineMessage):
                if isinstance(inline.message, ThinkingMessage):
                    inline.update(render(inline.message))

    def action_redraw(self) -> None:
        """Ctrl+L：清屏重绘。

        Textual 没有"清滚动条"概念；这里调 ``self.refresh(repaint=True)`` 强制重绘整屏。
        """
        self.refresh(repaint=True)

    def action_cycle_mode(self) -> None:
        """Shift+Tab：切换 plan / normal 模式。

        简化实现：只在 normal ↔ plan 之间切。
        状态显示在 footer hint 行。
        """
        self._plan_mode_armed = not self._plan_mode_armed
        mode = "plan" if self._plan_mode_armed else "normal"
        if self._footer is not None:
            if self._plan_mode_armed:
                self._footer.update_hint(f"plan mode armed · esc to interrupt")
            else:
                self._footer.update_hint()  # 默认 esc to interrupt
        self._append_message(InfoMessage(text=f"(mode: {mode})"))

    def action_external_editor(self) -> None:
        """Ctrl+G / Ctrl+X Ctrl+E：在 $EDITOR 里编辑当前输入框内容。

        suspend TUI → 启动 $EDITOR 编辑临时文件
        → 用户保存退出后回到 TUI，输入框填入编辑后的文本。
        """
        import os
        import subprocess
        import tempfile

        if self._input is None:
            return
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
        initial_text = self._input.value.replace(self._input.NEWLINE_GLYPH, "\n")
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8",
            ) as f:
                f.write(initial_text)
                tmp_path = f.name
            with self.suspend():  # Textual 0.89+ 支持 suspend / resume
                subprocess.call([editor, tmp_path])
            with open(tmp_path, encoding="utf-8") as f:
                edited = f.read().rstrip()
            os.unlink(tmp_path)
            # 多行文本：还原 \n 为 ↵ visual placeholder
            visual = edited.replace("\n", self._input.NEWLINE_GLYPH)
            self._input.set_value(visual)
        except Exception as exc:  # noqa: BLE001
            self._append_message(ErrorMessage(text=f"external editor failed: {exc}"))

    def action_esc(self) -> None:
        """Esc 上下文敏感。"""
        # 搜索模式下 Esc → 退出搜索，恢复 draft + footer hint
        if self._history.in_search_mode:
            restored = self._history.exit_search(restore=True)
            if self._input is not None:
                self._input.set_value(restored)
            if self._footer is not None:
                self._footer.update_hint()  # 默认提示
            return
        # 输入框有内容 → 清空 + 重置历史 cursor
        if self._input is not None and self._input.value:
            self._input.clear()
            self._history.reset_navigation()
            if self._completion is not None:
                self._completion.update_for_input("")
            return
        # 流式中 → 提示 abort（同 Ctrl+C）
        if self._bridge is not None and self._bridge.is_running:
            self._append_message(InfoMessage(text="[Request interrupted by user]"))

    def action_tab_complete(self) -> None:
        """Tab：把 SlashCompletion 第一个候选填入输入框。"""
        if self._input is None or self._completion is None:
            return
        first = self._completion.first_completion()
        if first:
            # 保留命令名 + 一个空格供 args 输入
            self._input.set_value(first + " ")

    # -- Newline in input (Shift+Enter / Ctrl+J) --

    def action_newline_in_input(self) -> None:
        """Shift+Enter 在 cursor 处插入换行 visual placeholder ↵；提交时还原 \\n。"""
        if self._input is None:
            return
        self._input.insert(self.NEWLINE_GLYPH)

    # -- History navigation --

    def action_history_up(self) -> None:
        """↑：翻 older history。第一次按时记录当前输入为 draft。"""
        if self._input is None:
            return
        out = self._history.up(self._input.value)
        if out is not None:
            self._input.set_value(out)
            # 翻历史时不触发 slash 补全（它会刷出来覆盖）
            if self._completion is not None:
                self._completion.update_for_input(out)

    def action_history_down(self) -> None:
        """↓：翻 newer history；超出 → 恢复 draft。"""
        if self._input is None:
            return
        out = self._history.down(self._input.value)
        if out is None:
            return
        self._input.set_value(out)
        if self._completion is not None:
            self._completion.update_for_input(out)

    def action_history_search(self) -> None:
        """Ctrl+R：进入搜索模式 / 跳下一个匹配。"""
        if self._input is None or self._footer is None:
            return
        if not self._history.in_search_mode:
            # 进入搜索模式
            match = self._history.start_search(self._input.value)
            self._footer.update_hint(
                f"(reverse-i-search)`{self._history.search_query}': "
                f"{(match or '<no match>')[:60]}"
            )
            if match is not None:
                self._input.set_value(match)
        else:
            # 已在搜索模式 → 跳下一个匹配
            match = self._history.search_next()
            self._footer.update_hint(
                f"(reverse-i-search)`{self._history.search_query}': "
                f"{(match or '<no match>')[:60]}"
            )
            if match is not None:
                self._input.set_value(match)
