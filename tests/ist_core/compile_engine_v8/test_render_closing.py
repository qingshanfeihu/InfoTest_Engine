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


# ── F-Py-3:leak_scan token 类级兜底 —— 正例(内部 token 抓)+ 反例(合法内容不抓·假阳守门) ──
# Design 强调:broaden 的风险全在假阳,反例是唯一守门,反例越充分 broaden 越安全。
def test_leak_scan_catches_internal_token_shapes():
    """正例:denylist 之外的 token-shape 内部标识被兜底抓(UPPER_SNAKE/leading-_/internal-snake/16hex)。"""
    for s in ["状态 NEEDS_USER_DECISION 未决", "落到 S_FAILED 终态",
              "见 needs_decision 台账", "读 ask_panel 面板", "last_run 记录里",
              "字段 _attribution 层", "指纹 _fail_signatures 复现",
              "needs_decision.internalfoo 钻空子",   # Design 精化:未知扩展名不豁免、仍抓
              "哈希 deadbeefcafe1234 对齐"]:
        assert RD.leak_scan(s), f"内部 token 应被抓却漏: {s!r}"


def test_leak_scan_exempts_legit_content_no_false_positive():
    """反例(假阳守门):合法内容不被抓——文件名.ext / 路径段 / 缩略语 / 中文人话(含 6 黑话+3 label)。"""
    for s in [
        "见完整报告 delivery_report.md",                 # 文件名·已知扩展名豁免
        "产出 engine_report.json 与 facts.jsonl",         # 同上
        "未通过卷 unsuccessful_cases.xlsx",               # 同上
        "落盘 needs_decision.json",                       # 内部名但作文件引用(.json)豁免
        "/Users/x/workspace/inputs/automatic_case/yzg.txt",  # 路径段(前后 /)豁免
        "用 DNS 解析", "走 HTTP/2 协议", "配置 IP 地址",    # 缩略语无下划线不匹配
        "改过程 / 改预期 / 改描述",                        # 3 label token(中文,不匹配 ASCII shape)
        "按相反顺序用 no 命令撤配置", "本轮先不做(挂起)",   # 6 黑话词(LLM-Eng 源头清,我不兜中文)
        "验证通过", "等待你的决定", "单独验证通过(待整卷复验)",  # 状态人话
    ]:
        assert RD.leak_scan(s) == [], f"合法内容误报(假阳): {s!r} → {RD.leak_scan(s)}"


def test_leak_scan_code_fence_exempts_device_echo():
    """code fence 内设备回显豁免不变(内部 token 在 ``` 内不算泄漏)。"""
    fenced = "结果:\n```\nNEEDS_USER_DECISION last_run _attribution\n```\n完成"
    assert RD.leak_scan(fenced) == []


# ── F-Py-8:断言极性照抄先例 flag(Design 定案·机械做来源/不判极性语义对错) ──────────────────────
def test_precedent_sourced_assertions_flags_by_source_only():
    """机械 flag source.kind=precedent 的断言(照抄先例语法候选);intent/manual/emit_auto 不 flag。"""
    prov = {"steps": [{"F": "found", "source": {"kind": "precedent", "ref": "precedent:203000000000000001"}},
                      {"F": "not_found", "source": {"kind": "emit_auto", "ref": ""}},
                      {"F": "found", "source": {"kind": "intent", "ref": "intent"}}]}
    flagged = RD.precedent_sourced_assertions(prov)
    assert len(flagged) == 1 and flagged[0]["F"] == "found"      # 只 precedent 那条被 flag
    assert RD.precedent_sourced_assertions(
        {"steps": [{"F": "found", "source": {"kind": "manual", "ref": "m"}}]}) == []   # manual 不 flag


def test_precedent_flag_does_not_judge_polarity_correctness():
    """★Design 命门:helper **只标来源、绝不判极性语义对错**——precedent 断言不论极性方向对错都只
    flag(极性对错=语义、留上机 oracle 判,机械不碰;防将来给 flag 加'极性对齐机械判'做成假门)。"""
    # 极性方向"对本案意图错"的 precedent 断言:仍只 flag、helper 不机械判它错、不拒
    wrong_polarity = {"steps": [{"F": "not_found", "source": {"kind": "precedent", "ref": "p:x"}}]}
    assert RD.precedent_sourced_assertions(wrong_polarity)       # 被 flag(标来源)
    # 极性方向"恰对"的 precedent 断言:同样只 flag(不因"对"就不标)——一致标来源,不判对错
    right_polarity = {"steps": [{"F": "found", "source": {"kind": "precedent", "ref": "p:y"}}]}
    assert RD.precedent_sourced_assertions(right_polarity)       # 也被 flag(对/错都标=只标来源)


