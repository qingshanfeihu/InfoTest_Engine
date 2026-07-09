"""fork 卡片渲染回归(2026-07-06 子 agent 输出卡片化,对标 opencode Task 卡)。

覆盖:渲染纯函数各状态形态 / 卡片经 _replay_snapshot 还原(卡片活在 snapshot 里,
不是 tailer 旁路行) / _insert_result_lines 对卡行登记的偏移 / 原地刷新不涨行 /
rev 守卫丢弃迟到旧快照 / _middle_ellipsis 边界。
"""

from __future__ import annotations

import time

from main.ist_core.ink.components.ist_app import (
    IstInkApp,
    _middle_ellipsis,
    _render_engine_bottom_line,
    _render_fork_card,
)
from main.ist_core.tui.message_model import (
    BLOCK_FORK_CARD,
    Message,
    MessageSnapshot,
    make_payload_block,
    make_system_message,
)


class _StubTranscript:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def append_message(self, text: str, *, style: str = "") -> None:
        self.lines.append(text)

    def append_messages(self, texts: list[str]) -> None:
        self.lines.extend(texts)

    def message_count(self) -> int:
        return len(self.lines)

    def clear(self) -> None:
        self.lines.clear()

    def update_message_at(self, idx: int, text: str) -> None:
        if 0 <= idx < len(self.lines):
            self.lines[idx] = text

    def replace_range(self, at: int, count: int, lines: list[str]) -> None:
        self.lines[at:at + count] = lines


class _StubApp:
    def render(self) -> None:
        pass


class _StubFooter:
    def __init__(self) -> None:
        self.engine_text = ""

    def set_engine_line(self, text: str) -> None:
        self.engine_text = text

    def update(self, **kw) -> None:
        pass


def _mini_app() -> IstInkApp:
    app = object.__new__(IstInkApp)
    app._transcript = _StubTranscript()
    app._app = _StubApp()
    app._footer = _StubFooter()
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
    app._fork_card_rows = {}
    app._fork_card_payloads = {}
    app._last_board_rev = 0
    app._last_snapshot_rev = 0
    app._persist_verbose = lambda: None
    app._render_markdown = lambda text, final=False: text
    return app


def _card_msg(uuid: str, payload: dict) -> Message:
    return make_system_message(uuid=uuid, content=make_payload_block(BLOCK_FORK_CARD, payload))


# ---------------------------------------------------------------- 渲染纯函数

def test_render_states_shapes():
    now = time.time()
    running = _render_fork_card({
        "kind": "fork", "skill": "compile-worker", "autoid": "203031754291994838",
        "brief_head": "编写", "status": "running", "start_ts": now - 65,
        "last_event_ts": now, "current_tool": "dev_probe",
        "current_arg": "show statistics sdns", "n_calls": 7}, now=now)
    assert "编写·994838" in running and "↳ Probe(" in running and "7 calls" in running
    assert running.count("\n") == 1, "running 卡=标题+当前工具两行"

    done = _render_fork_card({"kind": "fork", "skill": "ist-compile-grade",
                              "autoid": "203031754291994838", "status": "ok",
                              "calls": 12, "elapsed_s": 95,
                              "tokens_in": 1_200_000, "tokens_out": 52_000}, now=now)
    assert done.count("\n") == 0 and "✓" in done and "完成" in done and "↑1200.0k" in done

    err = _render_fork_card({"kind": "fork", "skill": "compile-worker",
                             "tag": "worker:994838", "status": "error",
                             "error": "error: 步骤载荷为空\n第二行不显示",
                             "calls": 3, "elapsed_s": 44}, now=now)
    assert "✗" in err and "步骤载荷为空" in err and "第二行" not in err

    compact = _render_fork_card({"kind": "fork", "skill": "compile-worker",
                                 "autoid": "203031754291994838", "status": "running",
                                 "start_ts": now, "last_event_ts": now,
                                 "n_calls": 2}, now=now, compact=True)
    assert compact.count("\n") == 0, "紧凑卡单行"

    stalled = _render_fork_card({"kind": "fork", "skill": "compile-worker",
                                 "autoid": "203031754291994838", "status": "running",
                                 "start_ts": now - 5000, "last_event_ts": now - 4000,
                                 "n_calls": 5}, now=now)
    assert "◌" in stalled and "无事件" in stalled


