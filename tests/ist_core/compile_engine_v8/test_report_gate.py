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
    """B 案缺 τ:G3 封堵后 engine_report 的 cases/totals/头行三方自洽,G5 零误报。
    H-16 后:fold 消费 delivery_blocked(views.case_status → S_PENDING 回炉重编),
    closing 重算视图替代手改标签——报告状态=S_PENDING(下批重编补自清),不再是
    fold 外第 13 状态 "delivery_blocked";事实照常入账(report_gate 侧 honor 不动)。"""
    monkeypatch.setattr(N, "_load_case_rows",
                        lambda aid: _POLLUTER_ROWS if aid == B else [])
    emitted = {}
    monkeypatch.setattr(sh, "emit_summary", lambda s, d: emitted.update(d))
    N.closing({"out_name": "b1", "facts_ref": "", "manifest_ref": ""})
    mdir = engine_env["mdir"]
    rep = json.loads((mdir / "engine_report.json").read_text(encoding="utf-8"))
    assert rep["cases"][B]["status"] == "pending"      # fold 派生回炉态,非手改标签
    assert rep["totals"]["deliverable"] == 1
    assert rep["totals"]["pending"] == 1
    fs = F.load_facts(engine_env["facts"])
    assert any(f.get("ev") == "delivery_blocked" and f.get("aid") == B for f in fs)
    # 下批路由真实消费:封堵案派生 S_PENDING → author 重派集(兑现重编补自清)
    from main.ist_core.compile_engine_v8 import views as V
    assert V.batch_view(fs, {"cases": [{"autoid": A}, {"autoid": B}]}
                        )["cases"][B]["status"] == V.S_PENDING
    md = (mdir / "delivery_report.md").read_text(encoding="utf-8")
    assert "本批 2 个用例:**1 个通过整卷复验" in md
    assert "案尾清理" in md            # G3 案在报告里如实解释(去向行消费 delivery_blocked 事实)
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


# ── F-1/G5:未答呈报按 question_id 配对(批3 yzg 668 族门层同源分叉) ──────────────


def test_recount_g5_withdraws_on_second_unanswered_decision():
    """同案二次欠定:round1 已答 + round2 未答。旧口径「有 needs_decision 且无任意
    decision」因 any(decision)==True 漏放行未上机卷;按 question_id 配对(H2)才挡住。
    这是 views.case_status 已修的 H2 在 G5 独立重算路径的同口径义务(双路不得漂移)。"""
    q1 = f"nd:{A}:1:forbidden_mechanism"
    q2 = f"nd:{A}:2:verification_path_absent"
    fs = _delivered_facts() + [
        {"ev": "needs_decision", "aid": A, "question_id": q1},
        {"ev": "decision", "aid": A, "question_id": q1, "answer": "改过程"},
        {"ev": "needs_decision", "aid": A, "question_id": q2},   # 未答
    ]
    assert RG.recount_deliverable(fs, MANIFEST)["deliverable"] == set()


def test_recount_g5_all_answered_still_deliverable():
    """对照(防过修):两轮欠定都已答→question_id 全配对→残留 needs_decision 不误挡。
    旧口径唯一正确处=全答案的案放行,新口径必须仍放行。"""
    q1 = f"nd:{A}:1:forbidden_mechanism"
    q2 = f"nd:{A}:2:verification_path_absent"
    fs = _delivered_facts() + [
        {"ev": "needs_decision", "aid": A, "question_id": q1},
        {"ev": "decision", "aid": A, "question_id": q1, "answer": "x"},
        {"ev": "needs_decision", "aid": A, "question_id": q2},
        {"ev": "decision", "aid": A, "question_id": q2, "answer": "y"},
    ]
    assert RG.recount_deliverable(fs, MANIFEST)["deliverable"] == {A}


# ── D31:escalated 解除感知(recount 与 case_status 同口径;zhaiyq 516389/533097 实弹) ──────


def test_recount_escalated_then_authored_is_deliverable_D31():
    """D31 红绿(zhaiyq 516389/533097):escalated 在 authored **之前**(fork 墙钟超时→迟到回收卷
    /reflow 重编 supersede)→ 交付有事实支撑。修前无条件 `any(escalated)` 丢=set()(红,与
    case_status 的 run18 解除漂移致 G5 自我误告警);修后 `last_esc<last_auth` 解除→{A}(绿)。"""
    fs = [{"ev": "escalated", "aid": A, "reason": "no output from fork"}] + _delivered_facts()
    assert RG.recount_deliverable(fs, MANIFEST)["deliverable"] == {A}


def test_recount_escalated_after_authored_still_withdrawn_D31():
    """对照(防过修):escalated 在 authored **之后**(未被后续 authored 解除)→ 仍是终态、丢。
    保证 D31 修法只救「被 supersede 的 escalated」,不放行真·升级案。"""
    fs = _delivered_facts() + [{"ev": "escalated", "aid": A, "reason": "genuine escalation"}]
    assert RG.recount_deliverable(fs, MANIFEST)["deliverable"] == set()


