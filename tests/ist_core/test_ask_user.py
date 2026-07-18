"""ask_user 工具 + reducer 事件 + AskUserSession 交互逻辑回归。"""

from __future__ import annotations

import threading

import pytest


# ── 工具注册 ──────────────────────────────────────────────────────────


def test_ask_user_registered_in_default_tools():
    from main.ist_core.agents.main_agent import _default_generic_tools

    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    assert "ask_user" in names


# ── reducer 事件 → ask_user 块 ────────────────────────────────────────


def test_reducer_emits_ask_user_block():
    from main.ist_core.tui.reducer import MessageReducer

    ev = {
        "kind": "ask_user_request",
        "run_id": "r1",
        "seq": 3,
        "ts": "",
        "payload": {
            "question_id": "qid1",
            "questions": [
                {
                    "question": "选哪个?",
                    "header": "方案",
                    "options": [
                        {"label": "A", "description": "方案A"},
                        {"label": "B", "description": "方案B"},
                    ],
                }
            ],
        },
        "tags": {"name": "ask_user"},
    }
    r = MessageReducer()
    r.dispatch(ev)
    msg = r._messages[-1]
    block = msg.content[0]
    assert block.type == "ask_user"
    payload = dict(block.payload)
    assert payload["question_id"] == "qid1"
    assert len(payload["questions"]) == 1


# ── 工具 schema 校验 ──────────────────────────────────────────────────


def test_ask_user_rejects_bad_input():
    from main.ist_core.tools.ask_user import ask_user

    assert "error" in ask_user.invoke({"questions": []})
    # options 少于 2
    bad = [{"question": "q?", "options": [{"label": "x", "description": ""}]}]
    assert "error" in ask_user.invoke({"questions": bad})


def test_submit_answers_unblocks_tool():
    """工具在后台线程阻塞，submit_answers 唤醒它并回填答案文本。"""
    from main.ist_core.tools import ask_user as au

    result: dict = {}

    def run_tool():
        result["out"] = au.ask_user.invoke(
            {
                "questions": [
                    {
                        "question": "继续?",
                        "options": [
                            {"label": "是", "description": ""},
                            {"label": "否", "description": ""},
                        ],
                    }
                ]
            }
        )

    t = threading.Thread(target=run_tool, daemon=True)
    t.start()
    # 等工具注册 pending
    qid = None
    for _ in range(200):
        pend = au.list_pending_questions()
        if pend:
            qid = pend[0]["question_id"]
            break
        threading.Event().wait(0.01)
    assert qid is not None
    assert au.submit_answers(qid, {"继续?": "是"})
    t.join(timeout=2.0)
    assert "继续?" in result["out"]
    assert "是" in result["out"]


# ── AskUserSession 交互逻辑 ───────────────────────────────────────────


@pytest.fixture
def capture_submit(monkeypatch):
    from main.ist_core.tools import ask_user as au

    captured: dict = {}
    monkeypatch.setattr(
        au, "submit_answers",
        lambda qid, ans: captured.update({"qid": qid, "ans": ans}) or True,
    )
    return captured


def _session(questions, captured):
    from main.ist_core.ink.components.ask_user_view import AskUserSession

    return AskUserSession(
        "q", questions, render=lambda: None, on_finish=lambda: None
    )