def test_render_engine_bottom_line_and_progress():
    # 引擎聚合 → footer 底部行(用户定稿):进度条+文字计数,九个 ledger 状态全归属
    eng = _render_engine_bottom_line({"kind": "engine", "run": "dongkl", "phase": "run_digest",
                                      "round": 1, "status": "running", "total": 34,
                                      "counts": {"produced": 4, "passed": 22, "dispatched": 7,
                                                 "failed_terminal": 1, "escalated": 0}})
    assert "编译 dongkl" in eng and "上机" in eng and "26/34" in eng
    assert "轮次1" in eng and "r1" not in eng, "轮次标签用中文『轮次N』,不用缩写 r"
    assert "█" in eng and "░" in eng, "必须有进度条"
    assert "产出4" in eng and "通过22" in eng and "编写中7" in eng and "失败1" in eng
    # 欠定/待用户段(dongkl 实跑暴露:漏了它,7 case 在聚合行凭空消失)
    eng2 = _render_engine_bottom_line({"kind": "engine", "run": "dongkl",
                                       "phase": "worker_fanout", "round": 0,
                                       "status": "running", "total": 34,
                                       "counts": {"produced": 6, "dispatched": 21,
                                                  "pending_decision": 7}})
    assert "欠定7" in eng2 and "6/34" in eng2
    # 收尾态
    done = _render_engine_bottom_line({"kind": "engine", "run": "dongkl", "phase": "report",
                                       "round": 2, "status": "done", "total": 34,
                                       "counts": {"passed": 32, "failed_terminal": 2}})
    assert "已收尾" in done and "32/34" in done
    now = time.time()

    prog = _render_fork_card({"kind": "progress", "phase": "上机", "status": "running",
                              "elapsed_s": 223, "total_s": 1440, "n_cases": 32,
                              "detail": "smoke_test/sdns/ist_staging_sdns/203031753342777976/test_xlsx.py"},
                             now=now)
    assert prog.count("\n") == 0 and "223s/1440s" in prog and "32 case" in prog
    assert "…" in prog, "长路径必须中段省略,不整段平铺"

    prog_done = _render_fork_card({"kind": "progress", "phase": "上机", "status": "done",
                                   "elapsed_s": 812, "n_cases": 32}, now=now)
    assert "✓" in prog_done and "上机完成" in prog_done


def test_render_expanded_appends_recent():
    now = time.time()
    card = _render_fork_card({"kind": "fork", "skill": "compile-worker", "autoid": "x" * 12,
                              "status": "running", "start_ts": now, "last_event_ts": now,
                              "current_tool": "fs_read", "current_arg": "a.md", "n_calls": 1,
                              "recent": ["dev_probe → Pool p1", "fs_grep → 3 hits"]},
                             now=now, expanded=True)
    assert "dev_probe → Pool p1" in card and "fs_grep → 3 hits" in card
    # 完成/失败卡展开态同样显示 recent(收口后回看它干了什么)
    done = _render_fork_card({"kind": "fork", "skill": "compile-worker", "autoid": "x" * 12,
                              "status": "ok", "calls": 5, "elapsed_s": 60,
                              "recent": ["compile_emit → produced structurally-correct"]}, now=now, expanded=True)
    assert "compile_emit → produced structurally-correct" in done
    # 折叠态不带
    done_c = _render_fork_card({"kind": "fork", "skill": "compile-worker", "autoid": "x" * 12,
                                "status": "ok", "calls": 5, "elapsed_s": 60,
                                "recent": ["compile_emit → produced structurally-correct"]}, now=now)
    assert "compile_emit" not in done_c


# ---------------------------------------------------------------- 卡片进 transcript

def test_fork_card_replay_restores_and_registers():
    """卡片在 snapshot.messages 里 → _replay_snapshot(ctrl+o)后卡行还原、登记重建;
    引擎卡走 footer 底部行不占 transcript。
    (旧平铺行是 tailer 旁路 append,不在 snapshot,replay 即丢——本测试钉死新架构不回退)"""
    app = _mini_app()
    now = time.time()
    snap = MessageSnapshot(
        messages=(
            _card_msg("fork:f1", {"kind": "fork", "skill": "compile-worker",
                                  "autoid": "203031754291994838", "status": "running",
                                  "start_ts": now, "last_event_ts": now,
                                  "current_tool": "dev_probe", "current_arg": "show x",
                                  "n_calls": 3}),
            _card_msg("engine:dongkl", {"kind": "engine", "run": "dongkl",
                                        "phase": "worker_fanout", "round": 0,
                                        "status": "running", "total": 34,
                                        "counts": {"produced": 4}}),
        ),
        status="running", rev=5, fork_board_rev=7,
        fork_card_indices={"fork:f1": 0, "engine:dongkl": 1},
    )
    app._prev_snapshot = snap
    app._replay_snapshot()
    lines = app._transcript.lines
    assert any("编写·994838" in l for l in lines)
    assert not any("dongkl" in l for l in lines), "引擎卡不进 transcript"
    assert "编译 dongkl" in app._footer.engine_text and "4/34" in app._footer.engine_text
    assert app._fork_card_rows == {"fork:f1": 0}
    assert app._last_board_rev == 7


