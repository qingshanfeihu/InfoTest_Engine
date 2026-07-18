"""fork 卡片渲染回归(2026-07-06 子 agent 输出卡片化,对标 opencode Task 卡)。

覆盖:渲染纯函数各状态形态 / 卡片经 _replay_snapshot 还原(卡片活在 snapshot 里,
不是 tailer 旁路行) / _insert_result_lines 对卡行登记的偏移 / 原地刷新不涨行 /
rev 守卫丢弃迟到旧快照 / _middle_ellipsis 边界。
"""

from __future__ import annotations

import time

from main.ist_core.ink.components.ist_app import (
    _ENGINE_PHASE_CN,
    IstInkApp,
    _middle_ellipsis,
    _render_engine_bottom_line,
    _render_fork_card,
    _tool_short_name,
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
        self.max_thinking = False

    def set_engine_line(self, text: str) -> None:
        self.engine_text = text

    def set_max_thinking(self, on: bool) -> None:
        self.max_thinking = bool(on)

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


def test_tool_short_names_cover_v8_fork_tools():
    # 2026-07-16 审计:两个 fork agent 白名单里这些工具此前掉裸 snake_case(zhaiyq 活体实证
    # dev_help×36 / kb_intent_search×18 / submit_ask_panel×9 / submit_behavior_fact×8 / …×1)
    for raw, want in [
        ("dev_help", "Help"),
        ("kb_intent_search", "IntentSearch"),
        ("submit_ask_panel", "AskPanel"),
        ("submit_behavior_fact", "BehaviorFact"),
        ("compile_report_underdetermined", "Underdet"),
    ]:
        got = _tool_short_name(raw)
        assert got == want, f"{raw} 应映射为 {want},实得 {got}"
        assert got != raw, f"{raw} 仍掉裸名(未进 _TOOL_SHORT_NAMES)"


def test_render_engine_bottom_line_residual_bucket():
    # broken(第三态)未进 engine_tick 的 9 键投影(事件侧 emit_tick 缺陷),渲染层残差桶兜底:
    # 复刻 zhaiyq 活体 round1——total=53,5 桶之和=51(passed36+failed_active14+escalated1),漏 2。
    eng = _render_engine_bottom_line({"kind": "engine", "run": "zhaiyq", "phase": "reconcile",
                                      "round": 1, "status": "running", "total": 53,
                                      "counts": {"passed": 36, "failed_active": 14, "escalated": 1}})
    assert "其他2" in eng, "broken 漏计的 2 案必须以『其他2』现身,不得在进度行静默消失"
    assert "53" in eng and "通过36" in eng
    # 桶和==total(正常轮)时不显残差桶,不给底行添噪
    ok = _render_engine_bottom_line({"kind": "engine", "run": "zhaiyq", "phase": "author",
                                     "round": 0, "status": "running", "total": 10,
                                     "counts": {"produced": 10}})
    assert "其他" not in ok


def test_engine_summary_card_renders_g4_decisions():
    """收口卡渲染 G4 echo(2026-07-17 team4 审计 P0-1):每条用户裁决「answer → 引擎
    理解为」并排可核对(run12 实录:「停止:…」截断被兜底成 retry,echo 上明显相悖
    即可人眼抓获)。engine_summary 是 decisions 的唯一出口,不渲染=功能全灭。"""
    now = time.time()
    card = _render_fork_card({
        "kind": "engine_summary", "run": "dongkl", "outcome": "delivered_with_labels",
        "ok": 7, "total": 13, "labels": [], "report": "workspace/outputs/dongkl/delivery_report.md",
        "decisions": [
            {"autoid": "203031754291994838", "answer": "停止:这案不用修了", "understood": "停止该案"},
            {"autoid": "203031754291994839", "answer": "继续", "understood": "授权继续 2 轮"},
        ]}, now=now)
    assert "你的裁决" in card and "引擎理解为" in card
    assert "…994838" in card and "停止:这案不用修了" in card and "停止该案" in card
    assert "…994839" in card and "授权继续 2 轮" in card
    # 超 4 条折叠
    many = [{"autoid": f"20303175429199484{i}", "answer": f"a{i}", "understood": f"u{i}"}
            for i in range(6)]
    card2 = _render_fork_card({"kind": "engine_summary", "run": "d", "ok": 1, "total": 1,
                               "decisions": many}, now=now)
    assert "另有 2 条裁决" in card2
    # 无 decisions 不渲染该段
    card3 = _render_fork_card({"kind": "engine_summary", "run": "d", "ok": 1, "total": 1},
                              now=now)
    assert "你的裁决" not in card3


def test_engine_summary_card_outcome_visual_distinction():
    """outcome 视觉区分(P0-1 伴生):delivery_incomplete/report_mismatch 时头部不得
    谎报「✓ 交付完成」——降级结论必须在收口卡可见。"""
    now = time.time()
    mism = _render_fork_card({"kind": "engine_summary", "run": "d", "ok": 7, "total": 13,
                              "outcome": "report_mismatch", "report_mismatch": True},
                             now=now)
    assert "对账失配" in mism and "⚠" in mism
    assert "✓" not in mism.split("\n")[0]
    incomp = _render_fork_card({"kind": "engine_summary", "run": "d", "ok": 12, "total": 13,
                                "outcome": "delivery_incomplete",
                                "missing": ["delivery_report.md"]}, now=now)
    assert "交付不完整" in incomp and "delivery_report.md" in incomp
    # 正常 outcome 头部形态不变
    normal = _render_fork_card({"kind": "engine_summary", "run": "d", "ok": 13, "total": 13,
                                "outcome": "delivered_all_pass"}, now=now)
    assert "交付完成" in normal and "全部通过整卷复验" in normal


def test_engine_phase_cn_covers_all_v8_nodes():
    # V8 图 11 节点(compile_engine_v8/state.py NODE_TYPES)在底行都须有中文名,无一掉裸英文
    # (user-facing 全中文纪律)。diagnose 是 2026-07-16 审计补的最后一个缺口。
    v8_nodes = ["prep", "bed_gate", "author", "ask_decision", "merge", "run",
                "reconcile", "attribute", "diagnose", "ask_contradiction", "closing"]
    for node in v8_nodes:
        assert node in _ENGINE_PHASE_CN, f"phase {node} 缺中文映射,底行会显裸英文"
        assert _ENGINE_PHASE_CN[node] != node


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


def test_fork_card_silent_run_shows_warning_not_checkmark():
    """P1-10 白跑假完成(2026-07-17 实弹:035493/035570 fork ok:true 但零产物零尾块,
    ✓ 绿标让用户以为编完、实际引擎判 escalated):worker 卡合取判——artifact_fresh
    恰为 False ∧ 无尾块 → ⚠「完成·无产出」;其余完成形态保持 ✓。"""
    now = time.time()
    base = {"kind": "fork", "skill": "compile-worker", "autoid": "204651759025035493",
            "status": "ok", "calls": 13, "elapsed_s": 218.8,
            "tokens_in": 197268, "tokens_out": 12172}
    # 白跑:零尾块 ∧ 卷面不新鲜
    silent = _render_fork_card({**base, "tail_status": "", "artifact_fresh": False},
                               now=now)
    assert "⚠" in silent and "完成·无产出" in silent
    assert "✓" not in silent
    # 正常产出:fresh=True → ✓
    ok1 = _render_fork_card({**base, "tail_status": "produced", "artifact_fresh": True},
                            now=now)
    assert "✓" in ok1 and "无产出" not in ok1
    # 欠定上报:有尾块=有交代,即使卷面不新鲜也不算白跑
    ok2 = _render_fork_card({**base, "tail_status": "needs_user_decision",
                             "artifact_fresh": False}, now=now)
    assert "✓" in ok2 and "无产出" not in ok2
    # attributor(产物形态不同)不误伤
    ok3 = _render_fork_card({**base, "skill": "compile-attributor",
                             "tail_status": "", "artifact_fresh": False}, now=now)
    assert "✓" in ok3 and "无产出" not in ok3
    # 旧事件(无新字段,artifact_fresh=None)→ 不可判,保持 ✓(向后兼容)
    ok4 = _render_fork_card(dict(base), now=now)
    assert "✓" in ok4 and "无产出" not in ok4


def test_ftui10_failure_card_humanizes_english_error():
    """F-TUI-10 失败卡英文黑话→中文人话+去向(2026-07-18;fork_end error 直透违语言分层)。
    子串映射到人话;未知错误保留原文(不隐藏)。"""
    now = time.time()
    from main.ist_core.ink.components.ist_app import _humanize_fork_error
    # 各英文黑话→中文
    assert _humanize_fork_error("fork returned no text output") == "未产出结果——引擎按无产出处理"
    assert _humanize_fork_error("no output from fork (tail=none)") == "未产出结果——已安排重写/复跑"
    assert _humanize_fork_error("[recursion-limit] GraphRecursionError") == "思考递归超限——已升级人工"
    assert "升级人工" in _humanize_fork_error("worker declared underdetermined but no ledger")
    assert _humanize_fork_error("fork skill execution failed: X") == "执行失败——已安排重试"
    # 未知错误:中文框+原文诊断(Design 必改,治 D1 裸英文泄漏漏口——中文语境+保留原文)
    _unknown = _humanize_fork_error("SomeUnexpectedError: boom")
    assert _unknown.startswith("编写未成功·未识别原因（") and "SomeUnexpectedError" in _unknown
    assert _humanize_fork_error("") == "" and _humanize_fork_error(None) == ""
    # 渲染进失败卡:卡片显中文,不显英文黑话
    card = _render_fork_card({"kind": "fork", "skill": "compile-worker", "autoid": "x" * 12,
                              "status": "error", "error": "fork returned no text output",
                              "calls": 5, "elapsed_s": 44}, now=now)
    assert "✗" in card and "未产出结果" in card
    assert "no text output" not in card, "英文黑话不得直透失败卡"


def test_ftui8_b1_authoring_phase_shows_settle_hint():
    """F-TUI-8 B1 编写期提示(治 P2-11 展示面:编写期 counts 冻初始态 produced=0,一串 0
    误读成"白干";实为合并时批量结算)。编写相位且无结算 → 计数段替换为"编写中N·产出将在
    合并时结算",不冗余显示全 0。数据源不动(纯展示)。"""
    # 编写期:produced=0 passed=0 spin>0
    authoring = _render_engine_bottom_line({
        "kind": "engine", "run": "yzg", "phase": "author", "round": 0,
        "status": "running", "total": 53,
        "counts": {"pending": 53}})
    assert "产出将在合并时结算" in authoring
    assert "编写中53" in authoring
    assert "产出0" not in authoring and "通过0 失败0" not in authoring, "编写期不冗余显示全 0"
    # 非编写期(归因/收敛):正常显示全计数,不显结算提示
    reconcile = _render_engine_bottom_line({
        "kind": "engine", "run": "yzg", "phase": "reconcile", "round": 1,
        "status": "running", "total": 53,
        "counts": {"produced": 3, "passed": 37, "failed_terminal": 9,
                   "pending": 2, "pending_decision": 2}})
    assert "产出将在合并时结算" not in reconcile
    assert "产出3" in reconcile and "通过37" in reconcile and "失败9" in reconcile
    # 编写期但已有产出(barrier 后):正常显示,不再是编写期提示
    post_barrier = _render_engine_bottom_line({
        "kind": "engine", "run": "yzg", "phase": "author", "round": 0,
        "status": "running", "total": 53,
        "counts": {"produced": 21, "pending": 32}})
    assert "产出将在合并时结算" not in post_barrier and "产出21" in post_barrier


# ── #27 编写期进度条 fork 卡驱动(收口批第⑦项,治「6 卡完成 vs bar 0/53」冻结) ──────────


def test_count_fork_cards_by_status():
    """#27:数 fork 卡 (running_n, done_n)——running=在跑, done=ok/error 跑完;
    非 fork(engine/progress)不计。照 _payloads_have_max_thinking 样板。"""
    from main.ist_core.ink.components.ist_app import _count_fork_cards_by_status
    payloads = [
        {"kind": "fork", "status": "running"},
        {"kind": "fork", "status": "ok"},
        {"kind": "fork", "status": "error"},      # done_n 含 error(编写孔跑完数不管成败)
        {"kind": "fork", "status": "running"},
        {"kind": "engine", "status": "running"},   # engine 不计
        {"kind": "progress", "status": "running"},  # progress 不计
    ]
    running_n, done_n = _count_fork_cards_by_status(payloads)
    assert running_n == 2, "2 张 running fork"
    assert done_n == 2, "ok+error 各 1 = 2 张跑完(含 error)"


def test_27_authoring_bar_driven_by_fork_done():
    """#27(zhaiyq 实弹「6 卡完成 vs bar 0/53」冻结):编写期 produced/passed 未结算(barrier
    后入账),bar 冻 0/53 与 fork 卡完成硬矛盾。修:编写期 bar/done 改用 fork 卡跑完数驱动。"""
    # 编写期 counts 全 0(未结算),但 6 张 fork 卡跑完 + 2 在跑
    eng = _render_engine_bottom_line(
        {"kind": "engine", "run": "zhaiyq", "phase": "author", "round": 0,
         "status": "running", "total": 53, "counts": {"pending": 8}},
        fork_running=2, fork_done=6)
    assert "6/53" in eng, "编写期进度条用 fork 卡完成数(6),不再冻 0/53"
    assert "█" in eng, "bar 非全空(fork_done=6 驱动填充)"
    assert "编写中2" in eng, "编写中=fork 在跑数(running_n=2),非 spin"
    assert "产出将在合并时结算" in eng
    # 对比:无 fork 计数(默认 0)退化——bar 0(同旧 F-TUI-8),编写中回落 spin
    eng0 = _render_engine_bottom_line(
        {"kind": "engine", "run": "zhaiyq", "phase": "author", "round": 0,
         "status": "running", "total": 53, "counts": {"pending": 8}})
    assert "0/53" in eng0 and "编写中8" in eng0, "无 fork 计数退化旧行为(bar 0,编写中 spin)"


def test_27_authoring_fork_activity_triggers_without_spin():
    """#27 组合判据扩:barrier-collect 下 spin 可能尚未投影(authored 全 fork 跑完才 append),
    靠 fork 卡在跑/跑完也进编写期显示(spin=0 但 fork_running/done>0)。"""
    eng = _render_engine_bottom_line(
        {"kind": "engine", "run": "zhaiyq", "phase": "worker_fanout", "round": 0,
         "status": "running", "total": 53, "counts": {}},        # spin=0(counts 空)
        fork_running=5, fork_done=3)
    assert "产出将在合并时结算" in eng, "spin=0 但 fork 在跑 → 仍编写期(组合判据 fork 项)"
    assert "3/53" in eng and "编写中5" in eng


def test_27_non_authoring_fork_counts_ignored():
    """#27:非编写期(有产出/已结算)fork 计数不参与——bar 仍用 produced+passed,不被覆盖。"""
    eng = _render_engine_bottom_line(
        {"kind": "engine", "run": "zhaiyq", "phase": "author", "round": 0,
         "status": "running", "total": 53, "counts": {"produced": 21, "pending": 32}},
        fork_running=2, fork_done=6)
    assert "21/53" in eng, "已结算(produced=21)→bar 用 produced,不被 fork_done(6)覆盖"
    assert "产出将在合并时结算" not in eng
    assert "产出21" in eng
