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
    """persist 经 §18.12 三稿收窄:只保留框架清不掉的真持久写。write memory 框架
    clear+write memory 清得掉(clear.py)→ 不进 persist(旧版误当持久污染源)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rig["monkeypatch"].setattr(N, "_load_case_rows", lambda aid: [
        {"E": "APV_0", "F": "cmds_config",
         "G": "write all file save_x pwd\nwrite memory"},   # 前者清不掉(.tgz盲区),后者清得掉
        {"E": "APV_0", "F": "cmd_config", "G": "ip address vlan100 172.16.34.70 24"},
        {"E": "check_point", "F": "found", "G": r"172\.16\.34\.70"},
    ])
    p = N._case_touch_profile("x")
    assert p["persist"] == ["write all file save_x pwd"]   # 只留框架清不掉的;write memory 被滤
    assert p["save_files"] == {"save_x"}
    assert p["l23"] == ["ip address vlan100 172.16.34.70 24"]
    assert "172.16.34.70" in p["entities"] and "vlan100" in p["entities"]


def test_s0_classes_data_driven():
    """§18.12 三稿:s₀ 持久写归类(从 clear.py 机械解析框架清理覆盖)。"""
    from main.ist_core.compile_engine_v8.nodes import _s0_persist_class
    assert _s0_persist_class("write memory") == "cleanable"       # 框架 clear+write memory
    assert _s0_persist_class("config memory") == "restore"        # 读磁盘,非污染源
    assert _s0_persist_class("config all file x") == "restore"
    assert _s0_persist_class("write net tftp 1 f") == "remote"    # 远端,本机不留
    assert _s0_persist_class("write file save_x") == "leftover_file"   # .tgz 盲区,需撞名
    assert _s0_persist_class("clear config all") == "uncovered"


def test_write_memory_not_s0_no_cross_file(rig):
    """写保存族自存自恢复(各案异名文件)→ 无跨案撞名 → 不判 s₀(误判消除正锚)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rows = {"P": [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns listener 172.16.34.70 53\nwrite memory\nconfig memory"}],
            "V": [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns listener 172.16.34.70 53\nwrite file save_V\nconfig file save_V"}]}
    rig["monkeypatch"].setattr(N, "_load_case_rows", lambda aid: rows.get(aid, []))
    pc = {a: N._case_touch_profile(a) for a in rows}
    h, pol, _ = N._s0_pair("V", ["P", "V"], lambda a: pc[a], "may already be occupied by SLB")
    assert h == "" and pol == []       # write memory 清得掉+自存自恢复无跨案 → 非 s₀


def test_cross_file_collision_is_s0(rig):
    """真跨案撞名:B 从 A 存的同名文件 config 恢复 → 保留 s₀(真污染不漏判)。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rows = {"A": [{"E": "APV_0", "F": "cmds_config", "G": "sdns listener 1.1.1.1 53\nwrite file shared"}],
            "B": [{"E": "APV_0", "F": "cmds_config", "G": "sdns listener 1.1.1.1 53\nconfig file shared"}]}
    rig["monkeypatch"].setattr(N, "_load_case_rows", lambda aid: rows.get(aid, []))
    pc = {a: N._case_touch_profile(a) for a in rows}
    h, pol, _ = N._s0_pair("B", ["A", "B"], lambda a: pc[a], "occupied")
    assert h == "h_s0" and any(p["aid"] == "A" for p in pol)


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
        # §18.12 三稿:污染者 write memory 框架清得掉→不再判 s₀;换真跨案撞名
        # (A 存 shared_save,B 从同名 config 恢复)——新判据下 s₀ 仍真实成立
        AIDS[0]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns listener 172.16.34.70\nwrite file shared_save"}],
        AIDS[1]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns on\nsdns listener 172.16.34.70\nconfig file shared_save"}],
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


def test_g6_prescreen_skips_attribution_fork(rig):
    """G6 域分诊前筛(§17,判定树第零层):s₀ 配对命中的案**零归因 fork 派发**
    (run12 实测 22 fork 大半烧在床污染案上;验收判据=归因 fork 数≈非 s₀ fail 数),
    机械落 h_s0 诊断+轻量归因事实,停车位/bed 面板消费链照常走通。"""
    from main.ist_core.compile_engine_v8 import nodes as N

    rows_by_aid = {
        # §18.12 三稿:污染者 write memory 框架清得掉→不再判 s₀;换真跨案撞名
        # (A 存 shared_save,B 从同名 config 恢复)——新判据下 s₀ 仍真实成立
        AIDS[0]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns listener 172.16.34.70\nwrite file shared_save"}],
        AIDS[1]: [{"E": "APV_0", "F": "cmds_config",
                   "G": "sdns on\nsdns listener 172.16.34.70\nconfig file shared_save"}],
        AIDS[2]: [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"}],
    }
    rig["monkeypatch"].setattr(
        N, "_load_case_rows",
        lambda aid: rows_by_aid.get(aid, [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"}]))

    orig_fork = N._FORK_OVERRIDE
    attr_forks: list[str] = []

    def fork(skill, brief, *, tag="", effort=""):
        if skill == "compile-attributor":
            env = json.loads(brief.splitlines()[0])
            attr_forks.append(str(env.get("autoid")))
            return "VERDICT: V/reflow"   # 若被派到,行为无害
        return orig_fork(skill, brief, tag=tag, effort=effort)

    rig["monkeypatch"].setattr(N, "_FORK_OVERRIDE", fork)

    def script(aid, ctx, n):
        return "fail" if aid == AIDS[1] and ctx == "delivery" else "pass"

    device = FakeDevice(script)
    res, g, cfgd = _run_graph(rig, device, resume_answers=lambda p: {"__dismiss__": ""})

    # 验收核心:床污染案(102)未派深归因 fork(s₀ 配对机械证据已足)
    assert AIDS[1] not in attr_forks, f"s₀ 案仍被派归因 fork: {attr_forks}"
    facts = [json.loads(l) for l in
             (rig["outputs"] / rig["out_name"] / "facts.jsonl").read_text(
                 encoding="utf-8").splitlines()]
    mine = [f for f in facts if str(f.get("aid")) == AIDS[1]]
    # 前筛落的轻量归因事实:h_s0 + rerun_isolated(接停车位/bed 面板既有消费链)
    atts = [f for f in mine if f.get("ev") == "attribution"]
    assert atts and atts[-1]["h_position"] == "h_s0", atts
    assert atts[-1]["disposition"] == "rerun_isolated"
    diags = [f for f in mine if f.get("ev") == "diagnosis"]
    assert diags and str(diags[-1]["run_id"]).startswith("diag:pre:"), diags
    # diagnose 节点未重复落账(同卷跳过),但污染者点名在前筛事实里齐全
    assert len(diags) == 1, diags
    assert any(p.get("aid") == AIDS[0] for p in diags[-1]["polluters"])
    # 消费链走通:无「仅 102 的 subset 复跑」+ 收口挂起
    assert not any(ctx == "subset" and set(comp) == {AIDS[1]}
                   for ctx, comp in device.calls), device.calls
    rep = _report(rig)
    assert rep["cases"][AIDS[1]]["status"] == "suspended", rep["cases"][AIDS[1]]


def test_s0_l23_excludes_fixed_infra_ips(rig):
    """§18.14 S1(脏态合取):L2/L3 共享实体减去固定基础设施 IP。667986 实弹——前案写
    接口 IP、后案引用同 IP,不判 s₀(基础设施合法共用);对照前案自建对象仍判 s₀。"""
    from main.ist_core.compile_engine_v8 import nodes as N
    rows = {
        "P_infra": [{"E": "APV_0", "F": "cmds_config",
                     "G": "bond interface bond1 port3\nip address bond1 172.16.32.70 24"}],
        "V_infra": [{"E": "APV_0", "F": "cmds_config",
                     "G": "sdns listener 172.16.32.70\nsdns listener 172.16.34.70 10001"}],
        "P_self": [{"E": "APV_0", "F": "cmds_config",
                    "G": "vlan port1 vlan233 233\nip address vlan233 10.9.9.9 24"}],
        "V_self": [{"E": "APV_0", "F": "cmds_config", "G": "sdns listener vlan233"}],
    }
    rig["monkeypatch"].setattr(N, "_load_case_rows", lambda a: rows.get(a, []))
    N._fixed_infra_ips.cache_clear()
    pc = {a: N._case_touch_profile(a) for a in rows}
    h1, _, _ = N._s0_pair("V_infra", ["P_infra", "V_infra"], lambda a: pc[a], "x")
    assert h1 == ""          # 基础设施 IP 共用 → 非 s₀
    h2, pol2, _ = N._s0_pair("V_self", ["P_self", "V_self"], lambda a: pc[a], "x")
    assert h2 == "h_s0" and any("vlan233" in p.get("shared", []) for p in pol2)   # 自建对象 → 真 s₀
