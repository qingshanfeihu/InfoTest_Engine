# -*- coding: utf-8 -*-
"""V8.5 片4:修法导出队列+选项约束+R5 两布尔(DESIGN §16.2-D/E,原 D 片)。

§11.7:队列非空禁 ask(路由既有行为的显式化);题面携已试修法;报告队列头=
唯一导出修法陈述句;decision/decision_outcome 携 R5 质量布尔。
"""
from __future__ import annotations

import json
import time

from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.compile_engine_v8.remedies import derive_queue, tried_actions

from tests.ist_core.compile_engine_v8.test_graph_scenarios import (  # noqa: F401
    AIDS, FakeDevice, rig, _run_graph, _report)

AID = AIDS[0]


def _vw(status: str) -> dict:
    return {"cases": {AID: {"status": status, "rounds": 1, "contradictions": 0}}}


def _att(disp: str, layer: str = "V", rnd: int = 1) -> dict:
    return {"ev": "attribution", "aid": AID, "layer": layer, "disposition": disp,
            "round": rnd, "fix_direction": "adjust expectation to captured relation"}


def _authored(rnd: int) -> dict:
    return {"ev": "authored", "aid": AID, "round": rnd, "artifact": f"a{rnd}"}


# ------------------------------------------------------------- 队列判定链单元
def test_queue_reflow_gives_recompile():
    fs = [_authored(1), _att("reflow")]
    q = derive_queue(fs, _vw(V.S_FAILED), AID)
    assert [x["action"] for x in q] == ["recompile_directed"]
    assert "captured relation" in q[0]["direction"]


def test_queue_frozen_appends_vary_form():
    fs = [_authored(1), _authored(2), _att("frozen")]
    q = derive_queue(fs, _vw(V.S_FAILED), AID)
    assert [x["action"] for x in q] == ["recompile_directed", "vary_form"]


def test_queue_rerun_non_s0():
    fs = [_authored(1), _att("rerun_isolated", layer="transient")]
    q = derive_queue(fs, _vw(V.S_FAILED), AID)
    assert [x["action"] for x in q] == ["rerun_isolated"]


def test_queue_s0_empty_ask_legal():
    """s₀:床治理在引擎权限外 → 案级队列空(bed 呈报合法,与片3复跑闸一致)。"""
    fs = [_authored(1), _att("rerun_isolated"),
          {"ev": "diagnosis", "aid": AID, "h_position": "h_s0", "polluters": []}]
    assert derive_queue(fs, _vw(V.S_FAILED), AID) == []


def test_queue_capped_empty_resource_ask_legal():
    fs = [_authored(1), _authored(2), _authored(3), _att("reflow", rnd=3)]
    assert derive_queue(fs, _vw(V.S_FAILED), AID, max_rounds=3) == []


def test_queue_env_blocked_empty():
    fs = [_authored(1), _att("env_blocked", layer="E")]
    assert derive_queue(fs, _vw(V.S_FAILED), AID) == []


def test_queue_terminal_states_empty():
    fs = [_authored(1), _att("reflow")]
    for st in (V.S_DELIVERABLE, V.S_TERMINAL, V.S_SUSPENDED, V.S_ESCALATED):
        assert derive_queue(fs, _vw(st), AID) == []


def test_tried_actions_chinese_summary():
    fs = [_authored(1), _authored(2), _authored(3),
          _att("rerun_isolated"),
          {"ev": "verdict", "aid": AID, "ctx": "subset", "result": "pass"},
          {"ev": "decision", "aid": AID, "token": "reorder", "answer": "重排复验"}]
    tried = tried_actions(fs, AID)
    assert "重编 2 次" in tried and "隔离复跑 1 次" in tried and "重排复验 1 次" in tried


# ------------------------------------------------------------- 题面携证明
def test_question_carries_tried_proof():
    from main.ist_core.compile_engine_v8.engine_tool import _contradiction_question
    q = _contradiction_question({"autoid": AID, "kind": "cap", "rounds": 3,
                                 "tried": ["重编 2 次", "隔离复跑 1 次"],
                                 "queue_empty": True})
    assert "引擎已试:重编 2 次、隔离复跑 1 次" in q["question"]


