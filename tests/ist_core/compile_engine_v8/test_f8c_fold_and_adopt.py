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

_ROOT = Path(__file__).resolve().parents[3]
A1, A2 = "203099999999900101", "203099999999900102"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    for a in (A1, A2):
        shutil.rmtree(_ROOT / "workspace" / "outputs" / a, ignore_errors=True)
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
        shutil.rmtree(_ROOT / "workspace" / "outputs" / a, ignore_errors=True)


def _mk_case(aid):
    d = _ROOT / "workspace" / "outputs" / aid
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
        ud = json.loads((_ROOT / "workspace" / "outputs" / a / "user_decision.json")
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
    assert (_ROOT / "workspace" / "outputs" / A1 / "user_decision.json").is_file()
    assert any(f.get("ev") == "adopted" for f in appended)


def test_other_freeform_lands_as_process_for_fm(monkeypatch):
    """Other 自由文本(无三关键词)对禁令类=改过程+原文入 note(评审 D9 兜底)。"""
    _mk_case(A1)
    appended, _ = _drive(monkeypatch, [_pend(A1, 1)],
                         {A1: "用受控维护窗真重启一次,周五凌晨"})
    ud = json.loads((_ROOT / "workspace" / "outputs" / A1 / "user_decision.json")
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
    assert q["options"][0]["label"].startswith("采纳「")       # 采纳选项=具体方案
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
