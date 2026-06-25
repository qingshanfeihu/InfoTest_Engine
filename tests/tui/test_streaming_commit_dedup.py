"""回归:流式 assistant 文本与其提交版不得重复渲染成两条 ⏺。

旧 bug:`_on_snapshot_locked` 流式阶段在 `_ai_stream_idx` 处 append 一条 ⏺ 文本,
流结束把 `_ai_stream_idx=-1` 丢掉引用;随后同一段文本作为最终 BLOCK_TEXT 落进
`snapshot.messages`,`_render_content_block` 又 append 一条 → transcript 里出现两条
完全相同的 ⏺ 文本。

修复:流结束时把行号存进 `_stream_commit_idx`,提交版到来时**原地替换**那一行,不再 append。
"""

from __future__ import annotations

from main.ist_core.ink.components import ist_app as M
from main.ist_core.ink.components.transcript import Transcript
from main.ist_core.tui.message_model import (
    MessageSnapshot,
    make_assistant_message,
    make_text_block,
)


class _FakeApp:
    class _Lock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    lock = _Lock()

    def render(self):
        pass


class _FakeFooter:
    def update(self, **kw):
        pass


class _FakePlan:
    is_visible = False

    def mark_all_done(self):
        pass


def _stub():
    s = type("Stub", (), {})()
    s._transcript = Transcript()
    s._app = _FakeApp()
    s._footer = _FakeFooter()
    s._plan_panel = _FakePlan()
    s._render_markdown = lambda text, final=False: text
    s._flush_pending_tools = lambda: None
    s._notify_new_outputs = lambda: None
    s._render_subagent_inner_block = lambda block, pid: None
    s._ai_stream_idx = -1
    s._stream_commit_idx = -1
    s._prev_snapshot = None
    s._tokens_used = 0
    s._is_loading = True
    s._BOLD = s._CYAN = s._DIM = s._RESET = ""
    s._render_content_block = M.IstInkApp._render_content_block.__get__(s)
    s._on_snapshot_locked = M.IstInkApp._on_snapshot_locked.__get__(s)
    return s


def _dot_lines(s):
    return [m for m in s._transcript._messages if "⏺" in m]


def test_streaming_then_commit_renders_single_dot_line():
    s = _stub()
    text = "脑图内容已读取。这是一个 SDNS CNAME 会话保持的用例。"

    # 1) 流式阶段:逐步累积(append + 原地更新)
    s._on_snapshot_locked(MessageSnapshot(messages=(), streaming_text="脑图内容", status="running"))
    s._on_snapshot_locked(MessageSnapshot(messages=(), streaming_text=text, status="running"))
    assert len(_dot_lines(s)) == 1, "流式阶段应只有一条 ⏺"

    # 2) 提交阶段:streaming_text 转 None,同段文本作为最终 BLOCK_TEXT 落进 messages
    commit = MessageSnapshot(
        messages=(make_assistant_message(uuid="r:1", content=make_text_block(text)),),
        streaming_text=None,
        status="running",
    )
    s._on_snapshot_locked(commit)

    dots = _dot_lines(s)
    assert len(dots) == 1, f"提交后应仍只有一条 ⏺(原地替换),实际 {len(dots)} 条:{dots}"
    assert text in dots[0]


def test_commit_without_prior_streaming_appends_once():
    # 关流式场景:无流式占位,提交版正常 append 一条(不漏)。
    s = _stub()
    text = "版本确认为 10.5。现在启动编译流水线。"
    snap = MessageSnapshot(
        messages=(make_assistant_message(uuid="r:1", content=make_text_block(text)),),
        streaming_text=None,
        status="running",
    )
    s._on_snapshot_locked(snap)
    dots = _dot_lines(s)
    assert len(dots) == 1
    assert text in dots[0]


def test_two_separate_turns_each_single_dot():
    # 两段不同的流式文本(中间流结束)→ 两条独立 ⏺,各自不重复。
    # reducer 快照是累积的:messages 逐帧增长,prev_count 切片只渲染新增。
    s = _stub()
    t1 = "第一段:读取脑图。"
    t2 = "第二段:启动编译。"
    msg1 = make_assistant_message(uuid="r:1", content=make_text_block(t1))
    msg2 = make_assistant_message(uuid="r:2", content=make_text_block(t2))

    # 第一段:流式 → 提交(messages 落入 t1)
    s._on_snapshot_locked(MessageSnapshot(messages=(), streaming_text=t1, status="running"))
    s._on_snapshot_locked(MessageSnapshot(messages=(msg1,), streaming_text=None, status="running"))
    # 第二段:流式(messages 仍含 t1)→ 提交(messages 累积为 t1+t2)
    s._on_snapshot_locked(MessageSnapshot(messages=(msg1,), streaming_text=t2, status="running"))
    s._on_snapshot_locked(MessageSnapshot(messages=(msg1, msg2), streaming_text=None, status="running"))

    dots = _dot_lines(s)
    assert len(dots) == 2, f"应两条独立 ⏺,实际 {len(dots)}:{dots}"
    assert t1 in dots[0] and t2 in dots[1]