def test_recount_matches_case_status_all_lifecycle_branches_D31():
    """★宪法级同口径守门(D31 定谳:同族二犯根因=双路独立实现无机器等价校验,一路修 bug、
    另一路必漂;门内注释「独立重算两条路径必须同口径,否则 G5 报告门自我误告警」早已预言)。
    合成事实流穷举 leader/Theory/Design 点名排除态转换全枝(escalated 解除/终态、suspended
    解除/终态、二次欠定 qid 配对、终局裁决 round99、未答呈报、clean),**双重断言**:recount 与
    case_status(S_DELIVERABLE) 逐案一致(两路等价)∧ 各自命中 ground-truth(防两路同错都绿)。

    **覆盖纪律(给未来编辑者)**:任一路(recount_deliverable / views.case_status)新增排除
    状态,**必须同 commit** 在此加对应等价 fixture case,否则守门形同虚设——G5→D31 二犯真因
    正是 fixture 没盖 escalated 解除枝(机制在、fixture 缺,pytest 照绿),漂移无人拦。"""
    from main.ist_core.compile_engine_v8 import views as V

    CLEAN, ESC_R, ESC_T = "203600000000000010", "203600000000000011", "203600000000000012"
    SUS_T, TERM, AWAIT = "203600000000000013", "203600000000000014", "203600000000000015"
    SUS_R, REDEC = "203600000000000016", "203600000000000017"
    DBLK, DBLK_R = "203600000000000018", "203600000000000019"

    def base(aid):   # authored + delivery pass(卷/指纹一致 v1)
        return [{"ev": "authored", "aid": aid, "round": 1, "artifact": aid + ":a"},
                {"ev": "verdict", "aid": aid, "run_id": "r", "ctx": "delivery",
                 "result": "pass", "artifact": aid + ":a", "volume": "v1", "signatures": []}]

    fs = []
    fs += base(CLEAN)                                                            # clean → deliverable
    fs += [{"ev": "escalated", "aid": ESC_R, "reason": "no output"}] + base(ESC_R)  # escalated 解除(esc<auth)
    fs += base(ESC_T) + [{"ev": "escalated", "aid": ESC_T, "reason": "x"}]       # escalated 终态(esc>auth)
    fs += base(SUS_R) + [{"ev": "suspended", "aid": SUS_R, "reason": "q"},
                         {"ev": "resumed", "aid": SUS_R, "of": "x"}]             # suspended 解除(resume>susp)→deliverable
    fs += base(SUS_T) + [{"ev": "suspended", "aid": SUS_T, "reason": "q"}]       # suspended 终态
    fs += base(TERM) + [{"ev": "attribution", "aid": TERM, "round": 99,
                         "disposition": "defect_candidate"}]                     # 终局裁决(round99 三处置之一)
    fs += base(AWAIT) + [{"ev": "needs_decision", "aid": AWAIT,
                          "question_id": "nd:x:1:k"}]                             # 单次未答呈报
    fs += base(REDEC) + [                                                        # 二次欠定 qid 配对(G5 首犯分叉点)
        {"ev": "needs_decision", "aid": REDEC, "question_id": "nd:d:1:k"},
        {"ev": "decision", "aid": REDEC, "question_id": "nd:d:1:k", "answer": "改过程"},
        {"ev": "needs_decision", "aid": REDEC, "question_id": "nd:d:2:v"}]       # r1 已答+r2 未答→NOT
    # G3 封堵枝(H-16 新增排除态,同 commit 按本族纪律补 fixture):封堵→NOT;
    # 封堵后重编复验通过(新 authored+新 delivery pass 在封堵之后)→deliverable
    fs += base(DBLK) + [{"ev": "delivery_blocked", "aid": DBLK, "run_id": "g3"}]
    fs += (base(DBLK_R) + [{"ev": "delivery_blocked", "aid": DBLK_R, "run_id": "g3"},
                           {"ev": "authored", "aid": DBLK_R, "round": 2,
                            "artifact": DBLK_R + ":b"},
                           {"ev": "verdict", "aid": DBLK_R, "run_id": "r2",
                            "ctx": "delivery", "result": "pass",
                            "artifact": DBLK_R + ":b", "volume": "v1",
                            "signatures": []}])
    all_aids = [CLEAN, ESC_R, ESC_T, SUS_R, SUS_T, TERM, AWAIT, REDEC, DBLK, DBLK_R]
    fs += [{"ev": "merged", "aid": "", "volume": "v1", "ctx": "delivery", "members": all_aids}]
    manifest = {"source": "t.txt", "cases": [{"autoid": a} for a in all_aids]}

    rc = RG.recount_deliverable(fs, manifest)["deliverable"]
    bv = V.batch_view(fs, manifest)
    cs = {aid for aid, c in bv["cases"].items() if c["status"] == V.S_DELIVERABLE}
    assert rc == cs, f"两路漂移(G5 自我误告警根因):recount={sorted(rc)} case_status={sorted(cs)}"
    # 双重断言:除两路等价,再钉 ground-truth——防两路同错都绿(解除态 escalated/suspended + clean 可交付)
    assert rc == {CLEAN, ESC_R, SUS_R, DBLK_R}, \
        f"ground-truth 不符:期望 clean+两类解除+封堵重编复验,实得 {sorted(rc)}"
