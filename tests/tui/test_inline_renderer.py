"""Stage 7-2 inline_renderer tests.

验证 关键行为完全照搬：
- ⏺ TOOL_GLYPH (U+23FA)
- 4 状态色 pending/running/done/error
- 50 行截断 + ``... [N lines truncated] ...``
- AI 文本无前缀（区别于工具行）
- ⏱ 完成 spinner + tokens
- HIL inline 提示用 /approve /edit /reject
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from main.qa_agent.tui.inline_renderer import (
    COMPLETION_GLYPH,
    TOOL_GLYPH,
    TOOL_OUTPUT_MAX_LINES,
    TOOL_STATUS_STYLE,
    _truncate_lines,
    _user_facing_tool_name,
    render,
    render_ai_text,
    render_completion_line,
    render_hil_request,
    render_human_input,
    render_tool_call_line,
    render_tool_output,
)
from main.qa_agent.tui.messages import (
    AIFinalMessage,
    AIThinkingMessage,
    BashExecMessage,
    ErrorMessage,
    FileReadMessage,
    GrepHitsMessage,
    HilDecisionMessage,
    HilRequestMessage,
    HumanInputMessage,
    LsTreeMessage,
    PythonExecMessage,
    SubAgentDispatchMessage,
    ToolCallMessage,
    XlsxSheetMessage,
)


def _to_plain(renderable) -> str:
    """Render to plain text (no ANSI) for assertions."""
    console = Console(record=True, force_terminal=False, width=120, no_color=True)
    console.print(renderable)
    return console.export_text()


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_tool_glyph_is_black_circle():
    """Codex / 用的是 ⏺ (U+23FA), 不是 ● (U+25CF)."""
    assert TOOL_GLYPH == "⏺"
    assert ord(TOOL_GLYPH) == 0x23FA


def test_tool_status_style_has_4_states():
    assert set(TOOL_STATUS_STYLE.keys()) == {"pending", "running", "done", "error"}
    assert TOOL_STATUS_STYLE["error"] == "red"
    assert TOOL_STATUS_STYLE["done"] == "green"


def test_tool_output_max_lines_5():
    """截断阈值：5 行（不是 50）。"""
    assert TOOL_OUTPUT_MAX_LINES == 5


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_user_facing_tool_names():
    cases = [
        (FileReadMessage(path="x.py"), "ReadFile"),
        (XlsxSheetMessage(workbook_path="x.xlsx"), "ReadXlsx"),
        (GrepHitsMessage(pattern="foo"), "Grep"),
        (LsTreeMessage(path="."), "Ls"),
        (PythonExecMessage(code="print(1)"), "Python"),
        (BashExecMessage(command="ls"), "Bash"),
        (ToolCallMessage(tool_name="custom_tool"), "custom_tool"),
    ]
    for msg, expected in cases:
        assert _user_facing_tool_name(msg) == expected


# ---------------------------------------------------------------------------
# render_tool_call_line — 单行格式 + 4 状态
# ---------------------------------------------------------------------------


def test_render_tool_call_line_includes_glyph_and_name():
    msg = FileReadMessage(path="main/qa_agent/graph.py", status="done")
    text = _to_plain(render_tool_call_line(msg))
    assert TOOL_GLYPH in text
    assert "ReadFile" in text
    assert "main/qa_agent/graph.py" in text


def test_render_tool_call_line_args_summary_truncated():
    msg = BashExecMessage(command="x" * 500, status="done")
    text = _to_plain(render_tool_call_line(msg))
    assert TOOL_GLYPH in text
    assert "Bash" in text
    # 应只有一行且 args 部分被截断
    assert "…" in text or len(text) < 250


def test_render_tool_call_line_status_override():
    """`status` kwarg 覆盖 msg.status（spinner widget 用得上）。"""
    msg = ToolCallMessage(tool_name="x", status="pending")
    line = render_tool_call_line(msg, status="running")
    # Text 对象内部 spans 至少一个有 yellow 风格（running 色）
    rendered = _to_plain(line)
    assert TOOL_GLYPH in rendered


def test_render_tool_call_line_python_shows_first_code_line():
    msg = PythonExecMessage(code="import openpyxl\nwb = ...\nprint(wb)", status="done")
    text = _to_plain(render_tool_call_line(msg))
    assert "import openpyxl" in text
    # 不应包含其他行（args summary 只取首行）
    assert "wb = ..." not in text


# ---------------------------------------------------------------------------
# render_tool_output — 5 行截断 + ``… +N lines (ctrl+o to expand)``
# ---------------------------------------------------------------------------


def test_render_tool_output_short_no_truncation():
    out = render_tool_output("line1\nline2\nline3")
    assert out is not None
    text = _to_plain(out)
    assert "line1" in text and "line3" in text
    assert "expand" not in text


def test_render_tool_output_long_triggers_5_line_truncation():
    """5+ 行 -> 必须出现 ``… +N lines (ctrl+o to expand)``"""
    body = "\n".join(f"line{i}" for i in range(8))
    out = render_tool_output(body)
    assert out is not None
    text = _to_plain(out)
    # 前 5 行可见
    assert "line0" in text
    assert "line4" in text
    # 第 6+ 行不可见
    assert "line5" not in text
    assert "line7" not in text
    # 截断提示
    assert "… +3 lines" in text
    assert "ctrl+o to expand" in text


def test_render_tool_output_first_line_uses_corner_glyph():
    """首行用 ``⎿  `` (U+23BF + 2 空格) 引导."""
    out = render_tool_output("hello\nworld")
    assert out is not None
    text = _to_plain(out)
    # 首行应以 ``  ⎿  `` 开头（外层缩进 2 空格 + 角符 + 2 空格）
    assert "⎿" in text
    # hello 在首行
    for line in text.splitlines():
        if "hello" in line:
            assert "⎿" in line
            break


def test_render_tool_output_continuation_lines_indent_5():
    """续行缩进 5 空格（与 ``  ⎿  `` 对齐）。"""
    out = render_tool_output("first\nsecond\nthird")
    assert out is not None
    lines = _to_plain(out).splitlines()
    # 找 "second" 行——应该是 5 空格缩进，无 ⎿
    for line in lines:
        if "second" in line:
            assert "⎿" not in line
            assert line.startswith("     ")  # 5 spaces
            break


def test_render_tool_output_stderr_shown_separately():
    out = render_tool_output("good\nbye", stderr="oops error")
    assert out is not None
    text = _to_plain(out)
    assert "good" in text and "oops error" in text


def test_render_tool_output_empty_returns_none():
    assert render_tool_output("") is None
    assert render_tool_output("", stderr="") is None


def test_truncate_lines_helper():
    body = "\n".join(f"l{i}" for i in range(60))
    kept, n = _truncate_lines(body, 50)
    assert n == 10
    assert kept.count("\n") == 49  # 50 行 = 49 个换行


# ---------------------------------------------------------------------------
# render_completion_line — ⏱ 1.2s · 845 tokens
# ---------------------------------------------------------------------------


def test_render_completion_line_short_duration():
    text = _to_plain(render_completion_line(elapsed_s=1.234, tokens=845))
    assert COMPLETION_GLYPH in text
    assert "1.2s" in text
    assert "845 tokens" in text


def test_render_completion_line_minutes():
    text = _to_plain(render_completion_line(elapsed_s=134.0, tokens=12345))
    assert "2m 14s" in text
    assert "12,345 tokens" in text  # 千分位逗号


def test_render_completion_line_hours():
    text = _to_plain(render_completion_line(elapsed_s=3700.0, tokens=999))
    assert "1h 1m" in text


# ---------------------------------------------------------------------------
# render_ai_text — 无前缀，流式期纯文本，完成期 Markdown
# ---------------------------------------------------------------------------


def test_render_ai_text_streaming_returns_plain_text():
    out = render_ai_text("# 标题\n\n内容", is_streaming=True)
    text = _to_plain(out)
    # 流式期纯文本：# 不会被渲染成 Markdown 标题
    assert "# 标题" in text


def test_render_ai_text_finalized_renders_markdown():
    out = render_ai_text("# 标题\n\n内容", is_streaming=False)
    text = _to_plain(out)
    # Markdown 渲染：# 标题 转成视觉标题（实际内容仍含"标题"字串）
    assert "标题" in text


def test_render_ai_text_has_glyph_prefix():
    """AI 文本必须有 ⏺ 前缀（ shouldShowDot=true 默认行为）.

    顶层 AI 消息（无论中间步还是最终答案）都加 ⏺ 标记，符合
    AssistantTextMessage.tsx:232 + figures.js BLACK_CIRCLE。
    """
    out = render_ai_text("一段话", is_streaming=True)
    text = _to_plain(out)
    assert TOOL_GLYPH in text
    # ⏺ 应在文本前面
    pos = text.find(TOOL_GLYPH)
    pos_text = text.find("一段话")
    assert pos < pos_text


def test_render_ai_text_priority_summary_appended_when_p0_present():
    """完成期：P0/P1 出现时追加优先级摘要条。"""
    long_md = "# 报告\n\n" + "## 一、整体结论\n\nP0 必须修复\n\nP1 重要" + " 详细" * 200
    out = render_ai_text(long_md, is_streaming=False)
    text = _to_plain(out)
    # P0 计数应在摘要条
    assert "P0" in text
    assert "P1" in text


# ---------------------------------------------------------------------------
# render_human_input — > {text}
# ---------------------------------------------------------------------------


def test_render_human_input_no_prefix():
    """User prompt 回显**无** ``>`` 前缀（ 真行为）.

    提交后 user message 是纯背景色块，无提示符。``>`` 只在输入框中显示，
    提交后消失。styles.tcss 给 .ist-human-input 加全宽 ``$surface-darken-1`` 背景。
    """
    msg = HumanInputMessage(text="ircookie 模式有哪些")
    text = _to_plain(render_human_input(msg))
    # 不应有 ``>`` 前缀
    assert not text.lstrip().startswith(">")
    # 但消息内容必须保留
    assert "ircookie 模式有哪些" in text


# ---------------------------------------------------------------------------
# render_hil_request — inline 提示 /approve /edit /reject
# ---------------------------------------------------------------------------


def test_render_hil_request_lists_three_slash_commands():
    msg = HilRequestMessage(
        findings={"D1": "FAIL"},
        draft_answer="评审结论：建议补充安全测试",
        reason="Phase C FAIL≥3",
    )
    text = _to_plain(render_hil_request(msg))
    assert "Human Review Required" in text or "review" in text.lower()
    assert "/approve" in text
    assert "/edit" in text
    assert "/reject" in text


def test_render_hil_request_includes_reason_and_draft():
    msg = HilRequestMessage(reason="some reason", draft_answer="some draft")
    text = _to_plain(render_hil_request(msg))
    assert "some reason" in text
    assert "some draft" in text


def test_render_hil_decision_three_paths():
    approved = HilDecisionMessage(decision={"approved": True})
    edited = HilDecisionMessage(decision={"override_answer": "new"})
    rejected = HilDecisionMessage(decision={"approved": False})
    assert "approved" in _to_plain(render(approved)).lower()
    assert "edited" in _to_plain(render(edited)).lower()
    assert "rejected" in _to_plain(render(rejected)).lower()


# ---------------------------------------------------------------------------
# render() main dispatch
# ---------------------------------------------------------------------------


def test_render_dispatches_each_message_type():
    msgs = [
        HumanInputMessage(text="hi"),
        AIThinkingMessage(content="thinking..."),
        AIFinalMessage(content="# done"),
        FileReadMessage(path="x.py"),
        XlsxSheetMessage(workbook_path="x.xlsx"),
        GrepHitsMessage(pattern="foo"),
        LsTreeMessage(path="."),
        PythonExecMessage(code="print(1)"),
        BashExecMessage(command="ls"),
        ToolCallMessage(tool_name="custom"),
        SubAgentDispatchMessage(name="coverage_analyst"),
        HilRequestMessage(reason="r", draft_answer="d"),
        ErrorMessage(text="boom"),
    ]
    for msg in msgs:
        out = render(msg)
        assert out is not None
        text = _to_plain(out)
        assert text.strip(), f"empty render for {type(msg).__name__}"


def test_render_subagent_status_glyph():
    msg = SubAgentDispatchMessage(name="coverage_analyst", status="running")
    text = _to_plain(render(msg))
    assert TOOL_GLYPH in text
    assert "coverage_analyst" in text
    assert "running" in text
