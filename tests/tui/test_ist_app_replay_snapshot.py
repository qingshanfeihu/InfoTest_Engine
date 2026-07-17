"""_replay_snapshot（Ctrl+O 展开/折叠 fork 行）回归测试。

背景：ctrl+o 折叠主路径工具输出用「就地 replace_range」可行（_tool_output_blocks 存了
full_lines）；但 fork 子 agent 的行是多 worker 并发交织写入、折叠会改变行数，无法就地增量改，
只能从最新 snapshot 全量重渲染。核心风险：reducer._messages 在整个 run 期间只增长、不清理
（见 main/ist_core/tui/reducer.py），fork inner block 的 parent_tool_use_id 随 message 一起
保留在 snapshot.messages 里——理论上全量重渲染不会丢 fork 行。这里用真实的 parent_tool_use_id
消息构造 snapshot，决定性验证（不依赖 tmux 抓屏肉眼判断）：expanded 模式下 fork 行数必须等于
实际 inner block 数，不会被 3 行截断丢弃。
"""

from __future__ import annotations

from main.ist_core.ink.components.ist_app import IstInkApp
from main.ist_core.tui.message_model import (
    Message,
    MessageSnapshot,
    make_text_block,
    make_thinking_block,
    make_tool_use_block,
)


class _StubTranscript:
    """最小 Transcript —— 记 append 的行 + 支持 clear()，供断言。"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def append_message(self, text: str, *, style: str = "") -> None:
        self.lines.append(text)

    def message_count(self) -> int:
        return len(self.lines)

    def clear(self) -> None:
        self.lines.clear()

    def update_message_at(self, idx: int, text: str) -> None:
        if 0 <= idx < len(self.lines):
            self.lines[idx] = text


class _StubApp:
    def render(self) -> None:
        pass


class _StubPrompt:
    """最小 PromptInput —— value/clear/set_value，供 F-TUI-1 串框隔离断言。"""

    def __init__(self, value: str = "") -> None:
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def clear(self) -> None:
        self._value = ""

    def set_value(self, text: str, *, cursor=None) -> None:
        self._value = text


class _StubAskPanel:
    """最小 ask_user 固定面板 —— 记 update/clear 内容，供断言面板是否复活。"""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.cleared = 0

    def update(self, lines) -> None:
        self.lines = list(lines)

    def clear(self) -> None:
        self.lines = []
        self.cleared += 1


def _bare_app() -> IstInkApp:
    """造裸实例，只挂 _replay_snapshot / _render_content_block 依赖的属性。"""
    app = object.__new__(IstInkApp)
    app._transcript = _StubTranscript()
    app._app = _StubApp()
    app._ask_user = None
    app._ask_user_panel = _StubAskPanel()
    app._prompt = _StubPrompt()   # F-TUI-1 串框隔离依赖(_begin/_finish 暂存/恢复全局框)
    app._GREEN = app._RED = app._CYAN = app._BOLD = app._DIM = app._RESET = ""
    app._ai_stream_idx = -1
    app._stream_commit_idx = -1
    app._tool_start_stack = []
    app._subagent_inner_summaries = {}
    app._subagent_thinking_lines = []
    app._main_thinking_lines = []
    app._tool_output_blocks = []
    app._tool_use_row = {}
    app._tool_outputs_expanded = False
    app._thinking_expanded = False
    app._last_thinking_idx = -1
    app._last_thinking_text = ""
    app._suppress_thinking_until_done = False
    app._prev_snapshot = None
    app._persist_verbose = lambda: None  # 避免测试写 ~/.ist/tui_config.json
    app._render_markdown = lambda text, final=False: text  # 绕开 Rich/终端宽度依赖
    return app


def _fork_msg(uuid: str, block, *, parent: str) -> Message:
    return Message(uuid=uuid, role="assistant", content=(block,), parent_tool_use_id=parent)


def _build_multi_worker_snapshot() -> MessageSnapshot:
    """1 条主 agent 消息 + 2 个并发 worker，每个 worker 6 条 inner block（远超 3 行上限）。"""
    messages = [
        Message(uuid="m:0", role="assistant", content=(make_text_block("已派发 2 个 worker"),)),
    ]
    for w in ("worker-1", "worker-2"):
        for i in range(6):
            block = make_text_block(f"{w} thinking step {i}") if i % 2 == 0 else make_tool_use_block(
                tool_use_id=f"{w}:{i}", name="fs_read", input={"path": f"x{i}.md"},
            )
            messages.append(_fork_msg(f"{w}:{i}", block, parent=w))
    return MessageSnapshot(messages=tuple(messages), status="done")


def test_replay_snapshot_expanded_renders_all_fork_lines() -> None:
    """expanded=True 时,全量重渲染必须还原每个 worker 的全部 6 条 inner 行,不截断丢弃。"""
    app = _bare_app()
    app._prev_snapshot = _build_multi_worker_snapshot()
    app._tool_outputs_expanded = True

    app._replay_snapshot()

    lines = app._transcript.lines
    # 主 agent 顶层文本仍平铺成 ⏺
    assert any(l.strip().startswith("⏺") and "已派发" in l for l in lines), lines
    # 折叠占位/省略提示不应出现 —— expanded 模式下应显示真实内容
    assert not any("more subagent activity" in l for l in lines), lines
    # 2 个 worker 各 6 行 fork 内容,全部还原(不是被截到 3+1)
    fork_lines = [l for l in lines if l.strip().startswith("⎿")]
    assert len(fork_lines) == 12, (len(fork_lines), lines)


def test_replay_snapshot_collapsed_still_truncates() -> None:
    """collapsed(默认)模式下,replay 复现与实时渲染一致的截断行为:每 worker 只显示 3 行 + 省略提示。"""
    app = _bare_app()
    app._prev_snapshot = _build_multi_worker_snapshot()
    app._tool_outputs_expanded = False

    app._replay_snapshot()

    lines = app._transcript.lines
    ellipsis_lines = [l for l in lines if "more subagent activity" in l]
    assert len(ellipsis_lines) == 2, lines  # 每个 worker 各触发一次省略提示
    fork_lines = [l for l in lines if l.strip().startswith("⎿")]
    # 每 worker 只留 3 条真实 ⎿ 行(省略提示行本身不带 ⎿ 前缀,不计入),两个 worker = 6
    assert len(fork_lines) == 6, (len(fork_lines), lines)


def test_toggle_expand_flips_state_and_replays() -> None:
    """Ctrl+O 处理函数 _toggle_expand:翻转 _tool_outputs_expanded 并触发全量 replay。"""
    app = _bare_app()
    app._prev_snapshot = _build_multi_worker_snapshot()
    assert app._tool_outputs_expanded is False

    app._toggle_expand()
    assert app._tool_outputs_expanded is True
    fork_lines = [l for l in app._transcript.lines if l.strip().startswith("⎿")]
    assert len(fork_lines) == 12, fork_lines  # 展开态:12 行全还原

    app._toggle_expand()
    assert app._tool_outputs_expanded is False
    fork_lines = [l for l in app._transcript.lines if l.strip().startswith("⎿")]
    assert len(fork_lines) == 6, fork_lines  # 折叠态:回到截断视图(每 worker 3 行 + 省略提示)


def test_replay_snapshot_noop_without_prev_snapshot() -> None:
    """没有 _prev_snapshot(如启动即按 ctrl+o)时不崩、不清空现有 transcript。"""
    app = _bare_app()
    app._transcript.append_message(" existing line")
    app._prev_snapshot = None

    app._replay_snapshot()

    assert app._transcript.lines == [" existing line"]


def test_replay_snapshot_thinking_expanded_shows_full_text() -> None:
    """_thinking_expanded=True 时,fork 的 thinking block 就地展开成全文而非占位 'Thinking'。"""
    app = _bare_app()
    long_thought = "这是一段很长的 worker 思考内容,应当在展开态被完整渲染出来。"
    messages = [_fork_msg("w:0", make_thinking_block(long_thought), parent="worker-1")]
    app._prev_snapshot = MessageSnapshot(messages=tuple(messages), status="done")
    app._tool_outputs_expanded = True
    app._thinking_expanded = True

    app._replay_snapshot()

    lines = app._transcript.lines
    assert any(long_thought in l for l in lines), lines


def test_ctrl_t_folds_all_main_thinking_not_just_last() -> None:
    """回归:ctrl+t 折叠主 agent 的**所有** thinking 行,不只最后一条。

    旧 bug:_toggle_thinking 只重渲染 _last_thinking_idx(单条);earlier 主 thinking 块在
    _thinking_expanded=True 期间烤成全文后,ctrl+t 折不回去(会留一堆展开的 ∴ 全文)。
    """
    app = _bare_app()
    app._thinking_expanded = True  # 展开态:每条 thinking 渲染全文

    thoughts = ["第一段思考 alpha", "第二段思考 beta", "第三段思考 gamma"]
    for i, t in enumerate(thoughts):
        blk = make_thinking_block(t)
        msg = Message(uuid=f"m:{i}", role="assistant", content=(blk,))
        app._render_content_block(blk, msg)
        app._transcript.append_message(f" ⏺ tool {i}")  # 夹工具行,模拟真实交织、推进行号

    lines = app._transcript.lines
    assert sum(1 for t in thoughts if any(t in l for l in lines)) == 3, lines
    assert len(app._main_thinking_lines) == 3

    app._toggle_thinking()  # 按 ctrl+t 折叠

    lines = app._transcript.lines
    for t in thoughts:  # 关键:3 段全文全部折成占位,一条不剩
        assert not any(t in l for l in lines), (t, lines)
    assert sum(1 for l in lines if "ctrl+t to expand" in l) == 3, lines


# ── ask_user 面板答后残留(TODO_tui)回归 ─────────────────────────────────────

def _ask_user_block(qid: str, *, answered: bool, answers: dict | None = None):
    from main.ist_core.tui.message_model import make_payload_block, BLOCK_ASK_USER
    payload = {
        "question_id": qid,
        "questions": [{"question": "产品版本?", "header": "版本",
                       "options": [{"label": "10.5"}, {"label": "10.4"}]}],
    }
    if answered:
        payload["answered"] = True
        payload["answers"] = answers or {"产品版本?": "10.5"}
    return make_payload_block(BLOCK_ASK_USER, payload)


def test_replay_answered_ask_user_does_not_resurrect_panel() -> None:
    """答后残留根因回归:snapshot 里的**已答** ask_user 块,全量重放不复活面板
    (只留一行「已回答」摘要)。旧版 _replay_snapshot 重走该块→_begin_ask_user→
    面板被拉回、遮挡后续问询。"""
    app = _bare_app()
    blk = _ask_user_block("q1", answered=True, answers={"产品版本?": "10.5"})
    msg = Message(uuid="m:0", role="system", content=(blk,))
    app._prev_snapshot = MessageSnapshot(messages=(msg,), status="done")

    app._replay_snapshot()

    assert app._ask_user is None                       # 面板不复活
    assert not app._ask_user_panel.lines               # 固定面板为空
    assert any("已回答" in l and "10.5" in l for l in app._transcript.lines), \
        app._transcript.lines


def test_replay_unanswered_ask_user_still_shows_panel() -> None:
    """对照:**未答** ask_user 块重放仍进入问答模式(面板该在就在),不被兜底重置误清。"""
    app = _bare_app()
    blk = _ask_user_block("q2", answered=False)
    msg = Message(uuid="m:0", role="system", content=(blk,))
    app._prev_snapshot = MessageSnapshot(messages=(msg,), status="done")

    app._replay_snapshot()

    assert app._ask_user is not None                   # 未答 → 面板重建
    assert app._ask_user_panel.lines                   # 面板有内容(渲染了问题)


def test_ftui1_ask_isolates_global_prompt_box():
    """F-TUI-1 串框隔离(P0,(41)④;User 23:54/00:03 串框):ask 面板 begin 时暂存并清空
    全局输入框(防漏进的残留文本串入答案),_finish 恢复用户草稿。"""
    app = _bare_app()
    app._prompt.set_value("用户没发出去的草稿")   # ask 前全局框有内容
    # begin ask 面板 → 应暂存并清空全局框
    app._begin_ask_user("q1", [{"question": "选?", "options": [
        {"label": "A", "description": ""}, {"label": "B", "description": ""}]}])
    assert app._prompt.value == "", "ask begin 必须清空全局框(防串入答案)"
    assert app._ask_saved_prompt == "用户没发出去的草稿", "草稿必须被暂存"
    # finish → 恢复草稿
    app._finish_ask_user()
    assert app._prompt.value == "用户没发出去的草稿", "ask 结束必须恢复用户草稿"
    assert app._ask_saved_prompt == "", "恢复后清暂存位"


def test_ftui1_ask_empty_global_box_no_restore_noise():
    """ask 前全局框为空:begin 清空(no-op)、finish 不恢复噪声(空串不 set)。"""
    app = _bare_app()
    app._begin_ask_user("q1", [{"question": "选?", "options": [
        {"label": "A", "description": ""}, {"label": "B", "description": ""}]}])
    assert app._prompt.value == ""
    app._finish_ask_user()
    assert app._prompt.value == ""
