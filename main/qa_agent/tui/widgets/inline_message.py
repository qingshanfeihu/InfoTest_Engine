"""InlineMessage：单条 IstMessage 的 Textual widget 包装器。

Static widget 持有一个 IstMessage 实例 + 用 inline_renderer 渲染成 Renderable。
工具消息的 status 改变（pending→running→done）时调 ``update_status()`` 触发 Rich
重新渲染（不重建 widget）。

对齐 REPL.tsx 的"消息数组累加 + Static 列表渲染"模式。
"""

from __future__ import annotations

from textual.widgets import Static

from main.qa_agent.tui.inline_renderer import (
    render,
    render_completion_line,
    render_tool_call_line,
    render_tool_output,
)
from main.qa_agent.tui.messages import (
    AIFinalMessage,
    AIThinkingMessage,
    BashExecMessage,
    FileReadMessage,
    GrepHitsMessage,
    IstMessage,
    LsTreeMessage,
    PlatformTaskMessage,
    PythonExecMessage,
    SubAgentDispatchMessage,
    ToolCallMessage,
    XlsxSheetMessage,
)


class InlineMessage(Static):
    """A single non-streaming message line in the transcript."""

    DEFAULT_CSS = """
    InlineMessage {
        height: auto;
        width: 1fr;
        padding: 0 0;
        margin: 0 0;
    }
    """

    def __init__(self, msg: IstMessage) -> None:
        super().__init__(render(msg))
        self.message = msg
        # 把 IstMessage.css_class 挂到 widget classes 上，让 styles.tcss 能匹配
        # （例如 .ist-human-input → 全宽背景）
        if msg.css_class:
            self.add_class(msg.css_class)

    def update_status(self, status: str) -> None:
        """Tool status transition (pending → running → done | error). Re-render in place."""
        if hasattr(self.message, "status"):
            self.message.status = status
        # 重新渲染：单条工具消息走 render_tool_call_line（保持单行）
        if isinstance(self.message, (
            FileReadMessage, XlsxSheetMessage, GrepHitsMessage, LsTreeMessage,
            PythonExecMessage, BashExecMessage, PlatformTaskMessage, ToolCallMessage,
            SubAgentDispatchMessage,
        )):
            self.update(render_tool_call_line(self.message, status=status))
        else:
            self.update(render(self.message))


class ToolOutputBlock(Static):
    """Indented tool output block 。

    工具行下方的独立消息块，缩进 2 空格 + 5 行截断 + ``… +N lines (ctrl+o to expand)``。
    Mounted **after** the tool's InlineMessage when tool_result event arrives.

    Ctrl+O 全局切换 transcript view（ ``ctrl+o → app:toggleTranscript``）：
    展开模式下所有 ToolOutputBlock 显示完整 stdout/stderr，不截断。
    """

    DEFAULT_CSS = """
    ToolOutputBlock {
        height: auto;
        width: 1fr;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, stdout: str, *, stderr: str = "") -> None:
        # 保留原始内容，set_expanded() 时根据 expanded 状态重渲染
        self._stdout = stdout
        self._stderr = stderr
        self._expanded = False
        rendered = render_tool_output(stdout, stderr=stderr)
        if rendered is None:
            rendered = ""
        super().__init__(rendered)

    def set_expanded(self, expanded: bool) -> None:
        """切换展开状态（Ctrl+O 全局触发）。expanded=True → 展示完整内容（无截断）。"""
        if self._expanded == expanded:
            return
        self._expanded = expanded
        # 展开 = 用一个超大的 max_lines 跳过截断
        max_lines = 10**9 if expanded else None
        kwargs = {"stderr": self._stderr}
        if max_lines is not None:
            kwargs["max_lines"] = max_lines
        rendered = render_tool_output(self._stdout, **kwargs)
        if rendered is None:
            rendered = ""
        self.update(rendered)


class CompletionLine(Static):
    """``⏱ 1.2s · 845 tokens`` 紧跟在 AI 消息完成后。"""

    DEFAULT_CSS = """
    CompletionLine {
        height: 1;
        width: 1fr;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, *, elapsed_s: float, tokens: int) -> None:
        super().__init__(render_completion_line(elapsed_s, tokens))
