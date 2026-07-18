"""D12（668000/668044）批间隙补修包 v2：D12 真根因 shape-aware 采信修复 + 5 项独立改进（D 撤出）。

照因（leader 令「先照因再修」，用 runtime/ask_user_answers.jsonl+facts+判例店实数据）定 D12 真根因=
**跨 claim_kind 采信碰撞**（非下列 5 项）：668000=verification_path_absent 三元组（group leaf=配置
保存,has_equivalent）→ _fm_meta sig=`配置保存|eq`，与 forbidden_mechanism 判例 `eq--forbidden-
mechanism--10-5`（同 sig,token=改描述）碰撞，adopt 读/写硬写 forbidden_mechanism、不校真实
claim_kind → 三元组被 改描述(挂起)抢占。**修法（本包，Design(b)+Theory 21c）**：读(:624)/写(:771)
conflict_shape 按案真实 claim_kind 分名空间 + 采信闸双保险（命中后校 shape）——守门见文件末
`test_shape_aware_*`（已证 red→green）。存量 11 条 FM 名空间判例经 sig 结构判定全为三元组误标,
修后被安全孤立（三元组查 verification_path_absent 命不中它们→重问=安全默认;FM 案 sig=leaf|fams
不撞 |eq/|noeq）,迁移treatment 待 Design 复裁（reclassify 会重启陈旧 改描述 采信,不宜）。

另含 5 项**各自独立成立的改进/防御纵深**（非 D12 修法面）：

- B  (questions.py:225)  test_point 面板题面带**全 aid**——先问后落门无 folded_members 键的
                         老记录回退按「全 aid in line」判,短号题面致回退失败。
- F-TUI-2 (questions.py:234) 采纳 label 由动态 `采纳「{proc[:60]}」` 改**固定短语**——动态 label
                         被 TUI 截断加 `…` 时会打断消费点 W3 `lbl in a` 子串匹配;固定短语更稳、
                         无截断（668000 上 W3 本就命中，非该案主因，此项为防御纵深）。
- W3 (nodes.py 消费点)   固定 label 下答案(含 TUI 序号加工)稳定命中 → 改过程 落账。
- D14 (render.py)        adopt 去向行的裁决要点经 `_ruling_summary` 去 md 头/Revision 时间戳/半句。
- D15 (render.py)        adopt 免问派生的 decision(provenance=adopted:*)在时间线不显「你的裁决」、
                         在结论 who 归因「此前批判例」而非「你的裁决」。

（另含 D13 可观测性:_land 拒因+W3 空 decision 落 logger/evidence,无独立断言、由既有路径覆盖。）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8.questions import build_questions
from main.ist_core.tools.knowledge import adjudication_store as adj
from main.ist_core.compile_engine_v8.render import (
    _ruling_summary, case_timeline, remedy_text,
)
from main.common.runtime_paths import runtime_path

# 668000 族形态(18 位 autoid;尾号 668000)
A = "203601753067668000"
FIXED_ADOPT_LABEL = "采纳该等价方案(方法见题面)"   # F-TUI-2 固定短语(与 questions.py:234 同源)


def _qa_log() -> Path:
    return runtime_path("ask_user_answers.jsonl")


@pytest.fixture(autouse=True)
def _clean_qa_log():
    """runtime_path 在 pytest 下按 pid 固定 → 跨用例复用同文件,须清场防污染。"""
    _qa_log().unlink(missing_ok=True)
    yield
    _qa_log().unlink(missing_ok=True)


def _write_qa(record: dict):
    p = _qa_log()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _triple_led(aid=A):
    """三元组(verification_path_absent + test_point + equivalent)——B/F-TUI-2 面板输入。"""
    return {aid: {"claims": [{
        "claim_kind": "verification_path_absent",
        "test_point": "write file 存盘后重启,sdns listener 配置应丢失",
        "obstacle": "自动化环境无法重启设备(断连、无法继续测试)",
        "equivalent": {"procedure": "查 show startup 有无 sdns listener port 53 配置",
                       "preserves": "write 家族错写启动面会被抓住(对被测写步敏感)"},
        "reason": "环境无法重启"}]}}


# ── B:test_point 题面带全 aid(先问后落门老记录回退凭证) ───────────────────────

def test_b_test_point_question_carries_full_aid():
    qs = build_questions(_triple_led())
    assert len(qs) == 1
    q = qs[0]["question"]
    assert A in q                       # 全 aid 在题面(门 full-aid 子串回退恒稳)
    assert f"尾号 {A[-6:]}" in q         # 尾号并存(人辨识)


# ── F-TUI-2:采纳 label 固定短语(无截断、跨轮稳定) ──────────────────────────────

def test_ftui2_adopt_label_is_fixed_short_phrase():
    qs = build_questions(_triple_led())
    opt0 = qs[0]["options"][0]
    assert opt0["label"] == FIXED_ADOPT_LABEL            # 固定短语,非 `采纳「{proc}」`
    assert "「" not in opt0["label"]                      # 无内嵌 proc → 无 mid-word 截断风险
    assert qs[0]["_token_by_label"][FIXED_ADOPT_LABEL] == "改过程"
    # 完整方法仍在题面(label 不需预览)
    assert "show startup" in qs[0]["question"]


# ── W3:固定 label 下答案命中 → 改过程落账(含 TUI 序号加工) ──────────────────────

def _mk_triple_case(aid=A):
    d = sh.outputs_root() / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "needs_decision.json").write_text(
        json.dumps(_triple_led(aid)[aid], ensure_ascii=False), encoding="utf-8")
    (d / "intent.json").write_text(json.dumps(
        {"autoid": aid, "title": "write file 后重启验证", "group_path": ["功能", "配置保存"],
         "source": "manifest"}, ensure_ascii=False), encoding="utf-8")
    return d


def _drive_ask(monkeypatch, tmp_path, aid, answer):
    # 判例店隔离到 tmp(空)——否则盘上真判例(eq--forbidden-mechanism--10-5)命中→adopt 免问
    # 抢在面板前落 改描述,W3 路径根本不走到(正是 D12「adopt 默认赢」形态,此处要测面板路故隔离)
    monkeypatch.setattr(adj, "adjudications_root", lambda: tmp_path / "adj")
    facts = [{"ev": "needs_decision", "aid": aid, "question_id": f"nd:{aid}:1"}]
    appended: list[dict] = []
    monkeypatch.setattr(sh, "load_facts", lambda st: facts)
    monkeypatch.setattr(sh, "append", lambda st, fx: appended.extend(fx))
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "counts_update", lambda st, f=None: {})

    def fake_interrupt(payload):
        return {str(q.get("_autoid")): answer for q in payload.get("questions", [])}
    monkeypatch.setattr(N, "interrupt", fake_interrupt)
    N.ask_decision({"product_version": "10.5", "out_name": "t_d12"})
    return appended


@pytest.mark.parametrize("answer", [
    FIXED_ADOPT_LABEL,                    # 精确答案
    f"1. {FIXED_ADOPT_LABEL}",            # TUI 序号加工(W3 子串仍命中)
    f"{FIXED_ADOPT_LABEL}\n",             # 换行加工
])
def test_w3_fixed_label_answer_lands_as_process(monkeypatch, tmp_path, answer):
    import shutil
    shutil.rmtree(sh.outputs_root() / A, ignore_errors=True)
    _mk_triple_case()
    # 先问后落门:老记录**无 folded_members 键**,靠 B 的全 aid 子串回退命中
    _write_qa({"ts": 0, "questions": [f"用例 {A}(尾号 {A[-6:]}) 要验证:…"],
               "answers": {"q": answer}})
    appended = _drive_ask(monkeypatch, tmp_path, A, answer)
    dec = [f for f in appended if f.get("ev") == "decision" and f.get("aid") == A]
    assert dec and dec[0]["answer"] == "改过程"          # 采纳落账(不再空)
    assert (sh.outputs_root() / A / "user_decision.json").is_file()
    shutil.rmtree(sh.outputs_root() / A, ignore_errors=True)


# 注：D（prep 批开工轮转 ask_user_answers.jsonl）已从本包撤出——照因发现它会误杀合法「免问采信」
# （adopt 的 _land 也过先问后落门、靠跨批陈旧记录满足，轮转清台账即断采信）。相应测试一并移除。


# ── D14:adopt 去向裁决要点经 _ruling_summary 清洗 ──────────────────────────────

def test_d14_adopted_remedy_summarizes_ruling():
    ruling = ("# 裁决\n\n采纳「配置sdns on」\n\n## Revision @2026-07-18T00:15:36\n\n"
              "采纳「以 IPv4 客户端 dig CNAME 替代 IPv6」")
    mine = [{"ev": "adopted", "aid": A, "round": 0, "slug": "eq--fm--10-5", "ruling": ruling}]
    txt = remedy_text([], mine)
    assert "**去向**" in txt and "沿用" in txt
    assert "## Revision" not in txt and "@2026" not in txt     # 去 md 头/时间戳
    assert "\n" not in txt                                     # 无残留换行
    assert "以 IPv4 客户端 dig CNAME 替代 IPv6" in txt          # 取最新段操作性要点


def test_d14_ruling_summary_unit():
    assert _ruling_summary("") == ""
    assert _ruling_summary("# 裁决\n\n挂起,如实报告") == "挂起,如实报告"
    long = "采纳「" + "很长的方案" * 40 + "」"
    out = _ruling_summary(long, limit=120)
    assert len(out) <= 121 and out.endswith("…")              # 超长按 limit 收尾不留半句


# ── D15:adopt 派生 decision 的 provenance 分流(时间线 + 结论 who) ──────────────

def test_d15_timeline_adopt_no_false_your_ruling():
    mine = [{"ev": "adopted", "aid": A, "round": 0, "ruling": "# 裁决\n\n挂起"},
            {"ev": "decision", "aid": A, "answer": "改过程",
             "provenance": "adopted:eq--fm--10-5"}]
    tl = case_timeline(mine)
    assert any("直接沿用(免问)" in x for x in tl)               # adopt 行在
    assert not any(str(x).startswith("你的裁决") for x in tl)   # 免问派生不冒充亲裁


def test_d15_timeline_real_decision_still_shows_your_ruling():
    """对照:真人裁决(无 adopted provenance)照常显「你的裁决」。"""
    mine = [{"ev": "decision", "aid": A, "answer": "改过程"}]
    assert case_timeline(mine) == ["你的裁决:改过程"]


def test_d15_remedy_who_provenance_split():
    base_att = {"ev": "attribution", "aid": A, "disposition": "env_blocked", "round": 99}
    adopt_mine = [{"ev": "decision", "aid": A, "answer": "改过程",
                   "provenance": "adopted:eq--fm--10-5"}, base_att]
    real_mine = [{"ev": "decision", "aid": A, "answer": "改过程"}, base_att]
    adopt_txt = remedy_text([], adopt_mine)
    real_txt = remedy_text([], real_mine)
    assert "此前批的同键判例" in adopt_txt and "你的裁决" not in adopt_txt
    assert "你的裁决" in real_txt


# ── D12 真根因守门：shape-aware 采信（Theory 21c 采信同型律 shape(案)≠shape(判例)⇒禁采信） ──
# 真因=跨 claim_kind 采信碰撞：verification_path_absent 三元组 _fm_meta sig=`配置保存|eq` 撞
# forbidden_mechanism 判例同 sig→旧硬写 FM 致三元组被 FM 判例 改描述(挂起)抢占、面板不再出。
# 修法=读(:624)写(:771)conflict_shape 按案真实 claim_kind 分名空间 + 采信闸双保险(命中后校 shape)。
# 修前红(三元组被采信)、修后绿；覆盖 668 族多案形态(eq 前缀同、claim_kind 异)。

def _seed_fm_adj(monkeypatch, tmp_path, sig, token="改描述"):
    monkeypatch.setattr(adj, "adjudications_root", lambda: tmp_path / "adj")
    adj.write_adjudication(
        key={"intent_signature": sig, "conflict_shape": "forbidden_mechanism",
             "version_family": "10.5"},
        ruling="# 裁决\n\n挂起,如实报告", anchor={"version": "10.5", "lineage": "user_proxy"},
        meta={"token": token})


def _mk_fm_case(aid, group_leaf="配置保存"):
    """真 forbidden_mechanism 案(claim_kind=forbidden_mechanism,无 test_point)→ shape=fm。"""
    d = sh.outputs_root() / aid
    d.mkdir(parents=True, exist_ok=True)
    (d / "needs_decision.json").write_text(json.dumps({"autoid": aid, "claims": [{
        "claim_kind": "forbidden_mechanism", "reason": "intent 要重启;床禁重启",
        "proposed_equivalent": "clear 运行面(模型条件等价)"}]}, ensure_ascii=False), encoding="utf-8")
    (d / "intent.json").write_text(json.dumps({"autoid": aid, "title": "重启案",
        "group_path": ["功能", group_leaf], "forbidden_mechanism": [{"family": "reboot",
        "matched": "重启"}], "source": "manifest"}, ensure_ascii=False), encoding="utf-8")


def test_shape_aware_triple_not_adopt_fm_ruling_668_family(monkeypatch, tmp_path):
    """守门①(668 族多案):三元组(verification_path_absent,sig=配置保存|eq)不采信同 sig 的
    forbidden_mechanism 判例→进面板问用户,不被 改描述 抢占(修前此测红)。"""
    import shutil
    _seed_fm_adj(monkeypatch, tmp_path, sig="配置保存|eq", token="改描述")
    aids = ["203601753067668000", "203601753067668015", "203601753067668044"]  # 668 族形态
    for aid in aids:
        shutil.rmtree(sh.outputs_root() / aid, ignore_errors=True)
        _mk_triple_case(aid)
        # 关键:播种先问后落门凭证——否则 adopt 的 _land 被门拒、碰撞不落,测试会**因错误理由变绿**
        # (与被移出的 xfail 同陷阱)。有凭证时:修前碰撞→adopt 改描述真落=红;修后 shape 不命中=绿。
        _write_qa({"ts": 0, "questions": [f"用例 {aid} 被问过"], "answers": {"q": "改描述"}})
    facts = [{"ev": "needs_decision", "aid": aid,
              "question_id": f"nd:{aid}:1:verification_path_absent"} for aid in aids]
    appended, ic = [], []
    monkeypatch.setattr(sh, "load_facts", lambda st: facts)
    monkeypatch.setattr(sh, "append", lambda st, fx: appended.extend(fx))
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "counts_update", lambda st, f=None: {})
    monkeypatch.setattr(N, "interrupt", lambda p: (ic.append(1) or {
        str(q.get("_autoid")): "改描述" for q in p.get("questions", [])}))
    N.ask_decision({"product_version": "10.5", "out_name": "t_shape"})
    for aid in aids:
        shutil.rmtree(sh.outputs_root() / aid, ignore_errors=True)
    # 21c:异 shape 判例不可命中——无一三元组被采信(零 adopted 事实),都进面板
    assert not any(f.get("ev") == "adopted" for f in appended)
    assert ic   # 面板展示了(进人工问询,不静默 改描述)


def test_shape_aware_fm_case_still_adopts_same_shape(monkeypatch, tmp_path):
    """守门②(正对照,不误伤收敛律):真 forbidden_mechanism 案(同 shape)仍正常采信 FM 判例免问。"""
    import shutil
    fm_aid = "203699999999900777"
    _seed_fm_adj(monkeypatch, tmp_path, sig="配置保存|reboot", token="改过程")   # FM 案 sig=leaf|fams
    shutil.rmtree(sh.outputs_root() / fm_aid, ignore_errors=True)
    _mk_fm_case(fm_aid)
    _write_qa({"ts": 0, "questions": [f"用例 {fm_aid} 被问过"], "answers": {"q": "改过程"}})  # _land 门
    facts = [{"ev": "needs_decision", "aid": fm_aid, "question_id": f"nd:{fm_aid}:1:forbidden_mechanism"}]
    appended = []
    monkeypatch.setattr(sh, "load_facts", lambda st: facts)
    monkeypatch.setattr(sh, "append", lambda st, fx: appended.extend(fx))
    monkeypatch.setattr(sh, "signal", lambda *a, **k: None)
    monkeypatch.setattr(sh, "emit", lambda t: None)
    monkeypatch.setattr(sh, "counts_update", lambda st, f=None: {})
    monkeypatch.setattr(N, "interrupt", lambda p: {str(q.get("_autoid")): "" for q in p.get("questions", [])})
    N.ask_decision({"product_version": "10.5", "out_name": "t_shape_fm"})
    shutil.rmtree(sh.outputs_root() / fm_aid, ignore_errors=True)
    # 同 shape → 正常采信:有 adopted 事实(修法不误伤 (20) 收敛律的免问采信)
    assert any(f.get("ev") == "adopted" and f.get("aid") == fm_aid for f in appended)