def test_engine_bottom_line_cleared_when_absent():
    """新 run reset 后 snapshot 无引擎卡 → footer 底部行清空。"""
    app = _mini_app()
    app._footer.engine_text = " 编译 dongkl · …"
    empty = MessageSnapshot(messages=(), status="idle", rev=9, fork_board_rev=8,
                            fork_card_indices={})
    app._refresh_fork_cards_from_snapshot(empty)
    assert app._footer.engine_text == ""


def test_insert_result_lines_offsets_card_rows_and_thinking():
    app = _mini_app()
    app._transcript.lines = ["A", "B", "card"]
    app._fork_card_rows = {"fork:f1": 2}
    app._main_thinking_lines = [{"idx": 2, "full": "x"}]
    app._subagent_thinking_lines = [{"idx": 1, "full": "y"}]
    app._insert_result_lines(1, ["r1", "r2"])
    assert app._transcript.lines == ["A", "r1", "r2", "B", "card"]
    assert app._fork_card_rows["fork:f1"] == 4
    assert app._main_thinking_lines[0]["idx"] == 4
    assert app._subagent_thinking_lines[0]["idx"] == 3, "idx==at_idx 也要偏移"


def test_board_refresh_updates_in_place_without_growth():
    app = _mini_app()
    now = time.time()
    p0 = {"kind": "fork", "skill": "compile-worker", "autoid": "203031754291994838",
          "status": "running", "start_ts": now, "last_event_ts": now,
          "current_tool": "fs_read", "current_arg": "a.md", "n_calls": 1}
    msg = _card_msg("fork:f1", p0)
    app._render_content_block(msg.content[0], msg)
    assert len(app._transcript.lines) == 1 and "Read(" in app._transcript.lines[0]

    p1 = dict(p0, current_tool="dev_probe", current_arg="show sdns", n_calls=5)
    snap = MessageSnapshot(messages=(_card_msg("fork:f1", p1),), status="running",
                           rev=2, fork_board_rev=2, fork_card_indices={"fork:f1": 0})
    app._refresh_fork_cards_from_snapshot(snap)
    assert len(app._transcript.lines) == 1, "原地更新不涨行"
    assert "Probe(" in app._transcript.lines[0] and "5 calls" in app._transcript.lines[0]


def test_rev_guard_drops_stale_snapshot():
    app = _mini_app()
    now = time.time()
    s_new = MessageSnapshot(messages=(_card_msg("fork:a", {"kind": "fork", "skill": "s",
                                                           "status": "running",
                                                           "start_ts": now,
                                                           "last_event_ts": now}),),
                            status="running", rev=10, fork_board_rev=1,
                            fork_card_indices={"fork:a": 0})
    app._on_snapshot_locked(s_new)
    n = len(app._transcript.lines)
    s_stale = MessageSnapshot(messages=(), status="running", rev=9)
    app._on_snapshot_locked(s_stale)
    assert len(app._transcript.lines) == n, "迟到旧快照必须被丢弃"
    assert app._prev_snapshot is s_new, "prev 不能被旧快照回退(否则增量 diff 重复渲染)"


def test_middle_ellipsis_edges():
    assert _middle_ellipsis("short", 20) == "short"
    p = "smoke_test/sdns/ist_staging_sdns/203031753342777976/test_xlsx.py"
    out = _middle_ellipsis(p, 50)
    assert len(out) <= 50 and out.startswith("smoke_test/") and out.endswith("test_xlsx.py")
    long_flat = "x" * 100
    out2 = _middle_ellipsis(long_flat, 30)
    assert len(out2) <= 30 and "…" in out2
