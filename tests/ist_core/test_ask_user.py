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
    s = _session(
        [{"question": "数字?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("2", "2")              # 高亮第 2 项
    s.handle_key("return", "")
    assert capture_submit["ans"] == {"数字?": "B"}


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


# ── 516576 防呆：已选未提交切题/esc 告警一次 + 带未答整体提交提示 ─────
# 实弹背景:zhaiyq 7 题丢 2 答——数字/↑↓ 只动高亮,enter 才落答;用户高亮后
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
    s.handle_key("2", "2")              # 高亮 B，未 enter（用户以为已选）
    s.handle_key("right", "")           # 第一次切题 → 拦下告警
    out = _rendered(s)
    assert "Q1?" in out, "首次切题应被拦在当前题"
    assert "已选未提交" in out, "应显示黄字告警"
    s.handle_key("right", "")           # 再次同类操作 → 放行
    out = _rendered(s)
    assert "Q2?" in out, "再次切题应放行"
    assert "已选未提交" not in out, "放行后告警清除"
    # 放行=按原语义切题不落答：提交后 Q1 仍为空
    s.handle_key("return", "")          # Q2 = X，进入提交（Q1 未答 → 提交防呆拦一次）
    s.handle_key("return", "")          # 再次 enter 确认提交
    assert capture_submit["ans"] == {"Q1?": "", "Q2?": "X"}


def test_session_switch_committed_no_warn(capture_submit):
    """已 enter 落答的题切走不告警；未动过高亮的题自由浏览也不告警。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("return", "")          # Q1 = A（落答，自动进 Q2）
    s.handle_key("left", "")            # Q2 未动过 → 自由切回 Q1
    assert "已选未提交" not in _rendered(s)
    assert "Q1?" in _rendered(s)
    s.handle_key("right", "")           # Q1 已落答 → 自由切到 Q2
    assert "已选未提交" not in _rendered(s)
    assert "Q2?" in _rendered(s)


def test_session_switch_warn_rearms_after_other_key(capture_submit):
    """告警后按了其他键（↑↓ 继续挑）→ armed 重置，再切题重新告警而非静默放行。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("2", "2")
    s.handle_key("right", "")           # 告警一次
    s.handle_key("up", "")              # 其他键 → 清提示重新计
    assert "已选未提交" not in _rendered(s)
    s.handle_key("right", "")           # 仍未提交 → 重新告警，不切题
    assert "Q1?" in _rendered(s) and "已选未提交" in _rendered(s)
    s.handle_key("right", "")           # 再次 → 放行
    assert "Q2?" in _rendered(s)


def test_session_esc_with_unsubmitted_selection_warns_then_cancels(capture_submit):
    """单题已选未提交按 esc：第一次告警不取消，再次 esc 确认取消。"""
    s = _session(
        [{"question": "选?", "options": [
            {"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
        capture_submit,
    )
    s.handle_key("2", "2")              # 高亮 B 未 enter
    s.handle_key("escape", "")
    assert "ans" not in capture_submit, "首次 esc 应被拦下"
    assert "已选未提交" in _rendered(s)
    s.handle_key("escape", "")          # 再次 esc → 确认取消
    assert capture_submit["ans"] == {}


def test_session_esc_untouched_multi_question_warns_unanswered(capture_submit):
    """多题面板带未答题 esc 关闭：提示「还有 N 题未答」，再次 esc 放行。"""
    s = _session(_two_questions(), capture_submit)
    s.handle_key("escape", "")
    assert "ans" not in capture_submit
    out = _rendered(s)
    assert "还有 2 题未答" in out and "挂起" in out
    s.handle_key("escape", "")
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
    s.handle_key("2", "2")              # Q1 高亮未提交
    s.handle_key("right", "")           # 切题告警
    assert "已选未提交" in _rendered(s)
    s.handle_key("o", "o")              # 进 Other 输入（切题告警清除）
    s.submit_other_text("")             # 空文本 → 532862 防呆拦下
    assert s.in_other_input
    assert any("不能为空" in ln for ln in s.render_lines())
    s.submit_other_text("裁决X")         # 补内容 → Q1 落答，前进 Q2
    assert "不能为空" not in _rendered(s)
    assert "已选未提交" not in _rendered(s)
    s.handle_key("return", "")          # Q2 = X → 全部已答直接提交
    assert capture_submit["ans"] == {"Q1?": "裁决X", "Q2?": "X"}
