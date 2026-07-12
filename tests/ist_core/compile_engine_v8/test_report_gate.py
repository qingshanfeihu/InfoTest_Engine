"""G5 报告重算门(DESIGN §17;(42) 报告保真)+ G3 接线修复的集成验证。

验收契约(§17.1-G5):注入一条 render 篡改,门必拦;干净批零误报。
门是独立重算路径——测试同时守护「fold 与门漂移即告警」的冗余设计。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import render as RD
from main.ist_core.compile_engine_v8 import report_gate as RG

A = "203600000000000001"
B = "203600000000000002"


def _delivered_facts(aid=A, art="a1", vol="v1"):
    return [
        {"ev": "authored", "aid": aid, "round": 1, "artifact": art},
        {"ev": "merged", "aid": "", "volume": vol, "members": [aid]},
        {"ev": "verdict", "aid": aid, "run_id": "r1", "ctx": "delivery",
         "result": "pass", "artifact": art, "volume": vol, "signatures": []},
    ]


def _report(status="deliverable", extra_totals=None):
    totals = {"cases": 1, status: 1, "deliverable": 1 if status == "deliverable" else 0}
    totals.update(extra_totals or {})
    return {"engine": "v8", "outcome": "delivered_all_pass",
            "totals": totals,
            "cases": {A: {"status": status, "artifact": "a1", "rounds": 1,
                          "contradictions": 0, "frozen": False,
                          "transient_recur": False}}}


MANIFEST = {"source": "t.txt", "cases": [{"autoid": A, "title": "案A"}]}


# ── 独立重算 ─────────────────────────────────────────────────────────────────


def test_recount_supports_clean_delivery():
    rc = RG.recount_deliverable(_delivered_facts(), MANIFEST)
    assert rc["deliverable"] == {A}


@pytest.mark.parametrize("tamper", [
    lambda fs: fs + [{"ev": "delivery_blocked", "aid": A, "run_id": "g3"}],
    lambda fs: fs + [{"ev": "escalated", "aid": A, "reason": "x"}],
    lambda fs: fs + [{"ev": "suspended", "aid": A, "reason": "q"}],
    # 旧卷组成的 pass 不为当前背书(volume 指纹不匹配)
    lambda fs: fs + [{"ev": "merged", "aid": "", "volume": "v2", "members": [A]}],
    # 重编后旧卷面 pass 失效(artifact 指纹不匹配)
    lambda fs: fs + [{"ev": "authored", "aid": A, "round": 2, "artifact": "a2"}],
])
def test_recount_withdraws_support(tamper):
    fs = tamper(_delivered_facts())
    assert RG.recount_deliverable(fs, MANIFEST)["deliverable"] == set()


# ── 比对门 ───────────────────────────────────────────────────────────────────


def _md(total=1, ok=1):
    return f"# 交付报告 — t.txt\n\n本批 {total} 个用例:**{ok} 个通过整卷复验,已入交付卷**。\n"


def test_clean_report_no_issues():
    issues, _ = RG.check_report(_report(), _md(), _delivered_facts(), MANIFEST)
    assert issues == []


def test_render_tamper_is_caught():
    """验收契约:render 篡改(头行数字虚报)必拦。"""
    issues, detail = RG.check_report(_report(), _md(total=26, ok=26),
                                     _delivered_facts(), MANIFEST)
    assert issues and detail.get("headline")
    assert any("26" in i for i in issues)


def test_unsupported_claim_is_caught():
    """名义 26/26 前科形态:报告称通过,事实台账只有 fail。"""
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "merged", "aid": "", "volume": "v1", "members": [A]},
          {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery",
           "result": "fail", "artifact": "a1", "volume": "v1", "signatures": []}]
    issues, detail = RG.check_report(_report(), _md(), fs, MANIFEST)
    assert detail.get("unsupported_claims") == [A]


def test_totals_incoherence_is_caught():
    """汇总与逐案互算不一致(G3 接线曾产出的形态:cases 说 deliverable,
    totals 的 deliverable 键被旧计数 clobber)。"""
    rep = _report(extra_totals={"deliverable": 0})
    issues, detail = RG.check_report(rep, _md(), _delivered_facts(), MANIFEST)
    assert detail.get("deliverable_count")


def test_fold_drift_reverse_direction_caught():
    """反向漂移:事实支持通过,报告却标了别的状态——门双向报。"""
    rep = _report(status="failed")
    issues, detail = RG.check_report(rep, _md(ok=0), _delivered_facts(), MANIFEST)
    assert detail.get("unreported_passes") == [A]


def test_banner_is_leak_free():
    issues = ["报告称 1 个用例(尾号 …000001)通过整卷复验,但事实台账不支撑该结论"]
    assert RD.leak_scan(RG.mismatch_banner(issues)) == []


# ── closing 集成:G3 封堵后报告自洽 + G5 零误报;篡改场景 G5 拒绝交付 ──────────


@pytest.fixture()
def engine_env(tmp_path, monkeypatch):
    out = tmp_path / "outputs"
    mdir = out / "b1"
    mdir.mkdir(parents=True)
    for aid in (A, B):
        (out / aid).mkdir()
        (out / aid / "case.xlsx").write_bytes(b"fake")
    facts_file = mdir / "facts.jsonl"
    art_a, art_b = "a1", "b1"
    F.append_facts(facts_file, [
        {"ev": "authored", "aid": A, "round": 1, "artifact": art_a},
        {"ev": "authored", "aid": B, "round": 1, "artifact": art_b},
        {"ev": "merged", "aid": "", "volume": "vol1", "members": [A, B],
         "moved_tail": [], "coexist_violations": []},
        {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery", "result": "pass",
         "artifact": art_a, "volume": "vol1", "signatures": []},
        {"ev": "verdict", "aid": B, "run_id": "r1", "ctx": "delivery", "result": "pass",
         "artifact": art_b, "volume": "vol1", "signatures": []},
    ])
    manifest = {"source": "b1.txt",
                "cases": [{"autoid": A, "title": "案A"}, {"autoid": B, "title": "案B"}]}
    (mdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                        encoding="utf-8")
    (mdir / "last_run.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: out)
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: manifest)
    monkeypatch.setattr(sh, "case_rows", lambda aid: [])
    return {"out": out, "mdir": mdir, "facts": facts_file}


_POLLUTER_ROWS = [{"E": "APV_0", "F": "cmds_config",
                   "G": "vlan port2 vlan100 100\n"
                        "ip address vlan100 172.16.34.70 255.255.255.0"}]


def test_closing_g3_block_keeps_report_coherent(engine_env, monkeypatch):
    """B 案缺 τ:G3 封堵后 engine_report 的 cases/totals/头行三方自洽,G5 零误报。"""
    monkeypatch.setattr(N, "_load_case_rows",
                        lambda aid: _POLLUTER_ROWS if aid == B else [])
    emitted = {}
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: emitted.update(d))
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    mdir = engine_env["mdir"]
    rep = json.loads((mdir / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["cases"][B]["status"] == "delivery_blocked"
    assert rep["totals"]["deliverable"] == 1
    assert rep["totals"]["delivery_blocked"] == 1
    md = (mdir / "delivery_report.md").read_text(encoding="utf-8")
    assert "本批 2 个用例:**1 个通过整卷复验" in md
    assert "缺案尾清理" in md            # G3 案在报告里如实解释
    assert RD.leak_scan(md) == []
    assert not (mdir / "REPORT_MISMATCH.json").exists()
    assert emitted["ok"] == 1 and emitted["report_mismatch"] is False


def test_closing_g5_refuses_on_render_tamper(engine_env, monkeypatch):
    """注入 render 篡改(头行虚报 26/26):G5 必拦——告警文件+outcome 翻转+警示条。"""
    real = RD.render_delivery_report

    def tampered(report, fs, m, queues, panels=None):
        md = real(report, fs, m, queues, panels)
        return md.replace("本批 2 个用例:**2 个通过整卷复验",
                          "本批 26 个用例:**26 个通过整卷复验")

    monkeypatch.setattr(RD, "render_delivery_report", tampered)
    emitted = {}
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: emitted.update(d))
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    mdir = engine_env["mdir"]
    mm = json.loads((mdir / "REPORT_MISMATCH.json").read_text(encoding="utf-8"))
    assert mm["issues"]
    rep = json.loads((mdir / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["outcome"] == "report_mismatch"
    md = (mdir / "delivery_report.md").read_text(encoding="utf-8")
    assert md.startswith("> ⚠ **报告校验未通过**")
    assert emitted["report_mismatch"] is True
    fs = F.load_facts(engine_env["facts"])
    assert any(f.get("ev") == "report_mismatch" for f in fs)
