"""Stage 8 视觉/行为对账单测——覆盖 8 项 。

每个测试对应 plan v3 的 1 项 gap，都是纯逻辑/Pilot in-process 测试，不依赖
真终端或 LLM。
"""

from __future__ import annotations

import pytest
from rich.console import Console

from main.qa_agent.tui.app import IstApp
from main.qa_agent.tui.inline_renderer import (
    TOOL_GLYPH,
    TOOL_OUTPUT_MAX_LINES,
    render_tool_output,
)
from main.qa_agent.tui.messages import (
    BashExecMessage,
    FileReadMessage,
    GrepHitsMessage,
    HumanInputMessage,
    LsTreeMessage,
    PythonExecMessage,
    WelcomeMessage,
)
from main.qa_agent.tui.sink import (
    IstUiEvent,
    TuiSink,
    _parse_input_str_to_args,
)
from main.qa_agent.tui.widgets.footer_pane import (
    DEFAULT_HINT_LINE,
    SPINNER_GLYPH,
    SPINNER_VERBS,
)
from main.qa_agent.tui.widgets.inline_message import InlineMessage, ToolOutputBlock
from main.qa_agent.tui.widgets.prompt_input import PromptInput
from main.qa_agent.tui.widgets.slash_completion import SlashCompletion


def _to_plain(renderable) -> str:
    console = Console(record=True, force_terminal=False, width=120, no_color=True)
    console.print(renderable)
    return console.export_text()


# ---------------------------------------------------------------------------
# Gap #1: ReadFile / Grep args 解析
# ---------------------------------------------------------------------------


def test_parse_input_str_json():
    """LangChain 格式化的 input_str 通常是 JSON。"""
    args = _parse_input_str_to_args('{"path": "main/qa_agent/graph.py"}', "qa_deepagent_read_file")
    assert args == {"path": "main/qa_agent/graph.py"}


def test_parse_input_str_python_repr():
    """有时是 Python repr（单引号 dict）。"""
    args = _parse_input_str_to_args("{'pattern': 'tool_call'}", "qa_deepagent_grep")
    assert args == {"pattern": "tool_call"}


def test_parse_input_str_bare_string_to_primary():
    """单值裸字符串 -> 当主参数。"""
    args = _parse_input_str_to_args("main/qa_agent/graph.py", "qa_deepagent_read_file")
    assert args["path"] == "main/qa_agent/graph.py"


def test_parse_input_str_unknown_tool_falls_back_to_raw():
    """未注册的工具 fallback 到 {raw}。"""
    args = _parse_input_str_to_args("foo bar", "unknown_tool")
    assert args == {"raw": "foo bar"}


def test_sink_tool_call_with_input_str_parses_path():
    """sink._make_tool_message 收到 input_str + qa_deepagent_read_file -> FileReadMessage.path 填充。"""
    captured: list[IstUiEvent] = []
    sink = TuiSink(post=captured.append, token_throttle_ms=0)
    sink({
        "run_id": "r1", "seq": 1, "ts": "t",
        "kind": "tool_call",
        "tags": {"name": "qa_deepagent_read_file"},
        "payload": {"input": '{"path": "main/qa_agent/graph.py"}'},
    })
    appended = next(e for e in captured if e.kind == "append")
    assert isinstance(appended.message, FileReadMessage)
    assert appended.message.path == "main/qa_agent/graph.py"


def test_sink_tool_call_grep_pattern():
    captured: list[IstUiEvent] = []
    sink = TuiSink(post=captured.append, token_throttle_ms=0)
    sink({
        "run_id": "r1", "seq": 1, "ts": "t",
        "kind": "tool_call",
        "tags": {"name": "qa_deepagent_grep"},
        "payload": {"input": '{"pattern": "tool_call"}'},
    })
    appended = next(e for e in captured if e.kind == "append")
    assert isinstance(appended.message, GrepHitsMessage)
    assert appended.message.pattern == "tool_call"


