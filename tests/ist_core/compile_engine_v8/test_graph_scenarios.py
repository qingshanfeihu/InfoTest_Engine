"""V8 图级金标准场景(假设备回放):INV-1/2/4/5/6 + yzg 双回合形态固化。

场景脚本经注入点控制:_FORK_OVERRIDE(worker/attributor)、_digest_fn(设备)、
B.bed_check(床态)。真理断言全部落在事实流与报告上。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8.graph import build_v8_graph

AIDS = ["203600000000000101", "203600000000000102", "203600000000000103"]


class FakeDevice:
    """场景脚本:per-(aid, artifact_round, ctx) 的裁决序列;digest 落 last_run.json。"""

    def __init__(self, script):
        self.script = script            # fn(aid, ctx, n_runs_so_far) -> "pass"|"fail"
        self.calls: list[tuple] = []

    def digest(self, xlsx_path: str, autoids: list[str]) -> str:
        ctx = "delivery" if "__sub" not in xlsx_path else "subset"
        recs = []
        for aid in autoids:
            verdict = self.script(aid, ctx, sum(1 for c in self.calls))
            recs.append({"autoid": aid, "verdict": verdict,
                         "_fail_signatures": ["sig-" + aid[-3:]] if verdict == "fail" else [],
                         "device_context": f"echo for {aid} ({verdict})"})
        self.calls.append((ctx, tuple(autoids)))
        lr = Path(xlsx_path).parent / "last_run.json"
        lr.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
        return "=== dev_run_batch_digest ===\nok"


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    """隔离运行台:tmp outputs 根 + 全注入点 + 记录器。"""
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "emit_tick", lambda *a, **k: None)
    # 合并预检豁免(#74-②):rig 假 worker 产的卷无 lint 凭证语义,预检会全拒;
    # 预检真实行为由 test_merge_precheck.py 单元覆盖
    from main.ist_core.tools.device import emit_xlsx_tool as _ex
    monkeypatch.setattr(_ex, "precheck_merge_case", lambda a: None)
    # user_decision 落盘 stub(§18.2 坑#14):真语义=落盘失败则 decision 不落账重问;
    # rig 假案无 workspace 目录,落盘必败会把「改描述→挂起」场景全变成重问——
    # stub 成功路径;失败语义由专项单元覆盖
    from main.ist_core.tools.device import verifiability_tool as _vt
    monkeypatch.setattr(_vt.compile_user_decision, "func",
                        lambda autoid, decision: f"ok: {autoid} {decision}")
    signals: list[tuple] = []
    monkeypatch.setattr(sh, "signal", lambda name, subj, **p: signals.append((name, subj, p)))

    # manifest + prep 幂等入口
    out_name = "batch1"
    mdir = outputs / out_name
    mdir.mkdir()
    manifest = {"cases": [{"autoid": a, "title": f"case {a[-3:]}",
                           "group_path": ["g"], "step_intents": []} for a in AIDS]}
    (mdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    # 床态:干净通过。bed_snapshot/check_sync 也必须打桩——bed_gate 与 closing 会
    # 独立调它们,漏桩=单测真连跳板机 FastMCP/SSH 并真探设备床(2026-07-13 实证:
    # 服务端一次卡死,SSE keep-alive 续租 idle 超时,全量回归在此级联挂 20min+)
    monkeypatch.setattr(N.B, "bed_check", lambda *a, **k: {
        "anchor": {"status": "match", "device": "InfosecOS Beta.APV-HG-K.10.5.0.585"},
        "findings": [], "needs_ask": False, "ours_unrestored": []})
    monkeypatch.setattr(N.B, "bed_snapshot", lambda probe_fn: {})
    import main.ist_core.compile_engine_v8.mirror_anchor as _MA
    monkeypatch.setattr(_MA, "check_sync",
                        lambda _exec: {"status": "unknown", "reason": "rig-stubbed"})

    # worker/attributor 假实现
    def fake_fork(skill, brief, *, tag="", effort=""):
        env = json.loads(brief.splitlines()[0])
        aid = str(env.get("autoid"))
        if skill == "compile-worker":
            d = outputs / aid
            d.mkdir(exist_ok=True)
            xp = d / "case.xlsx"
            xp.write_text("volume", encoding="utf-8")
            (d / ".grade_credential.json").write_text(
                json.dumps({"xlsx_mtime": xp.stat().st_mtime, "source": "lint"}),
                encoding="utf-8")
            return "done\nSTATUS: produced\nARTIFACT: case.xlsx"
        # attributor:把 reflow 结论落进 last_run(submit_attribution 的假体)
        lrp = tmp_path / str(env.get("last_run_path"))
        data = json.loads(lrp.read_text(encoding="utf-8"))
        for r in data:
            if str(r.get("autoid")) == aid:
                r["_attribution"] = {"layer": "V", "disposition": "reflow",
                                     "fix_direction": "adjust expectation",
                                     "evidence": f"echo for {aid}"}
        lrp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return "VERDICT: V/reflow"
    monkeypatch.setattr(N, "_FORK_OVERRIDE", fake_fork)

    # merge 的工具与卷面读取假体
    import main.ist_core.tools.device as TD
    class _FakeMerged:
        @staticmethod
        def invoke(args):
            vol = outputs / str(args["out_name"])
            vol.mkdir(exist_ok=True)
            (vol / "case.xlsx").write_text(",".join(args["autoids"]), encoding="utf-8")
            return f"已合并 {len(args['autoids'])} 个真 case + 1 哨兵 → {vol}/case.xlsx"
    monkeypatch.setattr(TD, "compile_emit_merged", _FakeMerged)
    monkeypatch.setattr(N, "_load_case_rows",
                        lambda aid: [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"}])

    # 写回/回滚记录器 + 自愈入库禁用(单独测过)
    wb, rb = [], []
    monkeypatch.setattr(N, "_writeback_one", lambda aid, lr: wb.append(aid))
    monkeypatch.setattr(N, "_rollback_one", lambda aid: rb.append(aid))
    import main.ist_core.compile_engine_v8.uncertain as U8
    monkeypatch.setattr(U8, "_ingest_uncertain_observations", lambda led: None)

    return {"tmp": tmp_path, "outputs": outputs, "out_name": out_name,
            "signals": signals, "wb": wb, "rb": rb, "monkeypatch": monkeypatch}


def _run_graph(rig, device, resume_answers=None, thread="t1"):
    N._digest_fn_orig = N._digest_fn
    rig["monkeypatch"].setattr(N, "_digest_fn", device.digest)
    g = build_v8_graph(checkpointer=MemorySaver())
    cfgd = {"configurable": {"thread_id": thread}}
    state = {"mindmap_path": "unused.txt", "out_name": rig["out_name"],
             "product_version": "10.5", "max_rounds": 3}
    res = g.invoke(state, cfgd)
    hops = 0
    while "__interrupt__" in res and hops < 6:
        payload = res["__interrupt__"][0].value
        ans = (resume_answers or (lambda p: {}))(payload)
        res = g.invoke(Command(resume=ans), cfgd)
        hops += 1
    return res, g, cfgd


def _report(rig):
    return json.loads((rig["outputs"] / rig["out_name"] / "engine_report.json")
                      .read_text(encoding="utf-8"))


# ── S1 全过直交付:INV-1 + 首跑即 delivery 语境 ────────────────────────────────

def test_s1_clean_batch_all_pass(rig):
    dev = FakeDevice(lambda aid, ctx, n: "pass")
    res, *_ = _run_graph(rig, dev)
    rep = _report(rig)
    assert rep["outcome"] == "delivered_all_pass"
    assert rep["totals"]["deliverable"] == 3          # INV-1:报告=视图
    assert dev.calls and dev.calls[0][0] == "delivery"  # 首跑整卷即交付语境
    fs = F.load_facts(rig["outputs"] / rig["out_name"] / "facts.jsonl")
    assert sum(1 for f in fs if f.get("ev") == "verdict") == 3   # INV-2:全裁决入流
    assert sorted(rig["wb"]) == sorted(AIDS)          # PASS 即时写回×3


# ── S2 yzg 形态:终验矛盾两次 → 第三条 ask 边(INV-4)+回滚(INV-6)+如实报告(INV-1) ──

def test_s2_contradiction_reaches_ask_edge_and_report_is_honest(rig):
    c2 = AIDS[1]

    def script(aid, ctx, n):
        if aid != c2:
            return "pass"
        return "pass" if ctx == "subset" else "fail"   # 单跑过/整卷挂(干扰形态)

    asked = []

    def answers(payload):
        asked.append(payload)
        if payload.get("kind") == "ask_contradiction":
            return {c2: "接受单跑"}
        return {}

    dev = FakeDevice(script)
    res, *_ = _run_graph(rig, dev, resume_answers=answers)
    rep = _report(rig)
    # INV-4:矛盾第二次必达 ask 边
    assert any(p.get("kind") == "ask_contradiction" for p in asked)
    # INV-1:如实报告——c2 不在可交付集,不出现名义全过
    assert rep["outcome"] == "delivered_with_labels"
    assert rep["totals"]["deliverable"] == 2
    assert rep["cases"][c2]["status"] != "deliverable"
    # INV-6:c2 曾 subset-pass 写回,终验矛盾后必回滚
    assert c2 in rig["rb"]
    # 信号:final_verify_failed 至少一次
    assert any(s[0] == "final_verify_failed" and s[1] == c2 for s in rig["signals"])
    # 事实流:矛盾计数≥2,全史可查
    fs = F.load_facts(rig["outputs"] / rig["out_name"] / "facts.jsonl")
    assert F.contradictions([f for f in fs if f.get("aid") == c2], c2) >= 2


# ── S3 INV-5:床锚失配跑前拦截,零设备轮 ───────────────────────────────────────

def test_s3_bed_mismatch_blocks_before_any_device_round(rig):
    rig["monkeypatch"].setattr(N.B, "bed_check", lambda *a, **k: {
        "anchor": {"status": "mismatch", "device": "…10.4.6.170", "config": "…10_5_0_568"},
        "findings": [{"kind": "build_anchor"}], "needs_ask": True, "ours_unrestored": []})
    dev = FakeDevice(lambda aid, ctx, n: "pass")
    asked = []

    def answers(payload):
        asked.append(payload)
        return {"decision": "停"}
    res, *_ = _run_graph(rig, dev, resume_answers=answers)
    assert any(p.get("kind") == "bed_gate" for p in asked)
    assert dev.calls == []                     # 零设备轮(yzg@103 的 ¥160 教训)
    fs = F.load_facts(rig["outputs"] / rig["out_name"] / "facts.jsonl")
    assert any(f.get("ev") == "bed_checked" for f in fs)


# ── S4 增量重编先走子集,再终验(语境判定规则) ─────────────────────────────────

def test_s4_incremental_recompile_goes_subset_then_delivery(rig):
    c2 = AIDS[1]
    state = {"n": 0}

    def script(aid, ctx, n):
        if aid == c2 and ctx == "delivery" and n == 0:
            return "fail"                       # 首跑 delivery:c2 挂
        return "pass"                           # 子集验证与终验全过
    dev = FakeDevice(script)
    res, *_ = _run_graph(rig, dev)
    rep = _report(rig)
    assert rep["outcome"] == "delivered_all_pass"
    # 轨迹:delivery(3) → subset(仅 c2) → delivery(3)
    kinds = [(c[0], len(c[1])) for c in dev.calls]
    assert kinds[0] == ("delivery", 3)
    assert ("subset", 1) in kinds
    assert kinds[-1] == ("delivery", 3)
    # §11.9 清理契约(C 片):per-case 目录收进批目录(通过案 delivered/ 存档,
    # 含重编 history——挂起恢复后终验重组全卷仍可用);outputs/ 根不留散目录
    assert not (rig["outputs"] / c2).exists()
    assert (rig["outputs"] / rig["out_name"] / "delivered" / c2
            / "history" / "case.r1.xlsx").is_file()
    assert (rig["outputs"] / rig["out_name"] / "delivery_report.md").is_file()