def test_precedent_polarity_flags_render_as_audit_note_not_reject():
    """F-Py-8 closing 报告标注:precedent_polarity_flags 渲染为审计标注(供复核抽查来源),
    **非拒卷**——outcome 不被标注改写(delivered_all_pass 保持)、渲染人话+用例标题、零 token 泄漏。"""
    report = {"engine": "v8", "outcome": "delivered_all_pass",
              "totals": {"cases": 1, "deliverable": 1}, "volume": "v",
              "moved_tail": [], "coexist_violations": [],
              "cases": {A: {"status": "deliverable", "artifact": "a1", "rounds": 1}},
              "precedent_polarity_flags": [{"autoid": A, "count": 2}]}
    manifest = {"source": "t.txt", "cases": [{"autoid": A, "title": "SDNS 示例用例"}]}
    md = RD.render_delivery_report(report, [], manifest, {}, {})
    assert "断言极性照抄先例" in md and "供复核抽查" in md   # 标注渲染(人话)
    assert "SDNS 示例用例" in md                              # 用例标题(非机读 autoid)
    assert report["outcome"] == "delivered_all_pass"         # 非拒卷:outcome 不被标注改写
    assert RD.leak_scan(md) == [], RD.leak_scan(md)          # 标注零 token 泄漏(复用 leak_scan)


def test_batch_name_strips_absolute_path_no_home_leak():
    """F-Py-10:交付物标题只显批名(source 主干),不露绝对本地路径/home/用户名/冗长目录。"""
    assert RD._batch_name({"source": "/home/ci/proj/inputs/automatic_case/yzg.txt"}) == "yzg"
    assert RD._batch_name({"source": "yzg"}) == "yzg"                 # 已是批名
    assert RD._batch_name({"source": "/a/b/test.case.txt"}) == "test.case"   # 只去末扩展名
    assert RD._batch_name({"source": ""}, {"batch": "fb"}) == "fb"    # 空回落 report.batch
    manifest = {"source": "/home/ci/proj/inputs/automatic_case/yzg.txt",
                "cases": [{"autoid": A, "title": "示例用例"}]}
    report = {"engine": "v8", "outcome": "delivered_all_pass",
              "totals": {"cases": 1, "deliverable": 1}, "volume": "v",
              "moved_tail": [], "coexist_violations": [], "cases": {A: {"status": "deliverable"}}}
    md = RD.render_delivery_report(report, [], manifest, {}, {})
    assert md.splitlines()[0] == "# 交付报告 — yzg"                   # 批名精确(无路径/扩展名)
    assert "/home/" not in md and "/inputs/" not in md               # 全文无绝对路径泄漏


def test_case_section_shows_tail_number_for_recognition():
    """F-Py-7(短号·A 配套):交付物 _case_section 编号行=18位 autoid +(尾号 后6位)——用户
    记忆里是短号(如 655233)、18位长号认不出(User 21:21);18位保留供框架 dev_run_batch
    canonical 匹配。render_delivery_report(bad案)与 render_unsuccessful_md 同享 _case_section。"""
    report = {"engine": "v8", "outcome": "delivered_with_labels",
              "totals": {"cases": 1, "deliverable": 0}, "volume": "v",
              "moved_tail": [], "coexist_violations": [],
              "cases": {A: {"status": "contradicted", "artifact": "a1", "rounds": 1}}}
    manifest = {"source": "t.txt", "cases": [{"autoid": A, "title": "示例用例"}]}
    md = RD.render_delivery_report(report, [], manifest, {}, {})
    assert f"编号 `{A}`(尾号 {A[-6:]})" in md          # 18 位 canonical + 尾号 辨识 并存
    umd = RD.render_unsuccessful_md(report, [], manifest, {}, {}, {})
    assert f"(尾号 {A[-6:]})" in umd                    # 未通过详报同享 _case_section