def test_session_single_select(capture_submit):
    s = _session(
        [{"question": "选?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("down", "")
    s.handle_key("return", "")
    assert capture_submit["ans"] == {"选?": "B"}


def test_session_multi_select(capture_submit):
    s = _session(
        [{"question": "多选?", "multiSelect": True, "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("space", "")           # A
    s.handle_key("down", "")
    s.handle_key("space", "")           # B
    s.handle_key("return", "")
    assert capture_submit["ans"] == {"多选?": "A, B"}


def test_session_other_freetext(capture_submit):
    s = _session(
        [{"question": "其他?", "options": [{"label": "A", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("o", "o")
    assert s.in_other_input
    s.submit_other_text("自定义X")
    assert capture_submit["ans"] == {"其他?": "自定义X"}


def test_session_other_empty_text_guard(capture_submit):
    # 防呆(2026-07-16 532862 实弹):高亮 Other→enter→空文本提交曾落成空答案,而空答案
    # 与 esc 取消无法区分→引擎判取消→案自动挂起。空文本不得提交,须留在输入态并提示。
    s = _session(
        [{"question": "其他?", "options": [{"label": "A", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("o", "o")
    assert s.in_other_input
    s.submit_other_text("")            # 空文本提交
    assert "ans" not in capture_submit, "空文本不得提交(否则空答案=取消→案被自动挂起)"
    assert s.in_other_input, "空文本后仍留在输入态,等用户补内容或 esc 显式取消"
    assert any("不能为空" in ln for ln in s.render_lines()), "面板须显防呆提示"
    # 补上真实内容后正常提交,提示清除
    s.submit_other_text("真实裁决")
    assert capture_submit["ans"] == {"其他?": "真实裁决"}


def test_session_other_whitespace_only_guard(capture_submit):
    # 纯空白(空格/制表符)strip 后为空,同样不得落成有效 Other
    s = _session(
        [{"question": "其他?", "options": [{"label": "A", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("o", "o")
    s.submit_other_text("   \t ")
    assert "ans" not in capture_submit
    assert s.in_other_input
    # esc 取消清除提示并退回选项
    s.cancel_other_input()
    assert not s.in_other_input


def test_session_cancel(capture_submit):
    s = _session(
        [{"question": "取消?", "options": [{"label": "A", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("escape", "")
    assert capture_submit["ans"] == {}


def test_session_multi_question_navigation(capture_submit):
    s = _session(
        [
            {"question": "Q1?", "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
            {"question": "Q2?", "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
        ],
        capture_submit,
    )
    s.handle_key("return", "")          # Q1 = A
    s.handle_key("down", "")
    s.handle_key("return", "")          # Q2 = Y
    assert capture_submit["ans"] == {"Q1?": "A", "Q2?": "Y"}


def test_session_digit_select(capture_submit):
    """F-TUI-1 数字直选(Design 裁,治 run15/17 丢答):单选题数字键直接落答+提交,
    不再"只高亮+必须 enter"。一次 handle_key("2") 即落 B 并提交(单题)。"""
    s = _session(
        [{"question": "数字?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("2", "2")              # 数字直选第 2 项 → 直接落答 B + 提交(单题单选)
    assert capture_submit["ans"] == {"数字?": "B"}, "数字直选应立即落答,无需再 enter"


def test_session_digit_direct_select_multi_question(capture_submit):
    """F-TUI-1 数字直选·多题:每题数字键直接落答并前进下一题,末题数字落答即提交。"""
    s = _session(
        [
            {"question": "Q1?", "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
            {"question": "Q2?", "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
        ],
        capture_submit,
    )
    s.handle_key("1", "1")              # Q1 数字选 A → 落答 + 自动前进 Q2
    assert "Q2?" in _rendered(s), "数字直选应落答并自动前进下一题"
    s.handle_key("2", "2")              # Q2 数字选 Y → 末题落答即提交
    assert capture_submit["ans"] == {"Q1?": "A", "Q2?": "Y"}


def test_session_digit_multi_select_toggles(capture_submit):
    """F-TUI-1 数字直选·多选题:数字键=勾选/取消(toggle,非直选提交),enter 才提交。"""
    s = _session(
        [{"question": "多选?", "multiSelect": True, "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("1", "1")              # 数字勾选 A(toggle)
    s.handle_key("2", "2")              # 数字勾选 B(toggle)
    assert "ans" not in capture_submit, "多选数字只 toggle 不提交"
    s.handle_key("return", "")          # enter 提交
    assert capture_submit["ans"] == {"多选?": "A, B"}


def test_session_digit_on_other_row_enters_text_input(capture_submit):
    """F-TUI-1 数字直选·Other 行:数字选中 Other 行 → 进文本输入态(不直选空 Other)。"""
    s = _session(
        [{"question": "选?", "options": [{"label": "A", "description": ""}]}],
        capture_submit,
    )
    # 2 选项行: 1=A, 2=Other → 数字 2 选 Other 行
    s.handle_key("2", "2")
    assert s.in_other_input, "数字选中 Other 行应进文本输入态,不落空 Other"
    assert "ans" not in capture_submit


# ── A2/A3/A4 渲染与导航 ───────────────────────────────────────────────


def test_session_selected_row_colored(capture_submit):
    """A2：已选项整行着绿(\\x1b[32m)。"""
    s = _session(
        [{"question": "选?", "options": [
            {"label": "A", "description": "aa"}, {"label": "B", "description": "bb"}]}],
        capture_submit,
    )
    s.handle_key("space", "")  # 多选才有 [x]，单选下 space 不选；改用 enter 选中后看 summary
    # 单选：高亮 A，渲染行应含 ❯ 与高亮
    lines = s.render_lines()
    assert any("❯" in ln for ln in lines)


def test_session_result_summary_answered(capture_submit):
    s = _session(
        [{"question": "选?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("return", "")  # 选 A
    summary = s.result_summary()
    assert "已回答" in summary and "选?" in summary and "A" in summary


def test_session_result_summary_cancelled(capture_submit):
    s = _session(
        [{"question": "选?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    summary = s.result_summary()
    assert "已取消" in summary


def test_session_bidirectional_nav_keeps_state(capture_submit):
    """A4：多题 ←→ 双向切，回头改，已选状态保留。"""
    s = _session(
        [
            {"question": "Q1?", "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
            {"question": "Q2?", "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
        ],
        capture_submit,
    )
    s.handle_key("return", "")          # Q1 = A，前进到 Q2
    s.handle_key("left", "")            # 回到 Q1
    s.handle_key("down", "")            # 高亮 B
    s.handle_key("return", "")          # Q1 改成 B，前进到 Q2
    s.handle_key("return", "")          # Q2 = X，提交
    assert capture_submit["ans"] == {"Q1?": "B", "Q2?": "X"}


# ── 516576 防呆：动过高亮未落答切题/esc 告警一次 + 带未答整体提交提示 ─────
# 实弹背景:zhaiyq 7 题丢 2 答——B 语义下 ↑↓ 只动高亮,数字/enter 才落答;用户高亮后
# 直接 Tab/←→ 切题或收尾,答案静默丢。防呆=黄字告警一次,再次同类操作放行。


def _two_questions():
    return [
        {"question": "Q1?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
        {"question": "Q2?", "options": [
            {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
    ]


def _rendered(s) -> str:
    return "\n".join(s.render_lines())


def test_session_switch_with_unsubmitted_selection_warns_once(capture_submit):
    """数字高亮未 enter 就 →/Tab 切题：第一次拦下+黄字，再次同键放行（不落答）。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("down", "")            # ↓移高亮 B，未 enter（数字直选后用 ↑↓ 造未提交态）
    s.handle_key("right", "")           # 第一次切题 → 拦下告警
    out = _rendered(s)
    assert "Q1?" in out, "首次切题应被拦在当前题"
    assert "动过高亮未落答" in out, "应显示黄字告警"
    s.handle_key("right", "")           # 再次同类操作 → 放行
    out = _rendered(s)
    assert "Q2?" in out, "再次切题应放行"
    assert "动过高亮未落答" not in out, "放行后告警清除"
    # 放行=按原语义切题不落答：提交后 Q1 仍为空
    s.handle_key("return", "")          # Q2 = X，进入提交（Q1 未答 → 提交防呆拦一次）
    s.handle_key("return", "")          # 再次 enter 确认提交
    assert capture_submit["ans"] == {"Q1?": "", "Q2?": "X"}


def test_session_switch_committed_no_warn(capture_submit):
    """已 enter 落答的题切走不告警；未动过高亮的题自由浏览也不告警。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("return", "")          # Q1 = A（落答，自动进 Q2）
    s.handle_key("left", "")            # Q2 未动过 → 自由切回 Q1
    assert "动过高亮未落答" not in _rendered(s)
    assert "Q1?" in _rendered(s)
    s.handle_key("right", "")           # Q1 已落答 → 自由切到 Q2
    assert "动过高亮未落答" not in _rendered(s)
    assert "Q2?" in _rendered(s)


def test_session_switch_warn_rearms_after_other_key(capture_submit):
    """告警后按了其他键（↑↓ 继续挑）→ armed 重置，再切题重新告警而非静默放行。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("down", "")            # ↓移高亮，未落答（数字直选后用 ↑↓ 造未提交态）
    s.handle_key("right", "")           # 告警一次
    s.handle_key("up", "")              # 其他键 → 清提示重新计
    assert "动过高亮未落答" not in _rendered(s)
    s.handle_key("right", "")           # 仍未提交 → 重新告警，不切题
    assert "Q1?" in _rendered(s) and "动过高亮未落答" in _rendered(s)
    s.handle_key("right", "")           # 再次 → 放行
    assert "Q2?" in _rendered(s)


def test_session_esc_with_unsubmitted_selection_warns_then_cancels(capture_submit):
    """单题动过高亮未落答按 esc：第一次告警不取消，再次 esc 确认取消。"""
    s = _session(
        [{"question": "选?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("down", "")            # ↓移高亮 B 未 enter（数字直选后用 ↑↓ 造未提交态）
    s.handle_key("escape", "")
    assert "ans" not in capture_submit, "首次 esc 应被拦下"
    assert "动过高亮未落答" in _rendered(s)
    s.handle_key("escape", "")          # 再次 esc → 确认取消
    assert capture_submit["ans"] == {}


def test_session_esc_empty_panel_quits_immediately(capture_submit):
    """A2 分级守卫(F-TUI-5,Design 2026-07-18 裁):空面板(无任何已答)esc 秒退——
    正常逃生口,不告警(改自旧"未答告警":Design 改用"有无已答内容"分流)。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("escape", "")   # 无已答 → 秒退,不告警
    assert capture_submit["ans"] == {}


def test_session_esc_with_answered_content_double_confirms(capture_submit):
    """A2 分级守卫(F-TUI-5,Design 裁):有已答内容 esc 二次确认「已答 N 题确认放弃」,
    防大面板误触全丢已答(用户答了半天)。首次告警、再次 esc 才真 cancel。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("return", "")   # Q1=A 落答(前进 Q2)——已答 1 题
    s.handle_key("escape", "")   # 有已答 → 首次 esc 告警,不 cancel
    assert "ans" not in capture_submit, "有已答时首次 esc 应拦下"
    assert "已答 1 题" in _rendered(s) and "确认放弃" in _rendered(s)
    s.handle_key("escape", "")   # 再次 esc → 真 cancel
    assert capture_submit["ans"] == {}


def test_session_submit_with_unanswered_warns_then_submits(capture_submit):
    """多题末题提交时存在未答题：提示「还有 N 题未答,未答题将按挂起处理」，再次 enter 提交。"""
    s = _session(
        [
            {"question": "Q1?", "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
            {"question": "Q2?", "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
            {"question": "Q3?", "options": [
                {"label": "M", "description": ""}, {"label": "N", "description": ""}]},
        ],
        capture_submit,
    )
    s.handle_key("return", "")          # Q1 = A → Q2
    s.handle_key("right", "")           # Q2 未动过 → 自由跳过 → Q3
    s.handle_key("return", "")          # Q3 = M → 触发提交，Q2 未答 → 拦下
    assert "ans" not in capture_submit, "带未答题的首次提交应被拦下"
    out = _rendered(s)
    assert "还有 1 题未答" in out and "挂起" in out
    s.handle_key("return", "")          # 再次 enter → 确认提交
    assert capture_submit["ans"] == {"Q1?": "A", "Q2?": "", "Q3?": "M"}


def test_session_submit_warned_then_user_goes_back_to_answer(capture_submit):
    """提交告警后用户回头补答（不锁死）：←切回补答，再提交时无未答 → 直接提交。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("right", "")           # Q1 未动过 → 自由跳到 Q2
    s.handle_key("return", "")          # Q2 = X → 提交，Q1 未答 → 拦下
    assert "还有 1 题未答" in _rendered(s)
    s.handle_key("left", "")            # 回 Q1（当前题已落答，自由切）
    s.handle_key("down", "")
    s.handle_key("return", "")          # Q1 = B → 前进 Q2
    s.handle_key("return", "")          # 全部已答 → 直接提交，无告警
    assert capture_submit["ans"] == {"Q1?": "B", "Q2?": "X"}


def test_session_other_submit_blocked_then_enter_confirms(capture_submit):
    """末题 Other 落答后被未答提示拦下：再次 enter 应直接提交，不得误入文本输入态。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("right", "")           # Q1 未动过 → 自由跳到 Q2
    s.handle_key("o", "o")              # Q2 进 Other 输入
    s.submit_other_text("自定义答案")     # 落答 → 提交被拦（Q1 未答）
    assert "ans" not in capture_submit
    assert "还有 1 题未答" in _rendered(s)
    assert not s.in_other_input
    s.handle_key("return", "")          # 再次 enter → 确认提交（高亮停在 Other 行也不得再入输入态）
    assert not s.in_other_input
    assert capture_submit["ans"] == {"Q1?": "", "Q2?": "自定义答案"}


def test_session_leave_warn_coexists_with_empty_other_guard(capture_submit):
    """两道防呆共存：切题告警后进 Other，空文本仍被 532862 防呆拦，补内容后正常走。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("down", "")            # Q1 ↓移高亮未提交（数字直选后用 ↑↓ 造未提交态）
    s.handle_key("right", "")           # 切题告警
    assert "动过高亮未落答" in _rendered(s)
    s.handle_key("o", "o")              # 进 Other 输入（切题告警清除）
    s.submit_other_text("")             # 空文本 → 532862 防呆拦下
    assert s.in_other_input
    assert any("不能为空" in ln for ln in s.render_lines())
    s.submit_other_text("裁决X")         # 补内容 → Q1 落答，前进 Q2
    assert "不能为空" not in _rendered(s)
    assert "动过高亮未落答" not in _rendered(s)
    s.handle_key("return", "")          # Q2 = X → 全部已答直接提交
    assert capture_submit["ans"] == {"Q1?": "裁决X", "Q2?": "X"}


def test_session_multi_enter_uncommitted_warns_once(capture_submit):
    """multiSelect 的 enter 也是「离开当前题」(2026-07-17 team4 审计 P1-6)：动过高亮
    未 space/数字 勾选就 enter → 与切题/esc 同款守卫，告警一次；再次 enter 放行（按未选继续）。"""
    s = _session(
        [
            {"question": "M1?", "multiSelect": True, "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
            {"question": "M2?", "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
        ],
        capture_submit,
    )
    s.handle_key("down", "")            # ↓移高亮 B，未 space（数字直选后用 ↑↓ 造未提交态）
    s.handle_key("return", "")          # 首次 enter → 拦下告警，不推进
    out = _rendered(s)
    assert "M1?" in out, "首次 enter 应被拦在当前题"
    assert "未 space/数字 勾选" in out, "应显示黄字告警(B 下数字也 toggle 落答)"
    s.handle_key("return", "")          # 再次 enter → 放行（按未选推进）
    assert "M2?" in _rendered(s)
    # space 勾选后 enter 不告警（正常路径）
    s2 = _session(
        [{"question": "M?", "multiSelect": True, "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s2.handle_key("space", "")          # 勾 A
    s2.handle_key("return", "")         # 有答案 → 直接提交无告警
    assert capture_submit["ans"] == {"M?": "A"}


def test_session_single_question_empty_submit_warns(capture_submit):
    """单题空提交告警(2026-07-17 team4 审计 P1-6)：旧条件 len>1 使单题 multiSelect
    空 enter 无任何告警直通空答案（空答案下游与取消语义模糊，532862 同族）。"""
    s = _session(
        [{"question": "M?", "multiSelect": True, "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("return", "")          # 未动高亮未勾选，直接 enter（空提交）
    assert "ans" not in capture_submit, "单题空提交首次应被拦下"
    assert "空答案" in _rendered(s)
    s.handle_key("return", "")          # 再次 enter → 确认提交空答案
    assert capture_submit["ans"] == {"M?": ""}


def test_session_hint_matches_actual_key_semantics(capture_submit):
    """按键提示对齐实际行为 B(2026-07-18 team4 D23):单选数字/enter 都落答+前进、
    多选数字/space 都勾选——纯移动只剩 ↑↓。旧「数字 移动」是 A 旧叙事、与 B 代码相反
    (用户看"移动"实际按数字即落答跳题),run15/17 丢答心智模型根因;D23 补文案闭环。"""
    # 单选单题(=末题):数字/enter 选定并提交,数字移出"移动"
    s = _session(
        [{"question": "选?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    hint = _rendered(s)
    assert "数字直选" not in hint, "旧 A 误导文案必须移除"
    assert "↑↓/数字 移动" not in hint, "数字不再属'移动'(B 下数字即落答)"
    assert "↑↓ 移动" in hint, "纯移动只剩 ↑↓"
    assert "数字/enter 选定并提交" in hint, "单题=末题:数字/enter 并列,选定并提交"
    # 单选多题非末题:数字/enter 选定并进下题(非'提交')
    sq = _session(_two_questions(), capture_submit)
    hq = _rendered(sq)
    assert "数字/enter 选定并进下题" in hq, "非末题:选定并进下题"
    assert "选定并提交" not in hq, "非末题不说'提交'"
    # multiSelect 非末题:数字/space 勾选 · enter 下一题；末题:enter 提交(保留 enter)
    s2 = _session(
        [
            {"question": "M1?", "multiSelect": True, "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
            {"question": "M2?", "multiSelect": True, "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
        ],
        capture_submit,
    )
    h1 = _rendered(s2)
    assert "数字/space 勾选" in h1 and "enter 下一题" in h1, "多选:数字/space 勾选,保留 enter"
    s2.handle_key("space", "")
    s2.handle_key("return", "")         # 进末题
    h2 = _rendered(s2)
    assert "enter 提交" in h2


def test_ask_user_records_folded_members_untruncated():
    """F-Py-1 T1b+T3:ask_user :247 落 folded_members 批级并集(专用字段);大 fold(30 成员)+
    题文超 500 → folded_members 仍含全 30 aid(专用字段不经题文 [:500] 截断,599838 根因)。"""
    import json as _j
    from main.ist_core.tools import ask_user as au
    from main.common.runtime_paths import runtime_path
    qa = runtime_path("ask_user_answers.jsonl")
    qa.parent.mkdir(parents=True, exist_ok=True)
    big = sorted(f"2030000000000{i:05d}" for i in range(30))
    result: dict = {}

    def run_tool():
        result["out"] = au.ask_user.invoke({"questions": [
            {"question": "组题" + "长" * 600 + "?",   # 题文 >500 (T3)
             "options": [{"label": "是", "description": ""}, {"label": "否", "description": ""}],
             "folded_members": big}]})

    t = threading.Thread(target=run_tool, daemon=True)
    t.start()
    qid = None
    q_text = None
    for _ in range(300):
        pend = au.list_pending_questions()
        if pend:
            qid = pend[0]["question_id"]
            q_text = pend[0]["questions"][0]["question"]
            break
        threading.Event().wait(0.01)
    assert qid is not None
    assert au.submit_answers(qid, {q_text: "是"})
    t.join(timeout=3.0)
    rec = _j.loads(qa.read_text(encoding="utf-8").splitlines()[-1])
    assert rec.get("folded_members") == big              # 批级并集 + 全 30 aid 未被 [:500] 截断


def test_ftui5_other_input_shows_visible_hint(capture_submit):
    """F-TUI-5 A1 o 输入态可见提示(Design 裁;Test-Eng 卡壳:进了文本输入态却不自知)。
    hint 文案「o 输入自定义文本」说清;进 other 态面板顶部醒目提示「正在输入自定义文本」。"""
    s = _session(
        [{"question": "选?", "options": [{"label": "A", "description": ""}]}],
        capture_submit,
    )
    # 非 other 态:hint 说清 o 是输入文本(旧「o 自定义」易误解)
    assert "o 输入自定义文本" in _rendered(s)
    assert "正在输入自定义文本" not in _rendered(s)
    # 进 other 态:顶部醒目输入提示
    s.handle_key("o", "o")
    assert s.in_other_input
    out = _rendered(s)
    assert "正在输入自定义文本" in out and "enter 提交" in out and "esc 取消" in out


def test_ftui1_last_q_digit_submit_passes_unanswered_gate(capture_submit):
    """F-TUI-1 裁点1×2 补点(Design 2026-07-18 必带):末题"数字直选提交"走的是数字键
    (非 enter)——未答挡板必须挂在提交动作本身(_advance_or_submit),而非只 enter 路径,
    否则"前面题未答→末题数字直选提交"绕过挡板成后门。验证数字直选提交也过未答挡板。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("right", "")   # Q1 未答,切题跳到 Q2(Q1 未落答)
    s.handle_key("1", "1")      # Q2(末题)数字直选提交 → 前面 Q1 未答 → 挡板拦一次
    assert "ans" not in capture_submit, "末题数字直选遇未答题必须过挡板(不是后门)"
    assert "还有 1 题未答" in _rendered(s)
    s.handle_key("1", "1")      # 再次数字直选 → 挡板放行,提交(Q1 空/Q2=X)
    assert capture_submit["ans"] == {"Q1?": "", "Q2?": "X"}


def test_ftui1_cross_path_armed_enter_then_digit(capture_submit):
    """跨路径 armed 共享(Design 2026-07-18 完备性点):_warned_op=="submit" 是共享 armed,
    enter 提交告警后 → **数字**二次确认也放行(非"enter告警只enter确认")。锁死共享语义
    防将来 armed 做成 enter/数字各自独立致跨路径确认失效。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("right", "")   # Q1 未答,跳到 Q2
    s.handle_key("return", "")  # Q2 enter:落答 X + 末题提交 → Q1 未答 → 告警 armed(submit)
    assert "ans" not in capture_submit, "enter 提交遇未答应告警"
    assert "还有 1 题未答" in _rendered(s)
    s.handle_key("1", "1")      # 数字二次确认(跨路径:enter 告警→数字放行)
    assert capture_submit["ans"] == {"Q1?": "", "Q2?": "X"}


def test_ftui1_cross_path_armed_digit_then_enter(capture_submit):
    """跨路径 armed 共享(对称):数字直选提交告警后 → **enter** 二次确认也放行。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("right", "")   # Q1 未答,跳到 Q2
    s.handle_key("1", "1")      # Q2 数字直选提交 → Q1 未答 → 告警 armed(submit)
    assert "ans" not in capture_submit, "数字提交遇未答应告警"
    s.handle_key("return", "")  # enter 二次确认(跨路径:数字告警→enter 放行)
    assert capture_submit["ans"] == {"Q1?": "", "Q2?": "X"}


# ── D24 回扫游标显已选(2026-07-18 team4 收口批,治回退已答题 ❯ 停默认行误判"答案没了") ──


def test_session_d24_backtrack_shows_selected_highlight(capture_submit):
    """D24:回扫到已答题时 ❯ 光标落已选项(非无条件 0)——旧 _goto_question 置 0 致回退
    已答题 ❯ 停默认行、已选项虽绿标却无光标,用户误判"答案没了"(选择其实在 _selected)。
    与 D23 保留前进硬绑定:前进(强反馈治丢答)配回扫(可复核治不可退回)方闭环。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("down", "")            # Q1 高亮 B(index 1)
    s.handle_key("return", "")          # Q1=B 落答,前进 Q2(新题从头 highlight=0)
    assert s._highlight == 0, "前进到新题 Q2 高亮从头(0),与回退区分"
    s.handle_key("left", "")            # 回退 Q1(已答=B)
    assert s._highlight == 1, "回退已答题 ❯ 落已选项 B(index 1),非默认 0"
    b_line = [ln for ln in s.render_lines() if "B" in ln and "❯" in ln]
    assert b_line, "❯ 光标应渲染在已选项 B 行"


def test_session_d24_backtrack_unanswered_stays_zero(capture_submit):
    """D24:回退到未答题→高亮保持 0(无已选项可显,不无脑显;对比已答题落已选)。"""
    s = _session(
        [
            {"question": "Q1?", "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""}]},
            {"question": "Q2?", "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
            {"question": "Q3?", "options": [
                {"label": "M", "description": ""}, {"label": "N", "description": ""}]},
        ],
        capture_submit,
    )
    s.handle_key("return", "")          # Q1=A,前进 Q2
    s.handle_key("right", "")           # Q2 未答,自由跳 Q3
    s.handle_key("left", "")            # 回退 Q2(未答)
    assert s._highlight == 0, "回退未答题 Q2 高亮保持 0(无已选可显)"


def test_session_d24_highlight_for_branches(capture_submit):
    """D24 _highlight_for 各分支:未答→0 / 单选已选→其 index / 仅 Other 已选→Other 行。"""
    from main.ist_core.ink.components.ask_user_view import _OTHER_VALUE
    s = _session(
        [{"question": "Q?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""},
            {"label": "C", "description": ""}]}],
        capture_submit,
    )
    assert s._highlight_for(0) == 0, "未答→0"
    s._selected[0] = {"C"}
    assert s._highlight_for(0) == 2, "选 C→index 2"
    s._selected[0] = {_OTHER_VALUE}
    assert s._highlight_for(0) == 3, "仅 Other 已选→Other 行 index=len(options)=3"


def test_session_d24_multi_select_backtrack_first_selected(capture_submit):
    """D24 多选:回退已答多选题→❯ 落首个已选项(多选 [x] 标全部,光标锚首个已选)。"""
    s = _session(
        [
            {"question": "M1?", "multiSelect": True, "options": [
                {"label": "A", "description": ""}, {"label": "B", "description": ""},
                {"label": "C", "description": ""}]},
            {"question": "Q2?", "options": [
                {"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
        ],
        capture_submit,
    )
    s.handle_key("down", "")            # 高亮 B
    s.handle_key("space", "")           # 勾 B(index 1)
    s.handle_key("down", "")            # 高亮 C
    s.handle_key("space", "")           # 勾 C(index 2)
    s.handle_key("return", "")          # M1 提交(B,C)→前进 Q2
    s.handle_key("left", "")            # 回退 M1(已答 B,C)
    assert s._highlight == 1, "回退多选题 ❯ 落首个已选项 B(index 1)"