def test_sink_python_exec_code():
    captured: list[IstUiEvent] = []
    sink = TuiSink(post=captured.append, token_throttle_ms=0)
    sink({
        "run_id": "r1", "seq": 1, "ts": "t",
        "kind": "tool_call",
        "tags": {"name": "python_exec"},
        "payload": {"input": "import openpyxl\nprint(1)"},
    })
    appended = next(e for e in captured if e.kind == "append")
    assert isinstance(appended.message, PythonExecMessage)
    assert "openpyxl" in appended.message.code


def test_sink_bash_exec_command():
    captured: list[IstUiEvent] = []
    sink = TuiSink(post=captured.append, token_throttle_ms=0)
    sink({
        "run_id": "r1", "seq": 1, "ts": "t",
        "kind": "tool_call",
        "tags": {"name": "bash_exec"},
        "payload": {"input": "ls -la"},
    })
    appended = next(e for e in captured if e.kind == "append")
    assert isinstance(appended.message, BashExecMessage)
    assert appended.message.command == "ls -la"


# ---------------------------------------------------------------------------
# Gap #2: LsTreeMessage path 不再用 "." 兜底
# ---------------------------------------------------------------------------


def test_lstree_default_path_empty():
    """LsTreeMessage 默认 path 应是空字符串（之前是 "."），允许 _args_summary 不显示。"""
    msg = LsTreeMessage()
    assert msg.path == ""


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def test_spinner_glyph_and_verbs_match_():
    """。"""
    assert SPINNER_GLYPH == "✶"
    assert "Considering" in SPINNER_VERBS
    assert "Synthesizing" in SPINNER_VERBS
    assert len(SPINNER_VERBS) >= 20


# ---------------------------------------------------------------------------
# Gap #5: Footer hint = "esc to interrupt"
# ---------------------------------------------------------------------------


def test_footer_hint_is_esc_to_interrupt():
    """Footer 提示行应是极简 ``esc to interrupt``（。"""
    assert DEFAULT_HINT_LINE == "esc to interrupt"


# ---------------------------------------------------------------------------
# Gap #4 + Gap #8: 输入框无横线 + 用户输入 css class
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_prompt_dividers():
    """启动后 widget tree 不应有 #prompt-divider-top / #prompt-divider-bottom。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        with pytest.raises(Exception):
            app.query_one("#prompt-divider-top")
        with pytest.raises(Exception):
            app.query_one("#prompt-divider-bottom")


@pytest.mark.asyncio
async def test_user_input_widget_has_human_css_class():
    """提交用户输入后 InlineMessage 应有 ``ist-human-input`` class。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "/version":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.1)
        # transcript 内应有一个 InlineMessage(HumanInputMessage)
        from textual.containers import VerticalScroll
        scroll = app.query_one("#transcript", VerticalScroll)
        found = False
        for child in scroll.walk_children():
            if isinstance(child, InlineMessage) and isinstance(child.message, HumanInputMessage):
                assert "ist-human-input" in child.classes
                found = True
                break
        assert found, "user input InlineMessage not found"


# ---------------------------------------------------------------------------
# Gap #6: Welcome box on startup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_welcome_message_mounted_on_startup():
    """启动后 transcript 应包含一条 WelcomeMessage。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        from textual.containers import VerticalScroll
        scroll = app.query_one("#transcript", VerticalScroll)
        welcome_found = False
        for child in scroll.walk_children():
            if isinstance(child, InlineMessage) and isinstance(child.message, WelcomeMessage):
                welcome_found = True
                break
        assert welcome_found, "WelcomeMessage not mounted on startup"


@pytest.mark.asyncio
async def test_welcome_removed_after_first_submit():
    """首次提交 query 后 WelcomeMessage 应被移除。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "/version":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.1)
        from textual.containers import VerticalScroll
        scroll = app.query_one("#transcript", VerticalScroll)
        for child in scroll.walk_children():
            if isinstance(child, InlineMessage) and isinstance(child.message, WelcomeMessage):
                pytest.fail("WelcomeMessage still in transcript after submit")