# ------------------------------------------------------------- e2e:报告与两布尔
def test_e2e_report_remedy_and_r5_booleans(rig):
    """668030 形态(片3场景)收口后:①未通过卷该案带修法/去向叙事;②decision 事实
    携 freeform 布尔,closing 回填 decision_outcome+report.totals.ask。"""
    from main.ist_core.compile_engine_v8 import nodes as N

    rows_by_aid = {
        # §18.12 三稿:write memory 框架清得掉不再判 s₀;换真跨案撞名(A 存 shared_save,
        # B 从同名 config 恢复)——s₀ 在新判据下仍真实成立,机制测试不变
        AIDS[0]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns listener 172.16.34.70\nwrite file shared_save"}],
        AIDS[1]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns on\nsdns listener 172.16.34.70\nconfig file shared_save"}],
    }
    rig["monkeypatch"].setattr(
        N, "_load_case_rows",
        lambda aid: rows_by_aid.get(aid, [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"}]))

    orig_fork = N._FORK_OVERRIDE

    def fork(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-attributor":
            # K1 并发纪律:假体读改写 last_run 必持真锁(裸写在并发池下有 write_text
            # 截断窗口,同伴读到空文件 JSONDecodeError——test_diagnose 同批修复)
            from main.ist_core.tools.device.fail_attribution import _LAST_RUN_LOCK
            lrp = rig["tmp"] / str(env.get("last_run_path"))
            with _LAST_RUN_LOCK:
                data = json.loads(lrp.read_text(encoding="utf-8"))
                for r in data:
                    if str(r.get("autoid")) == aid:
                        r["_attribution"] = {"layer": "V", "disposition": "rerun_isolated",
                                             "h_position": "h_pi",
                                             "evidence": f"echo for {aid} (fail)",
                                             "ts": time.time()}   # M-02 收账闸:真 tool 恒落 ts
                lrp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return "VERDICT"
        return orig_fork(skill, brief, tag=tag, effort=effort)

    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork)

    device = FakeDevice(
        lambda aid, ctx, n: "fail" if aid == AIDS[1] and ctx == "delivery" else "pass")

    def answer(payload):
        if payload.get("kind") == "ask_contradiction":
            # bed 面板:标准选项作答(非 freeform)
            return {it["autoid"]: {"answer": "如实降级", "token": "downgrade"}
                    for it in payload.get("cases", []) if it.get("kind") == "bed"} or \
                   {"__dismiss__": ""}
        return {"__dismiss__": ""}

    res, g, cfgd = _run_graph(rig, device, resume_answers=answer)
    rep = _report(rig)
    facts = [json.loads(l) for l in
             (rig["outputs"] / rig["out_name"] / "facts.jsonl").read_text(
                 encoding="utf-8").splitlines()]
    # decision 携 freeform=False(标准选项)
    decs = [f for f in facts if f.get("ev") == "decision" and f.get("aid") == AIDS[1]]
    assert decs and decs[-1]["token"] == "downgrade" and decs[-1]["freeform"] is False
    # decision_outcome 回填:如实降级=达成终局 → effective True
    ocs = [f for f in facts if f.get("ev") == "decision_outcome"
           and f.get("aid") == AIDS[1]]
    assert ocs and ocs[-1]["effective"] is True and ocs[-1]["freeform"] is False
    assert rep["totals"]["ask"]["answered"] >= 1
    assert rep["totals"]["ask"]["effective"] >= 1
    # 未通过卷叙事:s₀ 判断+按裁决收尾(渲染层消费诊断与裁决,非空话)
    umd = (rig["outputs"] / rig["out_name"] / "unsuccessful_cases.md").read_text(
        encoding="utf-8")
    assert "测试床状态残留" in umd and "如实降级" in umd
