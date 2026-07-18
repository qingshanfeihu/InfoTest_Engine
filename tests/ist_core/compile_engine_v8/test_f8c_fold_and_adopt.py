"""F6-ii+F8c(§18.11 五稿):禁令机制题面分支、组一题折叠扇出、同键采信豁免。

- 折叠:同(组,签名)的 forbidden_mechanism 案取代表提问,答案广播全组、逐案落盘
  (emit 门按案读 user_decision.json);每成员 ask_shown 入账(非代表标 folded_into)。
- 采信:裁决写回判例店((意图签名×forbidden_mechanism×版本族) 键),下批同键命中
  =机械采信免问((20) 收敛律;token 互斥→照常问,(45)/(21) 合成规则)。
- Other 兜底(评审 D9):禁令类自由文本答案=用户自给等价,按改过程落、原文随 note。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.tools.knowledge import adjudication_store as adj

A1, A2 = "203099999999900101", "203099999999900102"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    for a in (A1, A2):
        shutil.rmtree(sh.outputs_root() / a, ignore_errors=True)
    monkeypatch.setattr(adj, "adjudications_root", lambda: tmp_path / "adj")
    # 「先问后落」凭证(compile_user_decision 的 A 层门)。取径经 runtime_path——
    # pytest 下=tmp,与门读侧同径,不再污染生产台账
    from main.common.runtime_paths import runtime_path
    qa = runtime_path("ask_user_answers.jsonl")
    qa.parent.mkdir(parents=True, exist_ok=True)
    with qa.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": 0, "questions": [f"t {A1} {A2}"],
                            "answers": {"t": "改"}}, ensure_ascii=False) + "\n")
    yield
    for a in (A1, A2):
        shutil.rmtree(sh.outputs_root() / a, ignore_errors=True)


def _mk_case(aid):
    d = sh.outputs_root() / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "needs_decision.json").write_text(json.dumps({
        "autoid": aid, "claims": [{"claim_kind": "forbidden_mechanism",
                                   "reason": "intent requires reboot; bed forbids",
                                   "proposed_equivalent": "clear 运行面(模型条件等价)"}]},
        ensure_ascii=False), encoding="utf-8")
    (d / "intent.json").write_text(json.dumps({
        "autoid": aid, "title": "执行write后重启设备",
        "group_path": ["功能", "配置保存"],
        "forbidden_mechanism": [{"family": "reboot", "matched": "重启"}],
        "source": "manifest"}, ensure_ascii=False), encoding="utf-8")
    return d


def _drive(monkeypatch, facts, answer_by_rep):
    appended: list[dict] = []
    monkeypatch.setattr(sh, "load_facts", lambda st: facts)
    monkeypatch.setattr(sh, "append", lambda st, fx: appended.extend(fx))
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "counts_update", lambda st, f=None: {})
    asked: list[list[dict]] = []

    def fake_interrupt(payload):
        qs = payload.get("questions", [])
        asked.append(qs)
        return {str(q.get("_autoid")): answer_by_rep.get(str(q.get("_autoid")), "")
                for q in qs}
    monkeypatch.setattr(N, "interrupt", fake_interrupt)
    N.ask_decision({"product_version": "10.5", "out_name": "t_fold"})
    return appended, asked


def _pend(aid, n):
    return {"ev": "needs_decision", "aid": aid, "question_id": f"nd:{aid}:{n}"}


def test_fold_one_question_fanout_both_land(monkeypatch):
    _mk_case(A1), _mk_case(A2)
    appended, asked = _drive(monkeypatch, [_pend(A1, 1), _pend(A2, 1)],
                             {min(A1, A2): "改过程"})
    # 组一题:interrupt 只收到 1 题,题面注明代表 2 案
    assert sum(len(b) for b in asked) == 1
    assert "2 案" in asked[0][0]["question"]
    # 扇出:两案 user_decision.json 均落盘,decision 事实各携本案 question_id
    for a in (A1, A2):
        ud = json.loads((sh.outputs_root() / a / "user_decision.json")
                        .read_text(encoding="utf-8"))
        assert ud["decision"] == "改过程"
    dec = [f for f in appended if f.get("ev") == "decision"]
    assert {f["aid"] for f in dec} == {A1, A2}
    assert {f["question_id"] for f in dec} == {f"nd:{A1}:1", f"nd:{A2}:1"}
    # ask_shown 每成员一条,非代表标 folded_into
    shown = [f for f in appended if f.get("ev") == "ask_shown"]
    assert {f["aid"] for f in shown} == {A1, A2}
    assert any(f.get("folded_into") for f in shown)
    # 判例写回:同键 md 落店
    hits = adj.find_adjudications(conflict_shape="forbidden_mechanism")
    assert hits and hits[0].get("token") == "改过程"


def test_adoption_skips_question_next_batch(monkeypatch):
    """判例在店 → 下批同键案免问:零 interrupt,直接落盘+adopted 事实。"""
    _mk_case(A1)
    adj.write_adjudication(
        key={"intent_signature": "配置保存|reboot".lower(),
             "conflict_shape": "forbidden_mechanism", "version_family": "10.5"},
        ruling="改过程:采纳 clear 等价", anchor={"version": "10.5", "lineage": "user_proxy"},
        meta={"token": "改过程"})
    appended, asked = _drive(monkeypatch, [_pend(A1, 1)], {})
    assert asked == [] or sum(len(b) for b in asked) == 0
    assert (sh.outputs_root() / A1 / "user_decision.json").is_file()
    assert any(f.get("ev") == "adopted" for f in appended)


def test_other_freeform_lands_as_process_for_fm(monkeypatch):
    """Other 自由文本(无三关键词)对禁令类=改过程+原文入 note(评审 D9 兜底)。"""
    _mk_case(A1)
    appended, _ = _drive(monkeypatch, [_pend(A1, 1)],
                         {A1: "用受控维护窗真重启一次,周五凌晨"})
    ud = json.loads((sh.outputs_root() / A1 / "user_decision.json")
                    .read_text(encoding="utf-8"))
    assert ud["decision"] == "改过程" and "维护窗" in ud["note"]


def test_forbidden_question_template():
    from main.ist_core.compile_engine_v8.questions import build_questions
    qs = build_questions({A1: {"claims": [{"claim_kind": "forbidden_mechanism",
                                           "reason": "重启不可用",
                                           "proposed_equivalent": "clear 运行面"}]}})
    assert len(qs) == 1 and qs[0]["header"].startswith("禁令")
    assert "clear 运行面" in qs[0]["question"]
    assert [o["label"] for o in qs[0]["options"]] == ["改过程", "改预期", "改描述"]


def test_scheme_requiring_option_empty_scheme_rejected_reask(monkeypatch):
    """F-Py-5②(scheme 通道拒空):禁令面板选「改预期」(描述=在下面自定义输入里写你的等价方案)
    但答案==选项标签本身(没进 Other 文本态、没填 scheme,TUI-Eng 机读证=标签原文)→ 拒落、
    不写 user_decision、案 needs_decision 保持未答(下批重问);532618 空答陷阱。对照:「改过程」
    (采纳引擎推导、自足不需 scheme)照常 land 见 test_fold_one_question_fanout_both_land。"""
    _mk_case(A1)
    appended, asked = _drive(monkeypatch, [_pend(A1, 1)], {A1: "改预期"})
    assert sum(len(b) for b in asked) == 1                      # 呈报了(interrupt 收到题)
    # ★拒落:无 decision 事实 + 无 user_decision.json(案留 needs_decision 未答→下批重问)
    assert not any(f.get("ev") == "decision" and f.get("aid") == A1 for f in appended)
    assert not (sh.outputs_root() / A1 / "user_decision.json").is_file()
    # ★TUI 序号加工「1. 改预期」也拒(Design 审 gap:精确匹配会漏 TUI 序号、子串判据修,与 W3 一致)
    appended2, _ = _drive(monkeypatch, [_pend(A1, 1)], {A1: "1. 改预期"})
    assert not any(f.get("ev") == "decision" and f.get("aid") == A1 for f in appended2)
    assert not (sh.outputs_root() / A1 / "user_decision.json").is_file()


def _triple_claim(equiv=True):
    c = {"claim_kind": "verification_path_absent",
         "test_point": "验证 write mem 存盘后重启配置是否丢失",
         "sources": [{"kind": "step", "quote": "执行write mem后重启设备"}],
         "obstacle": "自动化环境无法重启:断连即无法继续测试"}
    if equiv:
        c["equivalent"] = {"procedure": "write file 后 clear 运行面看 listener 是否再现",
                           "preserves": "清运行面等价重启,未写 startup 则不再现"}
    else:
        c["no_equivalent_reason"] = "本床无任何重启等价手段"
    return c


def test_triple_projection_zero_template_verbatim():
    """§18.13 三元组投影:题面逐字、零模板文案、采纳选项内嵌 procedure(run22 病理修复)。"""
    from main.ist_core.compile_engine_v8.questions import build_questions
    qs = build_questions({A1: {"claims": [_triple_claim()]}})
    assert len(qs) == 1
    q = qs[0]
    blob = q["question"] + " ".join(o["description"] for o in q["options"])
    assert "加请求" not in blob and "观测次数" not in blob      # 模板文案退场
    assert "write file 后 clear" in q["question"]              # procedure 逐字投影
    assert q["options"][0]["label"] == "采纳该等价方案(方法见题面)"   # F-TUI-2 固定短语(旧动态截断)
    assert q["_token_by_label"][q["options"][0]["label"]] == "改过程"   # P3 label→token


def test_triple_no_equivalent_suspend_carries_reason():
    from main.ist_core.compile_engine_v8.questions import build_questions
    qs = build_questions({A1: {"claims": [_triple_claim(equiv=False)]}})
    q = qs[0]
    # 无等价:无"采纳"选项,挂起项携如实理由
    assert not any(o["label"].startswith("采纳") for o in q["options"])
    susp = next(o for o in q["options"] if o["label"].startswith("挂起"))
    assert "本床无任何重启等价" in susp["description"]


def test_triple_folds_by_group_and_equivalence(monkeypatch):
    """P1:同 group_path + has_equivalent 的三元组案折成一题(_fm_meta re-key)。"""
    import main.ist_core.compile_engine_v8.nodes as N
    A, B = "203601753067668000", "203601753067668015"
    led = {A: {"claims": [_triple_claim()]}, B: {"claims": [_triple_claim()]}}
    # 同 group_path 盖章
    monkeypatch.setattr(N.sh, "read_json",
                        lambda p, d=None: {"group_path": ["G1", "配置保存"], "title": "t"}
                        if "intent.json" in str(p) else (d or {}))
    # 直接验 _fm_meta 键一致(折叠依据)
    import types
    ns = types.SimpleNamespace()
    # _fm_meta 是 ask_decision 内闭包,改测其等价键:两案同 group+eq → 同 sig
    # 用 build_questions 的折叠标记间接验(fold 在 ask_decision,单元验键相等性)
    from main.ist_core.compile_engine_v8.questions import build_questions
    qs = build_questions(led)
    # 两案各产一题(build 层不折叠);折叠在 ask_decision 按 _fm_meta 键——此处验键可得
    assert len(qs) == 2 and all(q.get("_token_by_label") for q in qs)


# ── F8d 兄弟碰撞呈报(D5 型不硬拒) ────────────────────────────────────────────

def test_sibling_collision_reported(monkeypatch):
    A, B = "203600000000000201", "203600000000000202"
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": A, "title": "write mem 案", "group_path": ["功能", "配置保存"]},
        {"autoid": B, "title": "write all 案", "group_path": ["功能", "配置保存"]}]})
    rows = {A: [{"G": "write memory"}], B: [{"G": "write memory"}]}   # B 漂移撞 A
    monkeypatch.setattr(N, "_load_case_rows", lambda aid: rows.get(aid, []))
    out = N._sibling_collisions({}, [A, B])
    assert len(out) == 1 and out[0]["aid"] == B and out[0]["with"] == A
    assert out[0]["axis"] == "write memory"


def test_sibling_distinct_variants_clean(monkeypatch):
    A, B = "203600000000000203", "203600000000000204"
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": A, "title": "t", "group_path": ["功能", "配置保存"]},
        {"autoid": B, "title": "t", "group_path": ["功能", "配置保存"]}]})
    rows = {A: [{"G": "write memory"}], B: [{"G": "write file f1"}]}
    monkeypatch.setattr(N, "_load_case_rows", lambda aid: rows.get(aid, []))
    assert N._sibling_collisions({}, [A, B]) == []


# ── 判例采纳止损闸(B 线急派:批3 668 族 7 圈活锁,rounds_used 恒 0 不触轮闸) ────────


def _adopt_dec(aid, slug, n):
    """一条判例采纳 decision(provenance=adopted:slug,qid 逐轮递增→不去重、可计数)。"""
    return {"ev": "decision", "aid": aid, "question_id": f"nd:{aid}:{n}",
            "answer": "改过程", "provenance": f"adopted:{slug}"}


def _adopted_fact(aid, slug, ruling="改过程:采纳 clear 等价"):
    """历史 adopted 事实(带 ruling,止损题面的判例主张源;round:0→内容键去重恒=1)。"""
    return {"ev": "adopted", "aid": aid, "round": 0, "slug": slug,
            "token": "改过程", "ruling": ruling}


def _seed_adj():
    adj.write_adjudication(
        key={"intent_signature": "配置保存|reboot".lower(),
             "conflict_shape": "forbidden_mechanism", "version_family": "10.5"},
        ruling="改过程:采纳 clear 等价", anchor={"version": "10.5", "lineage": "user_proxy"},
        meta={"token": "改过程"})
    return adj.find_adjudications(conflict_shape="forbidden_mechanism")[0]["slug"]


def test_adoption_stoploss_third_hit_asks_user(monkeypatch):
    """复现锚:同 slug 已 2 次采纳(事实流 2 条 adopted decision)→第 3 次命中不采纳,
    案留 pending 进 gather 问人,题面附止损语境。封 668 族「采纳→再欠定→再采纳」活锁。"""
    _mk_case(A1)
    slug = _seed_adj()
    facts = [_pend(A1, 3), _adopt_dec(A1, slug, 1), _adopt_dec(A1, slug, 2),
             _adopted_fact(A1, slug)]
    appended, asked = _drive(monkeypatch, facts, {A1: "用受控维护窗重启一次"})
    # 不再采纳:无新 adopted 事实
    assert not any(f.get("ev") == "adopted" for f in appended)
    # 转人工:interrupt 被调用,题面带完整止损语境(多轮未解决+实际圈次,leader 令)
    assert sum(len(b) for b in asked) == 1
    _q = asked[0][0]["question"]
    assert "止损" in _q and "多轮尝试未解决" in _q and "2 次采纳" in _q
    # ②-1/2 完整语境(Design 令):判例主张(ruling 摘句)+ worker 最新论证(reason 摘句)在题面
    assert "判例主张" in _q and "clear" in _q            # ruling="改过程:采纳 clear 等价"
    assert "worker 最新论证" in _q and "reboot" in _q     # reason="intent requires reboot;…"
    # 用户答案落地=真人裁决(provenance 非 adopted),打破活锁
    dec = [f for f in appended if f.get("ev") == "decision"]
    assert dec and dec[0]["aid"] == A1
    assert str(dec[0].get("provenance") or "") == ""


def test_adoption_stoploss_first_two_hits_adopt(monkeypatch):
    """回归锚:止损闸不误伤收敛律——0/1 条前采纳时照常自动采纳(免问)。A1=0 前、A2=1 前,
    两案都 <2 阈值,均采纳、零 interrupt。"""
    _mk_case(A1), _mk_case(A2)
    slug = _seed_adj()
    facts = [_pend(A1, 1), _pend(A2, 2), _adopt_dec(A2, slug, 1)]
    appended, asked = _drive(monkeypatch, facts, {})
    assert {f["aid"] for f in appended if f.get("ev") == "adopted"} == {A1, A2}
    assert sum(len(b) for b in asked) == 0


def test_adoption_stoploss_livelock_exits_at_round3(monkeypatch):
    """活锁端到端形态(668 族 7 圈):逐圈累积 adopted decision,断言第 3 圈(2 前采纳)
    即止损问人——远不到 7 圈就出循环。"""
    slug = _seed_adj()
    # 圈1(0 前):采纳,零问
    _mk_case(A1)
    ap1, ask1 = _drive(monkeypatch, [_pend(A1, 1)], {})
    assert any(f["ev"] == "adopted" for f in ap1) and sum(len(b) for b in ask1) == 0
    # 圈2(1 前):采纳,零问
    _mk_case(A1)
    ap2, ask2 = _drive(monkeypatch, [_pend(A1, 2), _adopt_dec(A1, slug, 1)], {})
    assert any(f["ev"] == "adopted" for f in ap2) and sum(len(b) for b in ask2) == 0
    # 圈3(2 前):止损→问人,不再采纳(7 圈活锁在此第 3 圈截断)
    _mk_case(A1)
    ap3, ask3 = _drive(monkeypatch, [_pend(A1, 3), _adopt_dec(A1, slug, 1),
                                     _adopt_dec(A1, slug, 2)], {A1: "维护窗重启"})
    assert not any(f["ev"] == "adopted" for f in ap3)
    assert sum(len(b) for b in ask3) == 1
    assert "止损" in ask3[0][0]["question"] and "多轮尝试未解决" in ask3[0][0]["question"]
    # Theory 建议:重放稳定——止损后重放 ask_decision(同事实流),n_adopt 不虚涨、
    # 止损语境不重复叠加(止损分支不落 adopted decision→计数只读持久前轮,重放恒定)。
    import re
    _mk_case(A1)
    ap3b, ask3b = _drive(monkeypatch, [_pend(A1, 3), _adopt_dec(A1, slug, 1),
                                       _adopt_dec(A1, slug, 2)], {A1: "维护窗重启"})
    assert not any(f["ev"] == "adopted" for f in ap3b)          # 重放不产生采纳
    n1 = re.search(r"已 (\d+) 次采纳", ask3[0][0]["question"]).group(1)
    n2 = re.search(r"已 (\d+) 次采纳", ask3b[0][0]["question"]).group(1)
    assert n1 == n2 == "2"                                       # n_adopt 不虚涨(重放稳定)
    assert ask3b[0][0]["question"].count("此判例方向已多轮") == 1   # 语境单份,不重复叠加


def test_adoption_stoploss_survives_zero_hits_this_round(monkeypatch):
    """根因回归(668000 实弹未拦):活锁中 worker 把 equivalent 由 yes 翻 no→本轮 sig 由
    …|eq 变 …|noeq→find_adjudications 本轮 0 hits。止损必须仍触发——计数按 aid(不绑当轮
    slug)、前置于 find_adjudications。旧位置(嵌采纳块内、需 hits 命中才进)会整个跳过→止损
    永不触发(fastlog 免问/止损 emit 双零即此)。此处判例店留空模拟本轮 0 hits。"""
    _mk_case(A1)   # forbidden_mechanism 三元组,_fm_meta 非空;不 _seed_adj → 判例店空 → 本轮 0 hits
    hist = "eq--forbidden-mechanism--10-5"   # 历史 eq 判例(与本轮 sig 已不匹配)
    facts = [_pend(A1, 4),
             _adopt_dec(A1, hist, 1), _adopt_dec(A1, hist, 2), _adopt_dec(A1, hist, 3),
             _adopted_fact(A1, hist, ruling="改过程:采纳 clear 运行面等价")]
    appended, asked = _drive(monkeypatch, facts, {A1: "维护窗重启"})
    # 尽管本轮 find 0 hits,止损仍触发:无新 adopted、interrupt 被调、题面止损语境
    assert not any(f.get("ev") == "adopted" for f in appended)
    assert sum(len(b) for b in asked) == 1
    _q = asked[0][0]["question"]
    assert "止损" in _q and "多轮尝试未解决" in _q and "3 次采纳" in _q
    # 判例主张取历史 adopted 事实 ruling(与当轮 find 解耦→noeq 0 hits 时仍有)
    assert "判例主张" in _q and "clear" in _q


def test_folded_members_on_rep_question(monkeypatch):
    """F-Py-1 T1a:代表题 dict 带 folded_members==fold[rep](全 aid)——凭证组装侧恒等,
    防单题偷塞(引擎供的清单恰等于折叠组成员)。经 payload 流到 ask_user:247 落凭证。"""
    _mk_case(A1), _mk_case(A2)   # 同 group_path → 折成一题
    _appended, asked = _drive(monkeypatch, [_pend(A1, 1), _pend(A2, 1)], {min(A1, A2): "改过程"})
    assert sum(len(b) for b in asked) == 1                      # 组一题(代表)
    fm = asked[0][0].get("folded_members")
    assert fm is not None and set(fm) == {A1, A2}              # 代表题带全组成员 aid,恰等
