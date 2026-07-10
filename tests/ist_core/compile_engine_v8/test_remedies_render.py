"""§11 验收器:导出修法队列(修法归理论) + 判定式渲染(零泄漏) + yzg 真机事实金标准回放。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import remedies as R
from main.ist_core.compile_engine_v8 import render as RD
from main.ist_core.compile_engine_v8 import views as V

FIX = Path(__file__).parent / "fixtures"
A = "209030000000000001"

SAVE_ROWS = [{"E": "APV_0", "F": "cmds_config", "G": "write memory"}]
PLAIN_ROWS = [{"E": "APV_0", "F": "cmds_config", "G": "sdns on"}]


def _v(result, ctx, art="a1", rid="r1"):
    return {"ev": "verdict", "aid": A, "run_id": rid, "ctx": ctx, "result": result,
            "artifact": art, "volume": "v", "signatures": []}


# ── 队列:修法归理论 ─────────────────────────────────────────────────────────

def test_queue_self_cleanup_first_for_channel_hit_contradiction():
    """互扰消解推论:命中持久通道的矛盾案,队列头=案内自清理(带手册引用)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _v("pass", "subset"), _v("fail", "delivery", rid="r2")]
    q = R.derive_queue(fs, A, SAVE_ROWS)
    assert q and q[0]["action"] == "self_cleanup" and q[0]["channel"] == "local_disk"
    assert q[0]["refs"] and q[0]["obligation"]
    assert any(x["action"] == "rerun_isolated" for x in q)


def test_queue_drains_by_authored_remedy_stamp():
    """authored.remedy 戳=机械"已试";戳上后同修法不再入队。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _v("pass", "subset"), _v("fail", "delivery", rid="r2"),
          {"ev": "authored", "aid": A, "round": 2, "artifact": "a2",
           "remedy": "self_cleanup:local_disk"},
          _v("fail", "delivery", art="a2", rid="r3")]
    q = R.derive_queue(fs, A, SAVE_ROWS)
    assert not any(x["action"] == "self_cleanup" for x in q)


def test_queue_recompile_directed_rekeys_per_attribution_round():
    """新一轮归因给出新方向 → 定向重编再次可试(键按归因轮)。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _v("fail", "delivery"),
          {"ev": "attribution", "aid": A, "round": 1, "run_id": "r1",
           "layer": "V", "disposition": "reflow", "fix_direction": "d1"}]
    q1 = R.derive_queue(fs, A, PLAIN_ROWS)
    assert any(x["action"] == "recompile_directed" for x in q1)
    fs += [{"ev": "authored", "aid": A, "round": 2, "artifact": "a2",
            "remedy": "recompile_directed:r1"},
           _v("fail", "delivery", art="a2", rid="r2"),
           {"ev": "attribution", "aid": A, "round": 2, "run_id": "r2",
            "layer": "V", "disposition": "reflow", "fix_direction": "d2"}]
    q2 = R.derive_queue(fs, A, PLAIN_ROWS)
    assert any(x["action"] == "recompile_directed" for x in q2)


def test_queue_empty_gates_ask():
    """队列空=允许问;pass 案队列恒空。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _v("pass", "delivery")]
    assert R.queue_empty(fs, A, SAVE_ROWS)


# ── 渲染:判定式 + 零泄漏 ────────────────────────────────────────────────────

def _mini_report_and_facts():
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _v("pass", "subset"),
          {"ev": "writeback", "aid": A, "targets": ["precedent"], "voucher_run": "r1"},
          _v("fail", "delivery", rid="r2"),
          {"ev": "rollback", "aid": A, "of": "writeback", "reason": "contradicted_at_delivery"},
          {"ev": "attribution", "aid": A, "round": 1, "run_id": "r2", "layer": "V",
           "disposition": "reflow", "fix_direction": "en", "evidence": "echo",
           "user_note": "装载配置文件时设备回显了海量内容,把要检查的关键信息淹没了。",
           "doc_quote": "clear sdns all 不会清除SDNS配置文件", "doc_source": "CLI Ch20",
           "device_quote": "Running configuration backup files"}]
    report = {"engine": "v8", "outcome": "delivered_with_labels",
              "totals": {"cases": 1, "deliverable": 0}, "volume": "v",
              "moved_tail": [A], "coexist_violations": [],
              "cases": {A: {"status": "contradicted", "artifact": "a1", "rounds": 1,
                            "contradictions": 1, "frozen": False, "transient_recur": False}}}
    manifest = {"source": "test.txt", "cases": [{"autoid": A, "title": "SDNS 配置文件下发",
                "step_intents": [{"desc": "保存配置", "expected": "保存成功"}]}]}
    return report, fs, manifest


def test_delivery_report_is_determinate_and_leak_free():
    report, fs, manifest = _mini_report_and_facts()
    queues = {A: R.derive_queue(fs, A, SAVE_ROWS)}
    md = RD.render_delivery_report(report, fs, manifest, queues)
    # 判定式:修法是陈述句且引用依据;不出现选项菜单
    assert "修复方案" in md and "清理" in md and "CLI Ch20" in md
    assert "①" not in md and "② " not in md
    # 人话:user_note 上报告;时间线含矛盾叙事;先例撤销如实说
    assert "淹没" in md and "单独验证" in md and "撤销" in md
    # 零泄漏门
    assert RD.leak_scan(md) == []


def test_unsuccessful_md_leak_free_and_self_contained():
    report, fs, manifest = _mini_report_and_facts()
    queues = {A: R.derive_queue(fs, A, SAVE_ROWS)}
    md = RD.render_unsuccessful_md(report, fs, manifest, queues,
                                   {A: "2026-07-10 10:00:00 1.2.3.4 - echo line"})
    assert "脑图原始用例" in md and "保存配置" in md
    assert "echo line" in md and "2026-07-10 10:00:00" not in md   # 时间戳已剥
    assert RD.leak_scan(md) == []


def test_status_vocab_covers_all_view_labels():
    """结构门:视图每个标签都有人话词条(新增标签必须配词)。"""
    labels = [getattr(V, n) for n in dir(V) if n.startswith("S_")]
    for lab in labels:
        assert lab in RD.STATUS_CN, f"missing vocab for {lab}"


# ── 金标准回放:yzg 真机验收事实流 → 渲染稳定且零泄漏 ─────────────────────────

def test_yzg_golden_replay_renders_leak_free():
    fs = F.load_facts(FIX / "yzg_facts.jsonl")
    report = json.loads((FIX / "yzg_engine_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((FIX / "yzg_manifest.json").read_text(encoding="utf-8"))
    assert len(fs) > 100 and report["totals"]["cases"] == 26
    bad = [a for a, c in report["cases"].items() if c["status"] != "deliverable"]
    queues = {a: R.derive_queue([f for f in fs if str(f.get("aid")) == a], a, [])
              for a in bad}
    md = RD.render_delivery_report(report, fs, manifest, queues)
    assert RD.leak_scan(md) == []
    # 三个真机标注案都有完整三段叙事(发生了什么/怎么判断/修复或结论)
    for a in bad:
        title = next((str(c.get("title")) for c in manifest["cases"]
                      if str(c.get("autoid")) == a), "")
        assert (title and title in md) or f"…{a[-6:]}" in md
    assert md.count("发生了什么") == len(bad) == 3
    assert md.count("怎么判断的") == 3
