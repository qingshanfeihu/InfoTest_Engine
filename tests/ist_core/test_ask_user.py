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
