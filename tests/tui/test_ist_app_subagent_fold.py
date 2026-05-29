"""渲染层回归 —— fork subagent 内部事件不得平铺成顶层 ⏺（SEG1 泄漏修复）。

bug 背景：fork verifier 的研究报告（9000+ 字）经 _MainAgentProgressHandler 实时
流到 reducer，带上 parent_tool_use_id；但旧 _render_content_block 渲染 BLOCK_TEXT
时不看 parent，整段平铺成顶层 ⏺，与「fork result 只折成一行 Done」的设计相悖。

本测试用裸 IstInkApp 实例（不走重型 __init__）+ stub Transcript 驱动
_render_content_block，断言：
- parent 非空的长文 BLOCK_TEXT → 不出现顶层 "⏺ <长文>"，只出现折叠 "⎿" 行
- parent 非空的 BLOCK_TOOL_USE → 折成 "⎿ <ShortName>" 进度行
- parent 为空的普通 BLOCK_TEXT → 仍平铺成顶层 ⏺（主 agent 正文不受影响）
"""

from __future__ import annotations

from main.ist_core.ink.components.ist_app import IstInkApp
from main.ist_core.tui.message_model import (
    ContentBlock,
    Message,
    make_text_block,
    make_tool_use_block,
)


class _StubTranscript:
    """最小 Transcript —— 只记 append 的行，供断言。"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def append_message(self, text: str, *, style: str = "") -> None:
        self.lines.append(text)

    def message_count(self) -> int:
        return len(self.lines)


def _bare_app() -> IstInkApp:
    """造裸实例，只挂 _render_content_block 依赖的属性（绕开重型 __init__）。"""
    app = object.__new__(IstInkApp)
    app._transcript = _StubTranscript()
    app._GREEN = app._RED = app._CYAN = app._BOLD = app._DIM = app._RESET = ""
    app._ai_stream_idx = -1
    app._tool_start_stack = []
    app._subagent_inner_summaries = {}
    app._tool_outputs_expanded = False
    return app


def _msg(block, *, parent: str = "") -> Message:
    return Message(
        uuid="r1:1",
        role="assistant",
        content=(block,),
        parent_tool_use_id=parent,
    )


def test_subagent_long_text_folds_not_flattened() -> None:
    """parent 非空的长文 BLOCK_TEXT → 折成 ⎿ 行，绝不平铺成顶层 ⏺ <长文>。"""
    app = _bare_app()
    long_report = "Summary\n" + ("草稿整体质量尚可。" * 500) + "\nVERDICT: PARTIAL"
    block = make_text_block(long_report)
    msg = _msg(block, parent="r1:fork")

    app._render_content_block(block, msg)

    lines = app._transcript.lines
    
    assert not any(line.strip().startswith("⏺") for line in lines), lines
    
    assert not any("草稿整体质量尚可" in line for line in lines), lines
    
    assert len(lines) == 1 and "⎿" in lines[0], lines


def test_subagent_tool_use_folds_to_progress_line() -> None:
    """parent 非空的 BLOCK_TOOL_USE → 折成 ⎿ <ShortName> 进度行。"""
    app = _bare_app()
    block = make_tool_use_block(
        tool_use_id="r1:9",
        name="qa_deepagent_read_file",
        input={"file_path": "knowledge/data/markdown/qa/x.md"},
        status="running",
    )
    msg = _msg(block, parent="r1:fork")

    app._render_content_block(block, msg)

    lines = app._transcript.lines
    assert len(lines) == 1 and "⎿" in lines[0], lines
    assert not any(line.strip().startswith("⏺") for line in lines), lines


def test_subagent_inner_truncates_after_max_lines() -> None:
    """同一 parent 超过 _SUBAGENT_INNER_MAX_LINES 行后折成省略提示，不无限刷屏。"""
    app = _bare_app()
    n = app._SUBAGENT_INNER_MAX_LINES
    for _ in range(n + 3):
        block = make_text_block("thinking chunk")
        app._render_content_block(block, _msg(block, parent="r1:fork"))

    lines = app._transcript.lines
    
    assert len(lines) == n + 1, lines
    assert "more subagent activity" in lines[-1], lines


def test_main_agent_text_still_flattens_to_top_level() -> None:
    """parent 为空（主 agent 正文）→ 仍平铺成顶层 ⏺，复述报告不受影响。"""
    app = _bare_app()
    app._render_markdown = lambda text, final=False: text
    block = make_text_block("## 评审报告\nF1-F4 ...\nVERDICT: PARTIAL")
    msg = _msg(block, parent="")

    app._render_content_block(block, msg)

    lines = app._transcript.lines
    assert len(lines) == 1, lines
    assert lines[0].strip().startswith("⏺"), lines
    assert "评审报告" in lines[0], lines