def test_suspended_reason_split_no_answer_vs_other():
    """F-Py-5①(会签初衷走渲染层·不改状态机):suspended 按 reason 分流——decision 类未答
    (auto:{panel/cap/env/contra}:)显「未作答」;★bed 未答(auto:bed:,床治理待外部 §11.7 语义
    独立)、改描述/欠定挂起显「挂起」。qid 前缀=kind,白名单贯彻 bed 独立到渲染(Design 增量审 F 修)。"""
    # decision 类未作答(panel/cap/env/contra)→「未作答」
    for k in ("panel", "cap", "env", "contra"):
        na = [{"ev": "suspended", "aid": A, "reason": f"auto:{k}:{A}:1"}]
        assert RD._no_answer_suspended(na), k
        assert RD._status_cn("suspended", na) == "未作答(下批会再次问你)"
    # ★bed 未答(auto:bed:)=床治理待外部处理(§11.7 独立)→显「挂起」不是「未作答」(防回归锚)
    bed = [{"ev": "suspended", "aid": A, "reason": f"auto:bed:{A}:1"}]
    assert not RD._no_answer_suspended(bed)
    assert RD._status_cn("suspended", bed) == RD.STATUS_CN["suspended"]        # 挂起,非未作答
    # 改描述/欠定挂起(非 auto:)→「挂起」
    other = [{"ev": "suspended", "aid": A, "reason": "user_decision:改描述"}]
    assert not RD._no_answer_suspended(other)
    assert RD._status_cn("suspended", other) == RD.STATUS_CN["suspended"]
    # 详报:decision 类未作答案状态行显「未作答」
    report = {"engine": "v8", "outcome": "delivered_with_labels",
              "totals": {"cases": 1, "deliverable": 0}, "volume": "v",
              "moved_tail": [], "coexist_violations": [],
              "cases": {A: {"status": "suspended", "rounds": 1}}}
    manifest = {"source": "t.txt", "cases": [{"autoid": A, "title": "示例"}]}
    md = RD.render_delivery_report(report, [{"ev": "suspended", "aid": A, "reason": f"auto:panel:{A}:1"}],
                                   manifest, {}, {})
    assert "未作答" in md and "编号" in md


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


def test_delivery_overwrite_detected_next_closing(engine_env, monkeypatch):
    """F-Py-7 A-加固对账(手工覆盖·事后检测):上轮 engine_report.json 有 delivery_stamp_ts,交付物
    mtime>stamp+ε → 本轮 closing START 检出手工覆盖(delivery_overwritten 事实);ε 容差内 +
    facts.jsonl(跨轮 append 排除)不误判;closing END 重打 stamp。滞后一轮(prompt 主防线外纵深)。"""
    import os
    env = engine_env
    _mark_b_deliverable(env)
    mdir = env["mdir"]
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: None)
    T0 = 1000.0
    (mdir / "engine_report.json").write_text(json.dumps({"delivery_stamp_ts": T0}), encoding="utf-8")
    (mdir / "unsuccessful_cases.md").write_text("overwritten", encoding="utf-8")
    os.utime(mdir / "unsuccessful_cases.md", (T0 + 100, T0 + 100))   # >stamp+ε=手工覆盖
    (mdir / "delivery_report.md").write_text("x", encoding="utf-8")
    os.utime(mdir / "delivery_report.md", (T0 + 1, T0 + 1))          # <stamp+ε=容差内不误判
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    fs2 = F.load_facts(env["facts"])
    ov = [f for f in fs2 if f.get("ev") == "delivery_overwritten"]
    assert ov and "unsuccessful_cases.md" in ov[-1]["files"]         # 覆盖检出
    assert "delivery_report.md" not in ov[-1]["files"]              # ε 容差内不误判
    assert "facts.jsonl" not in ov[-1]["files"]                     # ★facts.jsonl 排除不误判(跨轮 append)
    rep2 = json.loads((mdir / "engine_report.json").read_text(encoding="utf-8"))
    assert float(rep2.get("delivery_stamp_ts") or 0) > T0           # closing END 重打 stamp


def test_delivery_no_false_overwrite_fresh_batch(engine_env, monkeypatch):
    """F-Py-7:首跑批次(无上轮 delivery_stamp_ts)不检测——零 delivery_overwritten 误报。"""
    env = engine_env
    _mark_b_deliverable(env)
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: None)
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    fs2 = F.load_facts(env["facts"])
    assert not [f for f in fs2 if f.get("ev") == "delivery_overwritten"]


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


def test_p1_11_closing_tick_fires_before_manifest_delete(engine_env, monkeypatch):
    """P1-11 收尾 footer 真值断言:emit_tick(closing) 必须在 §11.9 删 manifest.json 之前发。
    原 bug:emit_tick 在删 manifest 之后→batch_view(fs, manifest={})→aids=[]→counts 全 0
    →footer 收尾恒显 0/0。断言:emit_tick(closing) 触发时 manifest.json 磁盘文件仍在,
    且此刻真 counts 非空(两案)。修法回退(tick 移回节点尾)则 manifest 已删→本测试红。"""
    env = engine_env
    _mark_b_deliverable(env)
    mdir = env["mdir"]
    seen = {}
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: None)

    def spy_tick(state, phase, fs=None):
        if phase == "closing":
            seen["manifest_on_disk"] = (mdir / "manifest.json").is_file()
            seen["total"] = len(sh.view(state, fs)["cases"])
    monkeypatch.setattr(sh, "emit_tick", spy_tick)

    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    assert seen.get("manifest_on_disk") is True   # tick 在删 manifest 之前(P1-11 修的核心)
    assert seen.get("total") == 2                  # 真值(两案),非 0/0
