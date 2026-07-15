# -*- coding: utf-8 -*-
"""V8.5 片2:suspend-and-continue + 批末 ask_gather(DESIGN §16.1/16.2-A/E)。

金标准形态:欠定案不阻塞兄弟案(§14-R4「山穷水尽才 ask、单案待人不得阻塞全批」),
其余案先跑到 delivery;全批无可推进工作时 ask_decision 聚合呈报;答题→复活→
子集重跑→composition 锚强制整卷重新终验(INV-8)。题面入账(run11 体检发现#6)。
"""
from __future__ import annotations

import json

from main.ist_core.compile_engine_v8.graph import (_after_author, _after_diagnose,
                                                   _after_merge, _after_reconcile,
                                                   _gather_or_close)

# 复用 rig/FakeDevice/_run_graph(场景测试基座)
from tests.ist_core.compile_engine_v8.test_graph_scenarios import (  # noqa: F401
    AIDS, FakeDevice, rig, _run_graph, _report)


# ------------------------------------------------------------- 路由单元(纯函数)
def test_author_prefers_work_over_ask():
    """有活先干活:欠定与已产卷并存 → merge,不阻塞。"""
    s = {"n_authored": 2, "n_awaiting_user": 3}
    assert _after_author(s) == "merge"


def test_author_gathers_only_when_nothing_actionable():
    assert _after_author({"n_awaiting_user": 3}) == "ask_decision"
    assert _after_author({}) == "closing"


def test_terminal_points_gather_when_pending():
    s = {"n_awaiting_user": 1}
    assert _gather_or_close(s) == "ask_decision"
    assert _gather_or_close({}) == "closing"
    assert _after_reconcile(s) == "ask_decision"          # 全 deliverable+欠定
    assert _after_diagnose(s) == "ask_decision"           # 全终局+欠定
    assert _after_merge({"phase_status": "nothing_to_merge",
                         "n_awaiting_user": 1}) == "ask_decision"


# ── 回归#2 修 B(设计):「批末必有聚合点」立为真不变量——所有到 closing 的 pre-ask
#    边(硬错误/停滞)有未答欠定必先经 gather,禁静默吞(§16 / §18.2 式③) ──
def test_flush_awaiting_user_before_error_and_stuck_closings():
    from main.ist_core.compile_engine_v8.graph import (_after_reconcile, _after_run,
                                                       _after_merge, _after_bed)
    s = {"n_awaiting_user": 1}
    # 有欠定:原本直接 closing 的硬错误/停滞边,现先 gather 呈报
    assert _after_reconcile({**s, "phase_status": "error"}) == "ask_decision"
    assert _after_run({**s, "phase_status": "error"}) == "ask_decision"
    assert _after_run({**s, "phase_status": "device_busy"}) == "ask_decision"
    assert _after_merge({**s, "phase_status": "error"}) == "ask_decision"
    assert _after_bed({**s, "phase_status": "bed_blocked"}) == "ask_decision"
    from main.ist_core.compile_engine_v8.graph import (_after_prep,
                                                       _after_ask_contradiction)
    assert _after_prep({**s, "phase_status": "error"}) == "ask_decision"
    # ask_contradiction 零实答:不同面板,flush needs_decision(不 ping-pong)
    assert _after_ask_contradiction({**s, "ask_answers_consumed": 0,
                                     "n_ask_contradiction": 1}) == "ask_decision"
    # 无欠定:照旧如实收口(不改无欠定路径的硬停语义)
    assert _after_reconcile({"phase_status": "error"}) == "closing"
    assert _after_run({"phase_status": "error"}) == "closing"
    assert _after_merge({"phase_status": "error"}) == "closing"
    assert _after_bed({"phase_status": "bed_blocked"}) == "closing"
    assert _after_prep({"phase_status": "error"}) == "closing"
    assert _after_ask_contradiction({"ask_answers_consumed": 0,
                                     "n_ask_contradiction": 1}) == "closing"


