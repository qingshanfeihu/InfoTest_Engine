"""C 片验收(DESIGN §11.2/11.5/11.9):判定式渲染零泄漏 + yzg 金标准回放 +
closing 清理契约(通过案删/未决案挪 unfinished/facts 保留)+ prep 续跑还原 + 收口卡。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import render as RD
from main.ist_core.compile_engine_v8 import views as V

FIX = Path(__file__).parent / "fixtures"
A = "203600000000000001"


def _v(result, ctx, rid="r1", art="a1", vol="v"):
    return {"ev": "verdict", "aid": A, "run_id": rid, "ctx": ctx, "result": result,
            "artifact": art, "volume": vol, "signatures": []}


# ── 判定式渲染 + 零泄漏 ───────────────────────────────────────────────────────


def _mini_report_and_facts():
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          _v("pass", "subset"),
          {"ev": "writeback", "aid": A, "targets": ["precedent"], "voucher_run": "r1"},
          _v("fail", "delivery", rid="r2"),
          {"ev": "rollback", "aid": A, "of": "writeback", "reason": "contradicted_at_delivery"},
          {"ev": "attribution", "aid": A, "round": 1, "run_id": "r2", "layer": "V",
           "disposition": "reflow", "fix_direction": "en",
           "evidence": "Running configuration backup files"},
          {"ev": "ask_panel", "aid": A, "round": 1, "shape": "expected_vs_observed",
           "intent_signature": "sdns-config-file-visibility", "ref": "nonexistent.json"}]
    report = {"engine": "v8", "outcome": "delivered_with_labels",
              "totals": {"cases": 1, "deliverable": 0}, "volume": "v",
              "moved_tail": [A], "coexist_violations": [],
              "cases": {A: {"status": "contradicted", "artifact": "a1", "rounds": 1,
                            "contradictions": 1, "frozen": False, "transient_recur": False}}}
    manifest = {"source": "test.txt", "cases": [{"autoid": A, "title": "SDNS 配置文件下发",
                "step_intents": [{"desc": "保存配置", "expected": "保存成功"}]}]}
    panels = {A: {"conflict_shape": "expected_vs_observed",
                  "hypothesis": "设备行为是新成员下一轮才参与,预期应改为下一轮生效",
                  "ask": "按设备实际行为修改预期结果吗?"}}
    return report, fs, manifest, panels


def test_delivery_report_is_determinate_and_leak_free():
    report, fs, manifest, panels = _mini_report_and_facts()
    md = RD.render_delivery_report(report, fs, manifest, {}, panels)
    # 人话三段:时间线含呈报与撤销叙事;判断段用 panel 的 hypothesis(判断时刻中文)
    assert "发生了什么" in md and "怎么判断的" in md
    assert "撤销" in md and "呈报" in md
    assert "下一轮才参与" in md
    # 判定式:panel 待答 → 去向=等待确认(陈述句,零选项菜单)
    assert "待确认" in md
    assert RD.leak_scan(md) == []


def test_unsuccessful_md_leak_free_and_timestamps_stripped():
    report, fs, manifest, panels = _mini_report_and_facts()
    md = RD.render_unsuccessful_md(report, fs, manifest, {},
                                   {A: "2026-07-10 10:00:00 1.2.3.4 - echo line"},
                                   panels)
    assert "脑图原始用例" in md and "保存配置" in md
    assert "echo line" in md and "2026-07-10 10:00:00" not in md
    assert RD.leak_scan(md) == []


def test_status_vocab_covers_all_view_labels():
    """结构门:视图每个标签都有人话词条(新增标签必须配词)。"""
    labels = [getattr(V, n) for n in dir(V) if n.startswith("S_")]
    for lab in labels:
        assert lab in RD.STATUS_CN, f"missing vocab for {lab}"


@pytest.mark.parametrize("mine,expect", [
    # 用户确认缺陷 → 缺陷结案
    ([{"ev": "attribution", "aid": A, "round": 99, "layer": "product_defect",
       "disposition": "defect_candidate", "evidence": "user"}], "确认为产品缺陷"),
    # 用户止损 → 未通过卷收尾
    ([{"ev": "decision", "aid": A, "question_id": "q", "answer": "停止该案"},
      {"ev": "attribution", "aid": A, "round": 99, "layer": "E",
       "disposition": "env_blocked", "evidence": "user"}], "按环境/取舍收尾"),
    # 判例采信 → 沿用裁决
    ([{"ev": "adopted", "aid": A, "round": 1, "slug": "s", "token": "confirm",
       "ruling": "按下一轮生效编"}], "已有裁决"),
    # panel 待答 → 等待确认
    ([{"ev": "ask_panel", "aid": A, "round": 1, "ref": "x.json"}], "待确认"),
    # 挂起 → 下批恢复询问
    ([{"ev": "suspended", "aid": A, "reason": "q"}], "已挂起"),
    # 封顶未授权 → 等授权
    ([{"ev": "cap_reached", "aid": A, "round": 3}], "轮次已用尽"),
])
def test_remedy_text_determinate_branches(mine, expect):
    out = RD.remedy_text([], mine, None)
    assert expect in out
    assert RD.leak_scan(out) == []


def test_yzg_golden_replay_renders_leak_free():
    """金标准回放:yzg 真机验收事实流 → 渲染稳定且零泄漏。"""
    fs = F.load_facts(FIX / "yzg_facts.jsonl")
    report = json.loads((FIX / "yzg_engine_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((FIX / "yzg_manifest.json").read_text(encoding="utf-8"))
    assert len(fs) > 100 and report["totals"]["cases"] == 26
    bad = [a for a, c in report["cases"].items() if c["status"] != "deliverable"]
    md = RD.render_delivery_report(report, fs, manifest, {})
    assert RD.leak_scan(md) == []
    for a in bad:
        title = next((str(c.get("title")) for c in manifest["cases"]
                      if str(c.get("autoid")) == a), "")
        assert (title and title in md) or f"…{a[-6:]}" in md
    assert md.count("发生了什么") == len(bad) == 3
    assert md.count("怎么判断的") == 3


# ── closing 清理契约(§11.9)+ prep 续跑还原 ──────────────────────────────────


@pytest.fixture()
def engine_env(tmp_path, monkeypatch):
    """最小引擎盘面:两案(一 deliverable 一 failed),facts/manifest/交付目录齐。"""
    B_ = "203600000000000002"
    out = tmp_path / "outputs"
    mdir = out / "b1"
    mdir.mkdir(parents=True)
    for aid in (A, B_):
        (out / aid).mkdir()
        (out / aid / "case.xlsx").write_bytes(b"fake")
    (out / A / "ask_panel.json").write_text(json.dumps({
        "conflict_shape": "expected_vs_observed", "hypothesis": "h", "ask": "?",
        "sides": [], "retrieval_receipt": []}), encoding="utf-8")
    facts_file = mdir / "facts.jsonl"
    fs = [
        {"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
        {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery", "result": "fail",
         "artifact": "a1", "volume": "vol1", "signatures": []},
        {"ev": "attribution", "aid": A, "round": 1, "run_id": "r1", "layer": "V",
         "disposition": "reflow", "fix_direction": "x", "evidence": "e"},
        {"ev": "ask_panel", "aid": A, "round": 1, "shape": "expected_vs_observed",
         "intent_signature": "sig", "ref": str(out / A / "ask_panel.json")},
        {"ev": "authored", "aid": B_, "round": 1, "artifact": sh.artifact_fingerprint(B_) or "b1:1"},
    ]
    F.append_facts(facts_file, fs)
    manifest = {"source": "b1.txt",
                "cases": [{"autoid": A, "title": "案A"}, {"autoid": B_, "title": "案B"}]}
    (mdir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                        encoding="utf-8")
    (mdir / "last_run.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: out)
    monkeypatch.setattr(sh, "facts_path", lambda s: facts_file)
    monkeypatch.setattr(sh, "manifest", lambda s: manifest)
    monkeypatch.setattr(sh, "case_rows", lambda aid: [])   # 未通过卷 xlsx 走保守分支
    return {"out": out, "mdir": mdir, "facts": facts_file, "B": B_}


def _mark_b_deliverable(env):
    """把案B 做成 deliverable:delivery pass + 三重匹配(merged volume)。"""
    B_ = env["B"]
    fs = F.load_facts(env["facts"])
    art = next(f["artifact"] for f in fs if f.get("aid") == B_ and f.get("ev") == "authored")
    F.append_facts(env["facts"], [
        {"ev": "merged", "aid": "", "volume": "vol1", "members": [B_],
         "moved_tail": [], "coexist_violations": []},
        {"ev": "verdict", "aid": B_, "run_id": "rb", "ctx": "delivery", "result": "pass",
         "artifact": art, "volume": "vol1", "signatures": []},
    ])


def test_closing_cleanup_contract_and_summary(engine_env, monkeypatch):
    env = engine_env
    _mark_b_deliverable(env)
    emitted = {}
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: emitted.update(d))
    out = N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    assert out["phase_status"] == "done"
    mdir = env["mdir"]
    # 双报告 + 机读在盘
    assert (mdir / "delivery_report.md").is_file()
    assert (mdir / "unsuccessful_cases.md").is_file()
    assert (mdir / "engine_report.json").is_file()
    # 清理契约:per-case 目录全收进批目录(通过案 delivered/ 存档——续跑重组全卷
    # 要用其 xlsx;未决案 unfinished/);facts 保留;中间件删
    assert not (env["out"] / env["B"]).exists()
    assert (mdir / "delivered" / env["B"] / "case.xlsx").is_file()
    assert (mdir / "unfinished" / A / "ask_panel.json").is_file()
    assert env["facts"].is_file()
    assert not (mdir / "manifest.json").exists()
    assert not (mdir / "last_run.json").exists()
    # 报告零泄漏
    md = (mdir / "delivery_report.md").read_text(encoding="utf-8")
    assert RD.leak_scan(md) == []
    # 收口卡:人话标签 + 对账
    assert emitted["ok"] == 1 and emitted["total"] == 2
    assert emitted["labels"] and "…" not in emitted["labels"][0]["text"]
    assert emitted["labels"][0]["text"] in RD.STATUS_CN.values()
    assert "delivery_report.md" in " ".join(emitted["files"])


def test_prep_restores_unfinished_for_resume(engine_env, monkeypatch):
    """§11.9 闭环:closing 挪走的未决案,新批 prep 还原(panel ref 等读路径复通)。"""
    env = engine_env
    _mark_b_deliverable(env)
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: None)
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    assert (env["mdir"] / "unfinished" / A).is_dir()
    assert not (env["out"] / A).exists()
    # 新批 prep(manifest 已删——monkeypatch 的 sh.manifest 仍供 counts;
    # 真实 prep 会重新 compile_prep,这里只验还原段,预置 manifest 文件)
    (env["mdir"] / "manifest.json").write_text("{}", encoding="utf-8")
    N.prep({"mindmap_path": "x.txt", "out_name": "b1"})
    assert (env["out"] / A / "ask_panel.json").is_file()   # 未决案还原,读路径复通
    assert (env["out"] / env["B"] / "case.xlsx").is_file()  # 通过案还原(重组全卷输入)
    assert not (env["mdir"] / "unfinished").exists()       # 空档已收
    assert not (env["mdir"] / "delivered").exists()


# ── 缺陷候选单持久化(P0 C20,2026-07-16):表单不再随 last_run 湮灭 ──────────────


def _dc_attribution(aid, rnd=1, form=True, **kw):
    f = {"ev": "attribution", "aid": aid, "round": rnd, "run_id": f"r{rnd}",
         "layer": "product_defect", "disposition": "defect_candidate",
         "fix_direction": "会话保持超时条目不清除(Timeout=0 仍在表)",
         "evidence": "Timeout=0 entry still present", **kw}
    if form:
        f["defect_candidate"] = {
            "repro": "配置 IPv6 会话保持并等待超时",
            "expected_with_source": "手册 §x:超时条目应清除",
            "actual": "Timeout=0 条目跨超时存活,下次落点仍命中旧池",
            "version": "10.5.0.585"}
    return f


def test_closing_emits_defect_candidates_files(engine_env, monkeypatch):
    """构造 dc 案 → closing 后批目录 defect_candidates.md/json 双文件在、表单字段全、
    进交付清单、delivery_report 提及。"""
    env = engine_env
    _mark_b_deliverable(env)
    F.append_facts(env["facts"], [_dc_attribution(A, rnd=2)])
    emitted = {}
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: emitted.update(d))
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    mdir = env["mdir"]
    assert (mdir / "defect_candidates.json").is_file()
    assert (mdir / "defect_candidates.md").is_file()
    data = json.loads((mdir / "defect_candidates.json").read_text(encoding="utf-8"))
    assert len(data) == 1 and data[0]["autoid"] == A
    form = data[0]["form"]
    assert form["repro"] and form["expected_with_source"] and form["actual"]
    assert data[0]["claims"] and "Timeout=0" in data[0]["claims"][0]["evidence"]
    md = (mdir / "defect_candidates.md").read_text(encoding="utf-8")
    assert "案A" in md and "复现步骤" in md and "预期(含出处)" in md and "实际" in md
    assert RD.leak_scan(md) == []
    # 交付清单与报告提及
    assert "defect_candidates.md" in emitted["files"]
    assert "defect_candidates.json" in emitted["files"]
    dmd = (mdir / "delivery_report.md").read_text(encoding="utf-8")
    assert "defect_candidates.md" in dmd
    rep = json.loads((mdir / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["defect_candidates"]["count"] == 1


def test_defect_candidates_floor_lists_overridden_dc(engine_env, monkeypatch):
    """N1 floor:dc@r1 被 reflow@r2 覆盖仍列入候选单,处置轨迹如实展示改判。"""
    env = engine_env
    _mark_b_deliverable(env)
    F.append_facts(env["facts"], [
        _dc_attribution(A, rnd=2),
        {"ev": "attribution", "aid": A, "round": 3, "run_id": "r3", "layer": "V",
         "disposition": "reflow", "fix_direction": "round2 缺陷已修复",
         "evidence": "some echo"},
    ])
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: None)
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    data = json.loads((env["mdir"] / "defect_candidates.json").read_text(encoding="utf-8"))
    assert len(data) == 1, "后轮弱处置不得让历史 dc 从候选单消失(517027 型)"
    trail = data[0]["disposition_trail"]
    assert [t["disposition"] for t in trail][-2:] == ["defect_candidate", "reflow"]
    md = (env["mdir"] / "defect_candidates.md").read_text(encoding="utf-8")
    assert "处置轨迹" in md and "带反馈重新编写" in md   # 改判如实可见(中文词表)


def test_no_defect_candidates_no_files(engine_env, monkeypatch):
    """无 dc 案 → 不产文件、报告无缺陷单键(零噪声)。"""
    env = engine_env
    _mark_b_deliverable(env)
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: None)
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    assert not (env["mdir"] / "defect_candidates.json").exists()
    assert not (env["mdir"] / "defect_candidates.md").exists()
    rep = json.loads((env["mdir"] / "engine_report.json").read_text(encoding="utf-8"))
    assert "defect_candidates" not in rep


# ── TUI 收口卡 ───────────────────────────────────────────────────────────────


def test_reducer_upserts_engine_summary_card():
    from main.ist_core.tui.reducer import MessageReducer
    r = MessageReducer()
    r._on_fork_cards({"payload": {"records": [{
        "event": "engine_summary", "run": "b1", "outcome": "delivered_with_labels",
        "ok": 23, "total": 26,
        "labels": [{"autoid": A, "text": "挂起(下批继续)"}],
        "report": "workspace/outputs/b1/delivery_report.md",
        "files": ["case.xlsx"], "missing": [], "ts": 1.0,
    }]}})
    snap = r.snapshot()
    idx = snap.fork_card_indices.get("engine_summary:b1")
    assert idx is not None
    payload = dict(snap.messages[idx].content[0].payload or {})
    assert payload["kind"] == "engine_summary"
    assert payload["ok"] == 23 and payload["labels"][0]["text"] == "挂起(下批继续)"


def test_ink_engine_summary_card_renders_human_words():
    from main.ist_core.ink.components.ist_app import _render_fork_card
    text = _render_fork_card({
        "kind": "engine_summary", "ok": 23, "total": 26,
        "labels": [{"autoid": A, "text": "挂起(下批继续)"}],
        "report": "workspace/outputs/b1/delivery_report.md",
        "missing": [],
    }, now=0.0)
    assert "交付完成" in text and "23" in text and "挂起(下批继续)" in text
    assert "delivery_report.md" in text
    import re as _re
    assert RD.leak_scan(_re.sub(r"\x1b\[[0-9;]*m", "", text)) == []
