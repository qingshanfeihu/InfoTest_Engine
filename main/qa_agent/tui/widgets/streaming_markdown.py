"""StreamingMarkdown：LLM token 流的实时 Markdown 渲染（80ms 节流）。

对齐 src/components/messages/AssistantTextMessage.tsx + Markdown.tsx 的
"逐 token 即时 render Markdown"行为（不是行 buffer，不是 commit-then-render）。

实现：
- 流式期：每个 token chunk 累加到 self._buf；如果距上次 update >=80ms，触发 update()
  传 Rich Markdown(self._buf) — Rich 会按 markdown 语义重新渲染（# 标题立即变粗）
- 80ms 与 sink.py 的 token_throttle_ms 对齐 (cli_sink.py:60 同款)
- llm_end → finalize() 强制最后一次 flush 并标记完成
"""

from __future__ import annotations

import time

from rich.markdown import Markdown
from textual.widgets import Static

from main.qa_agent.tui.inline_renderer import render_completion_line


class StreamingMarkdown(Static):
    """Live AI text widget — Markdown 实时渲染。"""

    DEFAULT_CSS = """
    StreamingMarkdown {
        height: auto;
        width: 1fr;
        margin: 0 0 1 0;
    }
    """

    def __init__(self, *, throttle_s: float = 0.08) -> None:
        # 起始空白，Rich Markdown 会渲染成空行
        super().__init__("…")
        self._buf = ""
        self._throttle_s = throttle_s
        self._last_render = 0.0
        self._is_final = False

    @property
    def content(self) -> str:
        return self._buf

    def append_chunk(self, chunk: str) -> None:
        if self._is_final or not chunk:
            return
        self._buf += chunk
        now = time.time()
        if now - self._last_render >= self._throttle_s:
            self._render_now()
            self._last_render = now

    def finalize(self) -> None:
        """llm_end 触发：强制最后一次 flush + 锁定为 final 状态。"""
        if self._is_final:
            return
        self._render_now()
        self._is_final = True

    def _render_now(self) -> None:
        if self._buf:
            self.update(Markdown(self._buf))
        else:
            self.update("…")

    def is_final(self) -> bool:
        return self._is_final