# --------------------------------------------------------------- e2e 金标准
def test_gather_e2e_undecided_does_not_block_siblings(rig):
    """102 欠定:101/103 照常跑到 delivery(ctx 不被扣押)→ 批末 gather 一次呈报
    → 答「改过程」复活 → 子集验证 → 整卷终验 → 三案全交付。"""
    nd_written = {"n": 0}

    orig_fork = None

    def fork_with_undecided(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-worker" and aid == AIDS[1] and nd_written["n"] == 0:
            nd_written["n"] += 1
            d = rig["outputs"] / aid
            d.mkdir(exist_ok=True)
            (d / "needs_decision.json").write_text(json.dumps({
                "autoid": aid, "claims": [{
                    "claim_kind": "command_existence", "command": "sdns fulldns on",
                    "reason": "命令在 10.5 手册命令集未命中", "min_requests": 0,
                    "ordering_sensitive": False}]}, ensure_ascii=False), encoding="utf-8")
            return "cannot verify on this build\nSTATUS: needs_user_decision"
        return orig_fork(skill, brief, tag=tag, effort=effort)

    from main.ist_core.compile_engine_v8 import nodes as N
    orig_fork = N._FORK_OVERRIDE
    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork_with_undecided)

    device = FakeDevice(lambda aid, ctx, n: "pass")
    panels: list[dict] = []

    def answer(payload):
        panels.append(payload)
        if payload.get("kind") == "ask_decision":
            return {q["_autoid"]: "改过程" for q in payload.get("questions", [])}
        return {}

    res, g, cfgd = _run_graph(rig, device, resume_answers=answer)
    rep = _report(rig)

    # ① 兄弟案不被阻塞:第一次上机发生在 gather 之前(delivery ctx,组成不含 102)
    first_ctx, first_comp = device.calls[0]
    assert first_ctx == "delivery", "欠定案扣押了 delivery 语境(live 集未排除 awaiting)"
    assert AIDS[1] not in first_comp and set(first_comp) == {AIDS[0], AIDS[2]}
    # ② gather 面板恰一次、kind=ask_decision、包含 102 的存在性题面
    gathers = [p for p in panels if p.get("kind") == "ask_decision"]
    assert len(gathers) == 1, f"gather 应恰一次,实际 {len(gathers)}"
    assert any(q.get("_autoid") == AIDS[1] for q in gathers[0]["questions"])
    # ③ 复活后走子集(仅 102)再整卷终验(三案)
    ctxs = [(ctx, set(comp)) for ctx, comp in device.calls]
    assert ("subset", {AIDS[1]}) in ctxs, f"复活案未走子集复验: {ctxs}"
    assert ("delivery", set(AIDS)) in ctxs, f"复活后未整卷终验: {ctxs}"
    # ④ 终局:三案全交付,报告如实
    assert rep["totals"]["deliverable"] == 3, rep["totals"]
    # ⑤ 题面入账(发现#6)且幂等(interrupt 重放不重复)
    facts = [json.loads(l) for l in
             (rig["outputs"] / rig["out_name"] / "facts.jsonl").read_text(
                 encoding="utf-8").splitlines()]
    asked = [f for f in facts if f.get("ev") == "ask_shown" and f.get("aid") == AIDS[1]]
    assert len(asked) == 1, f"ask_shown 题面事实应恰一条,实际 {len(asked)}"
    assert asked[0].get("gather") is True and "查不到" in asked[0].get("question", "")   # S3 人话
    dec = [f for f in facts if f.get("ev") == "decision" and f.get("aid") == AIDS[1]]
    assert len(dec) == 1 and dec[0]["answer"] == "改过程"


