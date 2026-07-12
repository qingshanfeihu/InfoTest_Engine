# -*- coding: utf-8 -*-
"""V8.5 片3:h 位置轴 + diagnose 批级节点(DESIGN §16.2-B/C)。

金标准=668030 形态回放:前驱案持久面写(write memory)跨案存活 → 受害案 delivery
fail「occupied」;单案归因给 rerun_isolated(run11 实况,导致重排复验×3 全翻挂)
→ 批级诊断裁 h_s0 + 复跑闸挡住无效隔离复跑 + 报告叙事说人话。
"""
from __future__ import annotations

import json

from tests.ist_core.compile_engine_v8.test_graph_scenarios import (  # noqa: F401
    AIDS, FakeDevice, rig, _run_graph, _report)


# --------------------------------------------------------------- 单元:触碰画像
def test_touch_profile_extraction(rig):
    from main.ist_core.compile_engine_v8 import nodes as N
    rig["monkeypatch"].setattr(N, "_load_case_rows", lambda aid: [
        {"E": "APV_0", "F": "cmds_config",
         "G": "slb virtual http v1 172.16.34.70 80\nwrite memory"},
        {"E": "APV_0", "F": "cmd_config", "G": "ip address vlan100 172.16.34.70 24"},
        {"E": "check_point", "F": "found", "G": r"172\.16\.34\.70"},
    ])
    p = N._case_touch_profile("x")
    assert p["persist"] == ["write memory"]
    assert p["l23"] == ["ip address vlan100 172.16.34.70 24"]
    assert "172.16.34.70" in p["entities"] and "vlan100" in p["entities"]


def test_submit_attribution_h_position_validation(tmp_path):
    from main.ist_core.tools.device.fail_attribution import submit_attribution
    lr = tmp_path / "last_run.json"
    lr.write_text(json.dumps([{"autoid": "203600000000000101",
                               "device_context": "some occupied evidence",
                               "_round": 1}]), encoding="utf-8")
    out = submit_attribution.func(xlsx_path=str(lr), autoid="203600000000000101",
                                  layer="V", disposition="rerun_isolated",
                                  evidence="occupied evidence", h_position="h_pi")
    assert "attribution landed" in out
    data = json.loads(lr.read_text(encoding="utf-8"))
    assert data[0]["_attribution"]["h_position"] == "h_pi"
    bad = submit_attribution.func(xlsx_path=str(lr), autoid="203600000000000101",
                                  layer="V", disposition="reflow",
                                  evidence="occupied evidence", h_position="s0")
    assert bad.startswith("error: h_position")


