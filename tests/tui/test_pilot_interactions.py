"""Stage 7-Fix Pilot e2e — Textual 自带的 in-process e2e 测试。

不用 pexpect/pyte（抓不到 alt-screen 内容）；用 Textual ``App.run_test()`` +
``Pilot`` 直接戳 widget 状态、模拟按键、读 reactive 字段。能精确验证：

- 输入字符回显（PromptInput.value 实时变化）
- Slash 补全候选条 visible class
- 历史 ↑↓ 跳转
- Ctrl+R 搜索模式
- Shift+Enter / Ctrl+J 多行 ↵
- /help 输出落到 transcript
- /exit 退出
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from textual.widgets import Static

from main.qa_agent.tui.app import IstApp
from main.qa_agent.tui.widgets.prompt_input import PromptInput
from main.qa_agent.tui.widgets.slash_completion import SlashCompletion


@pytest.fixture(autouse=True)
def isolate_history(tmp_path: Path, monkeypatch):
    """Each test gets its own history file so no cross-contamination."""
    monkeypatch.setenv("INFOTEST_HISTORY_PATH", str(tmp_path / "history"))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-fake-key")  # 防止 build_graph 因 env 缺失崩
    # Reload module to pick up env
    from main.qa_agent.tui import input_history
    import importlib
    importlib.reload(input_history)


# ---------------------------------------------------------------------------
# A. 输入字符回显
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_typing_updates_prompt_value():
    """敲 'hello'，PromptInput.value 应实时变成 'hello'。"""
    app = IstApp()
    async with app.run_test() as pilot:
        # 等首屏 mount
        await pilot.pause()
        prompt = app.query_one(PromptInput)
        # 模拟逐字按键
        await pilot.press("h", "e", "l", "l", "o")
        await pilot.pause()
        assert prompt.value == "hello"
        assert prompt.cursor == 5


@pytest.mark.asyncio
async def test_backspace_removes_char():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptInput)
        await pilot.press("a", "b", "c")
        await pilot.press("backspace")
        await pilot.pause()
        assert prompt.value == "ab"
        assert prompt.cursor == 2


@pytest.mark.asyncio
async def test_left_right_cursor_navigation():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptInput)
        await pilot.press("a", "b", "c")
        await pilot.press("left", "left")
        assert prompt.cursor == 1
        await pilot.press("right")
        assert prompt.cursor == 2
        # 在中间插入
        await pilot.press("X")
        assert prompt.value == "abXc"


@pytest.mark.asyncio
async def test_prompt_render_includes_input_text():
    """Static widget 渲染的 markup 应包含输入字符。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptInput)
        await pilot.press("x", "y", "z")
        await pilot.pause()
        # _renderable 是 Static 内部的 Rich markup
        rendered = str(prompt.renderable)
        assert "xyz" in rendered or "xy" in rendered  # 'z' 可能在反白光标位置


# ---------------------------------------------------------------------------
# B. /help 命令落到 transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slash_help_outputs_to_transcript():
    """/help + Enter -> transcript 应包含 12 命令名。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/", "h", "e", "l", "p", "enter")
        await pilot.pause(delay=0.2)  # 等 dispatch
        # transcript 内所有 Static 文本拼起来
        from textual.containers import VerticalScroll
        scroll = app.query_one("#transcript", VerticalScroll)
        all_text = ""
        for child in scroll.walk_children():
            if hasattr(child, "renderable"):
                all_text += str(child.renderable) + "\n"
        for cmd in ("/help", "/clear", "/threads", "/resume", "/continue",
                    "/model", "/cost", "/compact", "/plan", "/init",
                    "/version", "/exit"):
            assert cmd in all_text, f"missing {cmd}"


@pytest.mark.asyncio
async def test_slash_version_outputs():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "/version":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.2)
        from textual.containers import VerticalScroll
        scroll = app.query_one("#transcript", VerticalScroll)
        all_text = ""
        for child in scroll.walk_children():
            if hasattr(child, "renderable"):
                all_text += str(child.renderable) + "\n"
        assert "infotest 0.1.0" in all_text


# ---------------------------------------------------------------------------
# C. Slash 补全候选条
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slash_completion_visible_after_typing_slash():
    """敲 / 后 SlashCompletion 应有 visible class。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        comp = app.query_one(SlashCompletion)
        assert "visible" in comp.classes
        rendered = str(comp.renderable)
        assert "/help" in rendered
        assert "/clear" in rendered