def test_welcome_renderable_includes_tips():
    msg = WelcomeMessage(cwd="~/proj", model="qwen-plus", tips=["tip-1", "tip-2"])
    from main.qa_agent.tui.inline_renderer import render_welcome
    text = _to_plain(render_welcome(msg))
    assert "Welcome to InfoTest Engine" in text
    assert "qwen-plus" in text
    assert "tip-1" in text
    assert "tip-2" in text


# ---------------------------------------------------------------------------
# Gap #7: Ctrl+O toggle transcript expand
# ---------------------------------------------------------------------------


def test_tool_output_block_default_collapsed():
    """新建 ToolOutputBlock 默认折叠（截断 5 行）。"""
    long_body = "\n".join(f"line{i}" for i in range(20))
    block = ToolOutputBlock(long_body)
    assert block._expanded is False


def test_tool_output_block_set_expanded_keeps_full():
    """set_expanded(True) 后内部 _expanded 切换。"""
    long_body = "\n".join(f"line{i}" for i in range(20))
    block = ToolOutputBlock(long_body)
    block.set_expanded(True)
    assert block._expanded is True
    block.set_expanded(False)
    assert block._expanded is False


@pytest.mark.asyncio
async def test_ctrl_o_toggles_transcript_expanded_flag():
    """Ctrl+O 切换 IstApp._transcript_expanded 标志。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert getattr(app, "_transcript_expanded", False) is False
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert app._transcript_expanded is True
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert app._transcript_expanded is False


# ---------------------------------------------------------------------------
# AI 文本 ⏺ 前缀 + thought 中间步
# ---------------------------------------------------------------------------


def test_ai_text_has_circle_prefix():
    from main.qa_agent.tui.inline_renderer import render_ai_text

    out = render_ai_text("hello", is_streaming=False)
    text = _to_plain(out)
    assert TOOL_GLYPH in text
    pos = text.find(TOOL_GLYPH)
    pos_text = text.find("hello")
    assert pos < pos_text


def test_sink_thought_event_appends_aifinal():
    """LLM thought（中间步带 tool_calls 的 LLM 输出）应 append 一条 AIFinalMessage."""
    captured: list[IstUiEvent] = []
    sink = TuiSink(post=captured.append, token_throttle_ms=0)
    sink({
        "run_id": "r1", "seq": 1, "ts": "t",
        "kind": "llm_end",
        "tags": {},
        "payload": {"name": "thought", "content": "我现在调用 Bash 工具读取..."},
    })
    appended = [e for e in captured if e.kind == "append"]
    assert len(appended) == 1
    from main.qa_agent.tui.messages import AIFinalMessage
    assert isinstance(appended[0].message, AIFinalMessage)
    assert "Bash" in appended[0].message.content


# ---------------------------------------------------------------------------
# Tool output 5 行截断 + ⎿ 引导符 + ctrl+o expand 文案
# ---------------------------------------------------------------------------


def test_tool_output_truncation_text_format():
    """5+ 行 -> ``… +N lines (ctrl+o to expand)`` 文案."""
    body = "\n".join(f"L{i}" for i in range(10))
    out = render_tool_output(body)
    text = _to_plain(out)
    assert "… +5 lines (ctrl+o to expand)" in text


def test_tool_output_uses_corner_glyph():
    body = "L1\nL2"
    out = render_tool_output(body)
    text = _to_plain(out)
    assert "⎿" in text  # U+23BF


# ---------------------------------------------------------------------------
# Bindings registered for Ctrl+L / Shift+Tab / Ctrl+G
# ---------------------------------------------------------------------------


def test_app_has_new_bindings():
    keys = [b.key for b in IstApp.BINDINGS]
    assert "ctrl+l" in keys
    assert "ctrl+o" in keys
    assert "shift+tab" in keys
    assert "ctrl+g" in keys
