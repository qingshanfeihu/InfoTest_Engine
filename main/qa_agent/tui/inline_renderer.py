"""Inline renderer — IstMessage -> Rich RenderableType (单行流风格)。

Design:
- 每条 IstMessage 渲染成一个 Rich Renderable
- 工具行单行 ``⏺ ToolName args_summary`` (4 状态色: pending/running/done/error)
- 工具输出独立块，缩进 2 空格，50 行截断
- AI 文本无前缀，直接 Markdown 渲染
- 完成行 ``⏱ 1.2s · 845 tokens`` 紧跟 AI 消息
"""

from __future__ import annotations

import re
from typing import Any

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text

from main.qa_agent.tui.markdown_section import (
    extract_priorities,
    priority_summary_line,
)
from main.qa_agent.tui.messages import (
    AIFinalMessage,
    AIThinkingMessage,
    BashExecMessage,
    ErrorMessage,
    EvidenceMessage,
    FileReadMessage,
    FindingMessage,
    GrepHitsMessage,
    HilDecisionMessage,
    HilRequestMessage,
    HumanInputMessage,
    InfoMessage,
    IstMessage,
    LsTreeMessage,
    PhaseMarkerMessage,
    PlatformTaskMessage,
    PythonExecMessage,
    SkillAssembledPromptMessage,
    SubAgentDispatchMessage,
    ToolCallMessage,
    ThinkingMessage,
    WarnMessage,
    WelcomeMessage,
    XlsxSheetMessage,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: 工具行前缀圆点
TOOL_GLYPH = "⏺"

#: 结果块引导符（U+23BF 圆角左下 + 2 空格）
TOOL_RESULT_GLYPH = "⎿"

#: 截断阈值：5 行
TOOL_OUTPUT_MAX_LINES = 5
TOOL_OUTPUT_TRUNCATE_TEMPLATE = "… +{n} lines (ctrl+o to expand)"

#: 完成行前缀
COMPLETION_GLYPH = "⏱"

#: 4 状态色
TOOL_STATUS_STYLE = {
    "pending": "grey50",
    "running": "yellow",
    "done": "green",
    "error": "red",
}


# ---------------------------------------------------------------------------
# User-facing tool name remapping
# ---------------------------------------------------------------------------


def _user_facing_tool_name(msg: IstMessage) -> str:
    """Map raw tool name -> display name."""
    if isinstance(msg, FileReadMessage):
        return "ReadFile"
    if isinstance(msg, XlsxSheetMessage):
        return "ReadXlsx"
    if isinstance(msg, GrepHitsMessage):
        return "Grep"
    if isinstance(msg, LsTreeMessage):
        return "Ls"
    if isinstance(msg, PythonExecMessage):
        return "Python"
    if isinstance(msg, BashExecMessage):
        return "Bash"
    if isinstance(msg, PlatformTaskMessage):
        return "PlatformTask"
    if isinstance(msg, SubAgentDispatchMessage):
        return f"SubAgent({msg.name})"
    if isinstance(msg, ToolCallMessage):
        return msg.tool_name or "Tool"
    return type(msg).__name__


def _args_summary(msg: IstMessage) -> str:
    """Single-line args summary, truncated. Mirrors renderedToolUseMessage."""
    if isinstance(msg, FileReadMessage):
        return msg.path or ""
    if isinstance(msg, XlsxSheetMessage):
        return msg.workbook_path or ""
    if isinstance(msg, GrepHitsMessage):
        return msg.pattern or ""
    if isinstance(msg, LsTreeMessage):
        return msg.path or "."
    if isinstance(msg, PythonExecMessage):
        first_line = (msg.code or "").splitlines()[0] if msg.code else ""
        return _truncate(first_line, 80)
    if isinstance(msg, BashExecMessage):
        return _truncate(msg.command or "", 80)
    if isinstance(msg, PlatformTaskMessage):
        task_type = (msg.task or {}).get("task_type") or ""
        perm = msg.permission_profile or ""
        dry = " [DRY-RUN]" if msg.dry_run else ""
        return f"{task_type} {perm}{dry}".strip()
    if isinstance(msg, SubAgentDispatchMessage):
        return ""
    if isinstance(msg, ToolCallMessage):
        # Pick first non-raw arg
        args = msg.args or {}
        for k, v in args.items():
            if k == "raw":
                continue
            return f"{k}={_truncate(str(v), 60)}"
        if "raw" in args:
            return _truncate(str(args["raw"]), 80)
    return ""


def _truncate(text: str, max_len: int) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Tool call line
# ---------------------------------------------------------------------------


def render_tool_call_line(msg: IstMessage, *, status: str | None = None) -> Text:
    """Single line: ``⏺ Bash(args…)``.

    。
    多行 args 续行缩进 6 空格（对齐 ``⏺ ToolName(``  之后）。

    `status` overrides msg.status if set.
    """
    s = status or _msg_status(msg)
    color = TOOL_STATUS_STYLE.get(s, "default")
    name = _user_facing_tool_name(msg)
    args = _args_summary(msg)

    line = Text()
    line.append(f"{TOOL_GLYPH} ", style=f"{color} bold")
    line.append(name, style="bold")
    if args:
        line.append("(", style="default")
        line.append(args, style="default")
        line.append(")", style="default")
    return line


def _msg_status(msg: IstMessage) -> str:
    """Best-effort status extraction. Falls back to ``pending``."""
    return getattr(msg, "status", None) or "pending"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def render_tool_output(
    stdout: str,
    *,
    stderr: str = "",
    max_lines: int = TOOL_OUTPUT_MAX_LINES,
) -> Text | None:
    """Indented output block. 视觉格式：

        ⎿  first line
           second line
           third line
           fourth line
           fifth line
           … +N lines (ctrl+o to expand)

    - 首行 ``⎿  `` (U+23BF + 2 空格 = 3 字符)
    - 续行缩进 3 空格（与 `⎿  ` 对齐）
    - 5 行截断 + ``… +N lines (ctrl+o to expand)``
    - stderr 独立 ``⎿`` 块
    """
    body_text = (stdout or "").rstrip()
    err_text = (stderr or "").rstrip()
    if not body_text and not err_text:
        return None

    out = Text()
    if body_text:
        truncated_body, n_truncated = _truncate_lines(body_text, max_lines)
        body_lines = truncated_body.splitlines()
        for i, line in enumerate(body_lines):
            if i == 0:
                out.append(f"  {TOOL_RESULT_GLYPH}  ", style="grey50")
                out.append(f"{line}\n", style="dim")
            else:
                out.append(f"     {line}\n", style="dim")
        if n_truncated > 0:
            out.append(
                f"     {TOOL_OUTPUT_TRUNCATE_TEMPLATE.format(n=n_truncated)}\n",
                style="grey50",
            )
    if err_text:
        err_lines = err_text.splitlines()
        for i, line in enumerate(err_lines):
            if i == 0:
                out.append(f"  {TOOL_RESULT_GLYPH}  ", style="grey50")
                out.append(f"{line}\n", style="red")
            else:
                out.append(f"     {line}\n", style="red")
    return out


def _truncate_lines(text: str, max_lines: int) -> tuple[str, int]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, 0
    kept = "\n".join(lines[:max_lines])
    n_truncated = len(lines) - max_lines
    return kept, n_truncated


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def render_completion_line(elapsed_s: float, tokens: int) -> Text:
    """``⏱ 2.3s · 1,245 tokens`` (gray, dim)."""
    duration = _format_duration(elapsed_s)
    txt = Text()
    txt.append(f"{COMPLETION_GLYPH} ", style="grey50")
    txt.append(duration, style="grey50")
    txt.append(" · ", style="grey50")
    txt.append(f"{tokens:,} tokens", style="grey50")
    return txt


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def render_ai_text(content: str, *, is_streaming: bool) -> RenderableType:
    """AI 文本渲染，前缀 ``⏺ ``（对齐  ``shouldShowDot={true}``）。

    顶层 AI 消息无论是中间步（带 tool_calls 的解释）还是最终答案，都显示 ``⏺``
    前缀（参考 AssistantTextMessage.tsx:232 + figures.js BLACK_CIRCLE）。
    """
    text = content or ""
    if is_streaming:
        # 流式期返回纯 Text + ⏺ 前缀
        return Text.assemble((f"{TOOL_GLYPH} ", "default bold"), text)
    # 完成后：⏺ 前缀 + Markdown（P0/P1/P2/P3 自动通过 Rich Markdown 渲染）
    prefix = Text(f"{TOOL_GLYPH} ", style="default bold")
    md = Markdown(text)
    counts = extract_priorities(text)
    summary = priority_summary_line(counts)
    if not summary:
        return Group(prefix, md)
    chip = Text()
    chip.append(summary, style="bold")
    return Group(prefix, md, chip)


# ---------------------------------------------------------------------------
# Misc message types
# ---------------------------------------------------------------------------


def render_human_input(msg: HumanInputMessage) -> Text:
    """User prompt 回显文本（无 ``>`` 前缀；背景色由 InlineMessage CSS 处理）.

     真实视觉：``Box backgroundColor='userMessageBackground'``
    无前缀 + 全宽背景。``>`` 提示符**只在输入框中显示**，提交后用户消息变成纯文本块。

    我们 InlineMessage widget 通过 ``msg.css_class == 'ist-human-input'`` 应用
    styles.tcss 里的 `background: $surface-darken-1` + `width: 1fr` 实现全宽背景。
    """
    return Text(msg.text, style="default")


def render_welcome(msg: WelcomeMessage) -> RenderableType:
    """启动屏欢迎 box（WelcomeV2.tsx 等价，简化版）.

    版本是复杂 ANSI 像素 logo（150+ 行 box-drawing），简化为：
    - 顶部 ``💖 Welcome to InfoTest Engine`` 标题（橙色 bold）
    - ``cwd: <path>`` + ``model: <name>`` 两行元信息
    - Tips for getting started 列表
    - 全部包在一个 panel 里（橙色圆角 border）
    """
    from rich.panel import Panel
    from rich.console import Group

    title = Text("💖 ", style="default") + Text(
        "Welcome to InfoTest Engine", style="bold"
    )
    meta_lines: list[Text] = []
    if msg.cwd:
        meta_lines.append(Text("  cwd:   ", style="dim") + Text(msg.cwd, style="default"))
    if msg.model:
        meta_lines.append(Text("  model: ", style="dim") + Text(msg.model, style="default"))

    tips_lines: list[Text] = []
    if msg.tips:
        tips_lines.append(Text("\nTips for getting started:", style="bold"))
        for i, tip in enumerate(msg.tips, 1):
            tips_lines.append(Text(f"  {i}. {tip}", style="default"))

    body = Group(title, *meta_lines, *tips_lines)
    return Panel(body, border_style="orange3", padding=(0, 1), expand=True)


def render_phase_marker(msg: PhaseMarkerMessage) -> Text:
    return Text(f"▶ phase: {msg.phase}", style="cyan")


def render_evidence(msg: EvidenceMessage) -> Text:
    summary = msg.payload.get("summary") if isinstance(msg.payload, dict) else ""
    if not summary and isinstance(msg.payload, dict):
        summary = ", ".join(list(msg.payload.keys())[:3])
    return Text(f"  ◇ evidence: {summary}", style="green")


def render_finding(msg: FindingMessage) -> Text:
    summary = msg.payload.get("summary") if isinstance(msg.payload, dict) else ""
    if not summary and isinstance(msg.payload, dict):
        summary = ", ".join(list(msg.payload.keys())[:3])
    return Text(f"  ✓ finding: {summary}", style="green bold")


def render_error(msg: ErrorMessage | WarnMessage | InfoMessage) -> Text:
    glyph_style = {
        "ist-error": ("✗", "red bold"),
        "ist-warn": ("⚠", "yellow"),
        "ist-info": ("·", "grey50"),
    }
    glyph, style = glyph_style.get(msg.css_class, ("·", "default"))
    return Text(f"{glyph} {msg.text}", style=style)


def render_hil_request(msg: HilRequestMessage) -> Group:
    """Inline HIL prompt: 3-line block + ``/approve`` ``/edit`` ``/reject`` hint."""
    parts: list[RenderableType] = []
    parts.append(Text("⚠ Human Review Required", style="yellow bold"))
    if msg.reason:
        parts.append(Text(f"  reason: {msg.reason}", style="grey50"))
    if msg.draft_answer:
        preview = msg.draft_answer[:200].replace("\n", " ")
        parts.append(Text(f"  draft: {preview}", style="default"))
    parts.append(
        Text("  type /approve, /edit, or /reject to decide", style="cyan italic")
    )
    return Group(*parts)


def render_hil_decision(msg: HilDecisionMessage) -> Text:
    decision = msg.decision or {}
    if decision.get("approved"):
        return Text("  ✓ HIL: approved", style="green")
    if "override_answer" in decision:
        return Text("  ✎ HIL: edited and submitted", style="cyan")
    return Text("  ✗ HIL: rejected", style="red")


def render_subagent_dispatch(msg: SubAgentDispatchMessage) -> Text:
    """Single-line subagent status: ``⏺ SubAgent(name) running ...``"""
    glyph_style = {
        "pending": "grey50",
        "running": "yellow",
        "done": "green",
        "error": "red",
    }
    style = glyph_style.get(msg.status, "default")
    line = Text()
    line.append(f"{TOOL_GLYPH} ", style=f"{style} bold")
    line.append(f"SubAgent({msg.name})", style="bold")
    line.append(f"  [{msg.status}]", style="dim")
    if msg.telemetry:
        # 紧凑 telemetry: tokens / tool_calls / elapsed
        bits = []
        for k in ("total_tokens", "tool_calls", "elapsed_ms"):
            if k in msg.telemetry:
                bits.append(f"{k}={msg.telemetry[k]}")
        if bits:
            line.append("  " + " ".join(bits), style="grey50")
    return line


def render_skill_prompt(msg: SkillAssembledPromptMessage) -> Text:
    fragments_count = len(msg.fragments)
    prompt_chars = len(msg.assembled_prompt or "")
    return Text(
        f"🧩 skill: {msg.skill_name}  fragments={fragments_count}  prompt={prompt_chars} chars",
        style="cyan dim",
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# 模块级标志：thinking 默认折叠；IstApp.action_toggle_transcript 切换
_THINKING_EXPANDED = False


def set_thinking_expanded(value: bool) -> None:
    """IstApp Ctrl+O 触发时调，切换 thinking 全局展开状态。"""
    global _THINKING_EXPANDED
    _THINKING_EXPANDED = value


def is_thinking_expanded() -> bool:
    return _THINKING_EXPANDED


def render_thinking(msg: ThinkingMessage) -> RenderableType:
    """LLM thinking block 渲染（）.

    - 折叠版（默认）：``∴ Thinking (ctrl+o to expand)`` 单行 dim italic
    - 展开版（Ctrl+O 触发）：``∴ Thinking…`` + dim markdown 缩进 2 空格
    """
    text = (msg.thinking or "").strip()
    if not text:
        return Text("∴ Thinking", style="dim italic")
    if not _THINKING_EXPANDED:
        return Text("∴ Thinking (ctrl+o to expand)", style="dim italic")
    # 展开版：标题 + 缩进 2 空格的 dim 内容
    title = Text("∴ Thinking…", style="dim italic")
    body_lines = []
    for line in text.splitlines():
        body_lines.append(Text("  " + line, style="dim"))
    return Group(title, *body_lines)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def render(msg: IstMessage) -> RenderableType:
    """Dispatch IstMessage -> RenderableType.

    Used by widgets/inline_message.py InlineMessage. Stream消息（AIThinkingMessage
    / 工具结果填充）由 widget 内部增量更新，不通过 render() 一次性渲染。
    """
    if isinstance(msg, HumanInputMessage):
        return render_human_input(msg)
    if isinstance(msg, WelcomeMessage):
        return render_welcome(msg)
    if isinstance(msg, ThinkingMessage):
        return render_thinking(msg)
    if isinstance(msg, AIFinalMessage):
        return render_ai_text(msg.content, is_streaming=False)
    if isinstance(msg, AIThinkingMessage):
        return render_ai_text(msg.content, is_streaming=True)

    # Specialized tool messages (must come before ToolCallMessage; they are not subclasses)
    if isinstance(msg, (
        FileReadMessage, XlsxSheetMessage, GrepHitsMessage, LsTreeMessage,
        PythonExecMessage, BashExecMessage, PlatformTaskMessage, ToolCallMessage,
    )):
        return render_tool_call_line(msg)

    if isinstance(msg, SubAgentDispatchMessage):
        return render_subagent_dispatch(msg)
    if isinstance(msg, SkillAssembledPromptMessage):
        return render_skill_prompt(msg)

    if isinstance(msg, HilRequestMessage):
        return render_hil_request(msg)
    if isinstance(msg, HilDecisionMessage):
        return render_hil_decision(msg)

    if isinstance(msg, PhaseMarkerMessage):
        return render_phase_marker(msg)
    if isinstance(msg, EvidenceMessage):
        return render_evidence(msg)
    if isinstance(msg, FindingMessage):
        return render_finding(msg)

    if isinstance(msg, (ErrorMessage, WarnMessage, InfoMessage)):
        return render_error(msg)

    # Fallback
    return Text(f"[{msg.css_class}] (no renderer)", style="dim")