def test_gather_fires_despite_persistent_broken(rig):
    """回归#2 e2e(yzg 形态):非收敛 broken 案(设备恒 not_run)不得饿死 awaiting_user
    的 gather。101 pass(交付)+ 102 欠定 + 103 恒 broken——修前 103 让 live 恒 >0、
    reconcile 恒回 merge、102 永不被问(yzg 实证);修后 103 per-case streak≥2 →
    escalated 退出 live,101 卷指纹隔离稳居 deliverable,live 归零 → gather 问到 102。"""
    def fork_undecided_102(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-worker" and aid == AIDS[1]:
            d = rig["outputs"] / aid
            d.mkdir(exist_ok=True)
            if not (d / "needs_decision.json").exists():
                (d / "needs_decision.json").write_text(json.dumps({
                    "autoid": aid, "claims": [{"claim_kind": "command_existence",
                                               "command": "sdns fulldns on",
                                               "reason": "命令在 10.5 手册命令集未命中"}]},
                    ensure_ascii=False), encoding="utf-8")
            return "cannot verify\nSTATUS: needs_user_decision"
        return orig_fork(skill, brief, tag=tag, effort=effort)

    from main.ist_core.compile_engine_v8 import nodes as N
    orig_fork = N._FORK_OVERRIDE
    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork_undecided_102)

    # 103 设备恒 unknown → not_run → undetermined broken(yzg 的非收敛 broken 复刻)
    device = FakeDevice(lambda aid, ctx, n: "unknown" if aid == AIDS[2] else "pass")
    panels: list[dict] = []

    def answer(payload):
        panels.append(payload)
        if payload.get("kind") == "ask_decision":
            return {q["_autoid"]: "改描述" for q in payload.get("questions", [])}
        return {}

    res, g, cfgd = _run_graph(rig, device, resume_answers=answer)
    fs = [json.loads(l) for l in (rig["outputs"] / rig["out_name"] / "facts.jsonl")
          .read_text(encoding="utf-8").splitlines() if l.strip()]

    # ① gather 真的触发了(102 被问)——修前这里永远为 0(饿死)
    gathers = [p for p in panels if p.get("kind") == "ask_decision"]
    assert gathers, "gather 从未触发——awaiting_user 被非收敛 broken 饿死(回归#2 未修)"
    assert any(q.get("_autoid") == AIDS[1] for q in gathers[0]["questions"])
    # ② 非收敛 broken(103)per-case streak 升级退出 live(不再无限占 live)
    esc = [f for f in fs if f.get("ev") == "escalated" and str(f.get("aid")) == AIDS[2]]
    assert esc, "恒 broken 案未 escalated——per-case streak 未生效,live 不收敛"
    # ③ 101 pass 案没被 103 的子集复跑卷 churn 降级(卷指纹隔离)
    assert not any(f.get("ev") == "awaiting_user_unasked" and str(f.get("aid")) == AIDS[1]
                   for f in fs), "102 被静默吞(收口前未问)"


def _fork_undecided_forever(rig, orig):
    def fork(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-worker" and aid == AIDS[1]:
            d = rig["outputs"] / aid
            d.mkdir(exist_ok=True)
            (d / "needs_decision.json").write_text(json.dumps({
                "autoid": aid, "claims": [{"claim_kind": "command_existence",
                                           "command": "sdns fulldns on",
                                           "reason": "未命中"}]},
                ensure_ascii=False), encoding="utf-8")
            return "STATUS: needs_user_decision"
        return orig(skill, brief, tag=tag, effort=effort)
    return fork


def test_gather_dismissed_closes_honestly(rig):
    """面板被略过(答复不含该案——TUI「跳过」形态):如实收口,欠定案记未通过卷,
    其余案交付不受影响。注意 resume 载荷不能是空 dict——langgraph 对空 dict 走
    interrupt-id 匹配分支(vacuous truth)永不消费、面板重挂(那是夜跑挂机形态,
    checkpoint 在,晨起可续,不是 bug)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE",
                               _fork_undecided_forever(rig, N._FORK_OVERRIDE))
    device = FakeDevice(lambda aid, ctx, n: "pass")
    res, g, cfgd = _run_graph(rig, device,
                              resume_answers=lambda p: {"__dismiss__": ""})
    rep = _report(rig)
    assert rep["totals"]["deliverable"] == 2, rep["totals"]
    assert rep["cases"][AIDS[1]]["status"] in ("awaiting_user", "pending_decision",
                                               "suspended"), rep["cases"][AIDS[1]]
    # 兄弟案的交付未被扣押:存在 delivery ctx 上机且不含 102
    assert any(ctx == "delivery" and AIDS[1] not in comp for ctx, comp in device.calls)


def test_gather_answer_suspend_via_desc(rig):
    """答「改描述」=本轮不产出 → 挂起(非终态,跨批可续),引擎收口不再重派重问。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE",
                               _fork_undecided_forever(rig, N._FORK_OVERRIDE))
    device = FakeDevice(lambda aid, ctx, n: "pass")
    panels = []

    def answer(payload):
        panels.append(payload)
        if payload.get("kind") == "ask_decision":
            return {q["_autoid"]: "改描述" for q in payload.get("questions", [])}
        return {}

    res, g, cfgd = _run_graph(rig, device, resume_answers=answer)
    rep = _report(rig)
    gathers = [p for p in panels if p.get("kind") == "ask_decision"]
    assert len(gathers) == 1, f"改描述后不得再问,实际问了 {len(gathers)} 次"
    assert rep["totals"]["deliverable"] == 2
    assert rep["cases"][AIDS[1]]["status"] == "suspended", rep["cases"][AIDS[1]]
