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


# ── H-01:env qid decision-count——retry 后再堵可重问 ───────────────────────────

def test_env_reblock_after_retry_asks_again_H01(tmp_path, monkeypatch):
    """H-01 红绿:答 retry 后再判 env_blocked → 必须以新 qid 重问。
    旧 round 判别子:retry 不重编→round 不变→同 qid「已答」永不再问。"""
    from main.ist_core.compile_engine_v8 import _shared as sh
    A = "203600000000000401"
    fs = [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "verdict", "aid": A, "result": "broken", "broken_subtype": "blocked",
         "run_id": "r1", "ctx": "subset", "artifact": "a1", "volume": "v1",
         "signatures": []},
        {"ev": "attribution", "aid": A, "layer": "E", "disposition": "env_blocked",
         "round": 0, "run_id": "r1", "mechanical": True},
        {"ev": "decision", "aid": A, "question_id": f"env:{A}:1",
         "answer": "环境已恢复", "token": "retry"},
        {"ev": "attribution", "aid": A, "layer": "E", "disposition": "rerun_isolated",
         "round": 1, "run_id": "u1"},
        # 复跑后再堵——最新归因又是 env_blocked
        {"ev": "attribution", "aid": A, "layer": "E", "disposition": "env_blocked",
         "round": 1, "run_id": "r2", "mechanical": True},
    ]
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    vw = sh.view({}, fs)
    assert A in sh.env_confirm_waiting(fs, vw)
    assert sh.env_qid(A, fs) == f"env:{A}:2"   # 已有 1 条 env decision → 下一题 :2
    # 对照:第一次堵、尚未答 → 待问且 qid=:1
    assert A in sh.env_confirm_waiting(fs[:3], sh.view({}, fs[:3]))
    assert sh.env_qid(A, fs[:3]) == f"env:{A}:1"


def test_cap_suspend_then_resume_reasks_H09(tmp_path, monkeypatch):
    """H-09 红绿:cap 题答挂起占用旧 round-qid 后,resume 须再问(新 decision-count qid)。
    suspend 不消费资源问询;题面承诺「重跑同参数时会再次询问」。"""
    from main.ist_core.compile_engine_v8 import _shared as sh
    A = "203600000000000402"
    fs = [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "verdict", "aid": A, "result": "fail", "run_id": "r1",
         "ctx": "subset", "artifact": "a1", "volume": "v1", "signatures": []},
        {"ev": "attribution", "aid": A, "layer": "V", "disposition": "reflow",
         "round": 1, "run_id": "r1"},
        {"ev": "cap_reached", "aid": A, "round": 3},
        {"ev": "decision", "aid": A, "question_id": f"cap:{A}:1",
         "answer": "挂起", "token": "suspend"},
        {"ev": "suspended", "aid": A, "reason": f"auto:cap:{A}:1"},
        # resume 后不再 suspended
        {"ev": "decision", "aid": A, "question_id": f"resume:{A}:2",
         "answer": "恢复", "token": "resume"},
        {"ev": "resumed", "aid": A},
    ]
    monkeypatch.setattr(sh, "manifest", lambda s: {"cases": [{"autoid": A}]})
    vw = sh.view({}, fs)
    assert A in sh.cap_waiting(fs, vw)
    # 仅既有 cap: decision 计数(resume 题不占 cap 序号)→ 下一题 :2
    assert sh.cap_qid(A, [f for f in fs if str(f.get("aid")) == A]) == f"cap:{A}:2"
    # 对照:仍挂起时 H-03 排除
    fs_susp = fs[:6]
    assert A not in sh.cap_waiting(fs_susp, sh.view({}, fs_susp))
    # continue 解决态后不再问
    fs_ok = fs[:4] + [{"ev": "decision", "aid": A, "question_id": f"cap:{A}:1",
                       "answer": "继续", "token": "continue"}]
    assert A not in sh.cap_waiting(fs_ok, sh.view({}, fs_ok))