# --------------------------------------------------------------- e2e 668030 回放
def test_diagnose_s0_blocks_pointless_rerun(rig):
    """A(101)带 write memory;B(102)delivery fail「occupied」;归因孔判
    rerun_isolated(run11 实况)→ 诊断裁 h_s0 点名 101 → 复跑闸挡隔离复跑
    (无 subset-only-102 上机)→ **bed 呈报面板**(§11.7:床权在用户,必问——
    redline 缺口②修复)→ 未答自动挂起,如实收口。"""
    from main.ist_core.compile_engine_v8 import nodes as N

    rows_by_aid = {
        AIDS[0]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "slb virtual http v1 172.16.34.70 80\nwrite memory"}],
        AIDS[1]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns on\nsdns listener 172.16.34.70"}],
        AIDS[2]: [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"}],
    }
    rig["monkeypatch"].setattr(
        N, "_load_case_rows",
        lambda aid: rows_by_aid.get(aid, [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"}]))

    orig_fork = N._FORK_OVERRIDE

    def fork(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-attributor":
            # run11 实况复刻:单案视野给 rerun_isolated(误按 π 对策治 s₀ 病)
            lrp = rig["tmp"] / str(env.get("last_run_path"))
            data = json.loads(lrp.read_text(encoding="utf-8"))
            for r in data:
                if str(r.get("autoid")) == aid:
                    r["_attribution"] = {"layer": "V", "disposition": "rerun_isolated",
                                         "h_position": "h_pi",
                                         "fix_direction": "isolate and rerun",
                                         "evidence": f"echo for {aid} (fail)"}
            lrp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return "VERDICT: V/rerun_isolated"
        return orig_fork(skill, brief, tag=tag, effort=effort)

    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork)

    def script(aid, ctx, n):
        # 102 在 delivery 恒 fail(床残留占 IP);其余恒 pass
        return "fail" if aid == AIDS[1] and ctx == "delivery" else "pass"

    device = FakeDevice(script)
    panels: list[dict] = []

    def answer(payload):
        panels.append(payload)
        return {"__dismiss__": ""}   # 不答 → 既有安全件自动挂起

    res, g, cfgd = _run_graph(rig, device, resume_answers=answer)

    facts = [json.loads(l) for l in
             (rig["outputs"] / rig["out_name"] / "facts.jsonl").read_text(
                 encoding="utf-8").splitlines()]
    # ① 诊断事实:h_s0 + 污染者点名 101(持久面写)
    diags = [f for f in facts if f.get("ev") == "diagnosis" and f.get("aid") == AIDS[1]]
    assert diags, "diagnose 未落诊断事实"
    assert diags[-1]["h_position"] == "h_s0", diags[-1]
    assert any(p.get("aid") == AIDS[0] and "persistent" in str(p.get("via"))
               for p in diags[-1]["polluters"]), diags[-1]["polluters"]
    # ② 复跑闸:不存在「仅 102 的 subset 复跑」(run11 的无效轮形态被消灭);
    #    且设备轮有界(s₀ 停车位+终验幂等闸——无 livelock,run11 曾 5 遍整卷)
    assert not any(ctx == "subset" and set(comp) == {AIDS[1]}
                   for ctx, comp in device.calls), device.calls
    assert len(device.calls) <= 4, f"设备轮未收敛: {device.calls}"
    # ③ bed 呈报发生(§11.7 床权必问——不静默停车);未答 → 自动挂起
    bed_items = [it for p in panels if p.get("kind") == "ask_contradiction"
                 for it in p.get("cases", []) if it.get("kind") == "bed"]
    assert bed_items and bed_items[0]["autoid"] == AIDS[1], panels
    rep = _report(rig)
    assert rep["cases"][AIDS[1]]["status"] == "suspended", rep["cases"][AIDS[1]]
    assert rep["totals"]["deliverable"] >= 2, rep["totals"]
    # ④ 叙事说人话:s₀ 判断进「怎么判断的」,点名前驱
    from main.ist_core.compile_engine_v8.render import diagnosis_text
    mine = [f for f in facts if str(f.get("aid")) == AIDS[1]]
    txt = diagnosis_text(mine)
    assert "测试床状态残留" in txt and AIDS[0][-6:] in txt, txt


def test_transient_recovery_final_verify_not_gated(rig):
    """redline 实证回归①:瞬态案 delivery fail → rerun 处方 → subset pass →
    组成与卷面未变的终验**必须放行**(has_upgrade)拿到 delivery-pass。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    orig_fork = N._FORK_OVERRIDE

    def fork(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-attributor":
            lrp = rig["tmp"] / str(env.get("last_run_path"))
            data = json.loads(lrp.read_text(encoding="utf-8"))
            for r in data:
                if str(r.get("autoid")) == aid:
                    r["_attribution"] = {"layer": "transient",
                                         "disposition": "rerun_isolated",
                                         "h_position": "h_pi",
                                         "fix_direction": "one-off timeout, rerun",
                                         "evidence": f"echo for {aid} (fail)"}
            lrp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return "VERDICT: transient/rerun_isolated"
        return orig_fork(skill, brief, tag=tag, effort=effort)

    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork)

    flake = {"done": False}

    def script(aid, ctx, n):
        if aid == AIDS[1] and ctx == "delivery" and not flake["done"]:
            flake["done"] = True
            return "fail"        # 首次 delivery 瞬态失败,此后全过
        return "pass"

    device = FakeDevice(script)
    res, g, cfgd = _run_graph(rig, device, resume_answers=lambda p: {"__dismiss__": ""})
    rep = _report(rig)
    assert rep["totals"]["deliverable"] == 3, (rep["totals"], device.calls)
    ctxs = [(ctx, set(comp)) for ctx, comp in device.calls]
    assert ("subset", {AIDS[1]}) in ctxs, f"rerun 处方未走子集: {ctxs}"
    assert sum(1 for c, _ in device.calls if c == "delivery") >= 2, \
        f"终验幂等闸误挡瞬态恢复的整卷确认: {device.calls}"


def test_diagnose_common_cause_cluster(rig):
    """两案同签名词干 → common_cause 事实(机械前筛 (24) 产物,片4 提案消费)。"""
    from main.ist_core.compile_engine_v8 import nodes as N

    orig_fork = N._FORK_OVERRIDE

    def fork(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-attributor":
            lrp = rig["tmp"] / str(env.get("last_run_path"))
            data = json.loads(lrp.read_text(encoding="utf-8"))
            for r in data:
                if str(r.get("autoid")) == aid:
                    r["_attribution"] = {"layer": "E", "disposition": "env_blocked",
                                         "evidence": f"echo for {aid} (fail)"}
            lrp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return "VERDICT: E/env_blocked"
        return orig_fork(skill, brief, tag=tag, effort=effort)

    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork)

    class SameSigDevice(FakeDevice):
        def digest(self, xlsx_path, autoids):
            ctx = "delivery" if "__sub" not in xlsx_path else "subset"
            recs = []
            for aid in autoids:
                fail = aid in (AIDS[0], AIDS[1])
                recs.append({"autoid": aid, "verdict": "fail" if fail else "pass",
                             "_fail_signatures":
                                 ["connection timed out; no servers could be reached"]
                                 if fail else [],
                             "device_context": f"echo for {aid} (fail)" if fail
                                 else f"echo for {aid} (pass)"})
            self.calls.append((ctx, tuple(autoids)))
            from pathlib import Path
            (Path(xlsx_path).parent / "last_run.json").write_text(
                json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
            return "=== dev_run_batch_digest ===\nok"

    device = SameSigDevice(lambda aid, ctx, n: "pass")
    res, g, cfgd = _run_graph(rig, device, resume_answers=lambda p: {"__dismiss__": ""})
    facts = [json.loads(l) for l in
             (rig["outputs"] / rig["out_name"] / "facts.jsonl").read_text(
                 encoding="utf-8").splitlines()]
    ccs = [f for f in facts if f.get("ev") == "common_cause"]
    assert ccs, "同签名双 fail 未产 common_cause 事实"
    assert set(ccs[-1]["aids"]) == {AIDS[0], AIDS[1]}, ccs[-1]


def test_user_retry_overrides_s0_gate():
    """(36) 写权律(run12 实弹修复):最新 h_s0 诊断之后的用户 retry 裁决必须放行
    复跑——机械闸不得否决用户对床状态的声明(实测 8 案 retry 后零复跑收口)。"""
    from main.ist_core.compile_engine_v8.nodes import _user_retry_after_s0
    aid = AIDS[1]
    fs = [
        {"ev": "diagnosis", "aid": aid, "h_position": "h_s0"},
        {"ev": "decision", "aid": aid, "token": "retry",
         "question_id": f"env:{aid}:1", "answer": "不认可,隔离复跑"},
    ]
    assert _user_retry_after_s0(fs, aid) is True
    # 反向:retry 在诊断之前(旧裁决不背新诊断的书)
    fs_rev = list(reversed(fs))
    assert _user_retry_after_s0(fs_rev, aid) is False
    # 无诊断:不适用
    assert _user_retry_after_s0([fs[1]], aid) is False