@pytest.mark.asyncio
async def test_slash_completion_filters_on_prefix():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "/cl":
            await pilot.press(c)
        await pilot.pause()
        comp = app.query_one(SlashCompletion)
        rendered = str(comp.renderable)
        assert "/clear" in rendered
        # /help 不应在过滤后出现
        assert "/help" not in rendered


@pytest.mark.asyncio
async def test_tab_fills_first_completion():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/", "h")
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        prompt = app.query_one(PromptInput)
        assert prompt.value.startswith("/help")


# ---------------------------------------------------------------------------
# D. 历史 ↑↓
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arrow_up_recalls_history():
    """提交两条 -> ↑ 应取最新一条。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # 提交第一条（slash 命令避免触发真 LLM）
        for c in "/version":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.1)
        # 提交第二条
        for c in "/help":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.1)
        # ↑ 应回到 /help
        await pilot.press("up")
        prompt = app.query_one(PromptInput)
        assert prompt.value == "/help"
        # 再 ↑ 回到 /version
        await pilot.press("up")
        assert prompt.value == "/version"


@pytest.mark.asyncio
async def test_arrow_down_returns_to_draft():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # 提交一条
        for c in "/version":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.1)
        # 输入 draft
        for c in "draft":
            await pilot.press(c)
        prompt = app.query_one(PromptInput)
        assert prompt.value == "draft"
        # ↑ -> 历史
        await pilot.press("up")
        assert prompt.value == "/version"
        # ↓ -> 回到 draft
        await pilot.press("down")
        assert prompt.value == "draft"


# ---------------------------------------------------------------------------
# E. Shift+Enter / Ctrl+J 多行
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctrl_j_inserts_newline_glyph():
    """Ctrl+J 应在 cursor 处插入 ↵ 字符（多行模式）。"""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "line1":
            await pilot.press(c)
        await pilot.press("ctrl+j")
        for c in "line2":
            await pilot.press(c)
        prompt = app.query_one(PromptInput)
        assert "↵" in prompt.value
        assert prompt.value == "line1↵line2"


@pytest.mark.asyncio
async def test_paste_event_inserts_text_at_cursor():
    """模拟剪贴板粘贴 -> on_paste 把 text 插入 cursor 位置。"""
    from textual import events
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptInput)
        # 先输入 ab|cd（光标在 ab 后）
        for c in "abcd":
            await pilot.press(c)
        await pilot.press("left", "left")  # 光标在 ab|cd
        # 模拟 Paste 事件
        await prompt.on_paste(events.Paste(text="XYZ"))
        await pilot.pause()
        assert prompt.value == "abXYZcd"
        assert prompt.cursor == 5  # cursor 移到 XYZ 之后


@pytest.mark.asyncio
async def test_paste_multiline_uses_newline_glyph():
    """多行 paste 应被规范化为 ↵ 占位符。"""
    from textual import events
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one(PromptInput)
        await prompt.on_paste(events.Paste(text="line1\nline2"))
        assert prompt.value == "line1↵line2"


# ---------------------------------------------------------------------------
# F. Esc 上下文敏感
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_esc_clears_nonempty_input():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "hello":
            await pilot.press(c)
        await pilot.press("escape")
        prompt = app.query_one(PromptInput)
        assert prompt.value == ""


# ---------------------------------------------------------------------------
# G. 用户输入提交后立即出现在 transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submitted_text_appears_in_transcript():
    """用户敲 hi + Enter，transcript 应立即出现 ``> hi``."""
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "hi":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.1)
        from textual.containers import VerticalScroll
        scroll = app.query_one("#transcript", VerticalScroll)
        all_text = ""
        for child in scroll.walk_children():
            if hasattr(child, "renderable"):
                all_text += str(child.renderable) + "\n"
        assert "hi" in all_text
        assert ">" in all_text


# ---------------------------------------------------------------------------
# H. /exit 退出
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slash_exit_closes_app():
    app = IstApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for c in "/exit":
            await pilot.press(c)
        await pilot.press("enter")
        await pilot.pause(delay=0.1)
    # exit context 后 app 应已退
    assert app.is_running is False or app._exit is True
