"""问询路由两向校准(§16.6,run17 实弹回归)。

run17@79 实录:9 挂起案 3 题问询只答 1(TUI 面板部分提交,(41)④)——668044 resumed
产生可推进工作,却被旧边「有任何未答题即 closing」直接收口,零复跑交付;而对称方向,
若把 n_failed 简单前置于 ask,封顶/env/bed 待问案会让 merge 空转、cap 资源问询被跳过
(违 §11.7 引擎无单方终结权)。修:actionable=失败∧不在问询等待集;closing 仅限
真·未获答(本轮零实答)。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8.graph import (
    _after_ask_contradiction, _after_author,
)


# ── _after_ask_contradiction:部分作答不吞已答案子 ────────────────────────────

def test_partial_answer_routes_to_work_not_closing():
    """run17 形态:3 题答 1(668044 resumed→可推进),8 题未答仍在等待集。"""
    s = {"ask_answers_consumed": 1, "n_ask_contradiction": 8,
         "n_failed_actionable": 1, "n_authored": 0, "n_subset_verified": 0}
    assert _after_ask_contradiction(s) == "attribute"


def test_zero_answer_still_closes():
    """真·未获答(非交互/面板取消):禁空转卫兵语义保留。"""
    s = {"ask_answers_consumed": 0, "n_ask_contradiction": 8,
         "n_failed_actionable": 1, "n_authored": 0, "n_subset_verified": 0}
    assert _after_ask_contradiction(s) == "closing"


def test_all_answers_suspend_closes_honestly():
    """答了但全为挂起/降级(无可推进工作、欠定=0)→ 如实收口交付。"""
    s = {"ask_answers_consumed": 3, "n_ask_contradiction": 0,
         "n_failed_actionable": 0, "n_authored": 0, "n_subset_verified": 0,
         "n_awaiting_user": 0}
    assert _after_ask_contradiction(s) == "closing"


def test_answered_authored_goes_merge():
    s = {"ask_answers_consumed": 2, "n_ask_contradiction": 1,
         "n_failed_actionable": 0, "n_authored": 1, "n_subset_verified": 0}
    assert _after_ask_contradiction(s) == "merge"


# ── _after_author:处方复跑先于 ask,但等待案不算"有活" ────────────────────────

def test_author_rerun_prescription_reaches_merge_before_ask():
    """resumed 复活案(rerun 处方,不在等待集)必达 merge——不被未答题截回问询。"""
    s = {"n_authored": 0, "n_subset_verified": 0,
         "n_failed_actionable": 1, "n_ask_contradiction": 8}
    assert _after_author(s) == "merge"


def test_author_cap_waiting_still_asks():
    """封顶案在等待集内(actionable=0)→ cap 资源问询必须发生(§11.7),不被 merge 空转跳过。"""
    s = {"n_authored": 0, "n_subset_verified": 0,
         "n_failed_actionable": 0, "n_ask_contradiction": 1}
    assert _after_author(s) == "ask_contradiction"


def test_author_authored_first():
    s = {"n_authored": 2, "n_subset_verified": 0,
         "n_failed_actionable": 1, "n_ask_contradiction": 3}
    assert _after_author(s) == "merge"


# ── counts:n_failed_actionable 剔除问询等待案 ────────────────────────────────

def test_counts_failed_actionable_excludes_waiting(tmp_path, monkeypatch):
    from main.ist_core.compile_engine_v8 import _shared as sh
    from main.ist_core.compile_engine_v8 import views as V

    A_RERUN, A_CAP = "203600000000000201", "203600000000000202"
    fs = [
        # 两案都 failed:A_RERUN 无任何待问;A_CAP 有 cap_reached 且未答
        {"ev": "authored", "aid": A_RERUN, "round": 1, "artifact": "a1"},
        {"ev": "verdict", "aid": A_RERUN, "result": "fail", "run_id": "r1",
         "ctx": "subset", "artifact": "a1", "volume": "v1", "signatures": []},
        {"ev": "attribution", "aid": A_RERUN, "layer": "E",
         "disposition": "rerun_isolated", "round": 1, "run_id": "r1"},
        {"ev": "authored", "aid": A_CAP, "round": 1, "artifact": "a1"},
        {"ev": "verdict", "aid": A_CAP, "result": "fail", "run_id": "r1",
         "ctx": "subset", "artifact": "a1", "volume": "v1", "signatures": []},
        {"ev": "attribution", "aid": A_CAP, "layer": "V",
         "disposition": "reflow", "round": 1, "run_id": "r1"},
        {"ev": "cap_reached", "aid": A_CAP, "round": 3},
    ]
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [
        {"autoid": A_RERUN, "title": "t"}, {"autoid": A_CAP, "title": "t"}]})
    monkeypatch.setattr(sh, "load_facts", lambda s: fs)
    c = sh.counts_update({}, fs)
    assert c["n_failed"] == 2
    assert c["n_failed_actionable"] == 1          # A_CAP 在 cap 等待集内,不算可推进
    assert c["n_ask_contradiction"] >= 1          # cap 问询在等待集


# ── H-03:cap_waiting 与 panel/env 同款 settled 排除 ───────────────────────────

def test_cap_waiting_excludes_settled_H03(tmp_path, monkeypatch):
    """H-03:cap_reached 案已是终态(user_stop)/挂起/升级时不再出 cap 题——旧实现
    不看 vw:用户另题答 stop 落 user_stop 终态后 cap_waiting 仍每批命中出 cap 题,
    非交互 auto-suspend 再落 suspended → failed_terminal 被翻成 suspended,
    用户止损终局被安全件静默推翻。"""
    from main.ist_core.compile_engine_v8 import _shared as sh
    A1, A2, A3, A4 = ("203600000000000301", "203600000000000302",
                      "203600000000000303", "203600000000000304")
    fs = ([{"ev": "cap_reached", "aid": a, "round": 3} for a in (A1, A2, A3, A4)]
          + [{"ev": "attribution", "aid": A2, "round": 99, "layer": "user",
              "disposition": "user_stop"},                     # A2 终态
             {"ev": "suspended", "aid": A3, "reason": "q"},      # A3 挂起
             # A4 升级(带一条非「保持」的 deesc 裁决——不进 deesc 待答投影,
             # vw 状态才是 S_ESCALATED 而非 awaiting_user)
             {"ev": "escalated", "aid": A4, "reason": "x", "subclass": "no_output"},
             {"ev": "decision", "aid": A4, "question_id": f"deesc:{A4}:1",
              "answer": "换床复跑", "token": "deesc_reswitch"}])
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [
        {"autoid": a} for a in (A1, A2, A3, A4)]})
    monkeypatch.setattr(sh, "load_facts", lambda s: fs)
    vw = sh.view({}, fs)
    assert sh.cap_waiting(fs, vw) == [A1]      # 仅未 settled 的 A1 待授权
    assert sh.ask_targets({}, fs, vw)["cap"] == [A1]
    # 对照(防过修):终态案的 cap_reached 不再进 ask 等待集 → 不占 n_ask_contradiction
    assert sh.counts_update({}, fs)["n_ask_contradiction"] == 1
