"""Ask 子系统 B 片验收(DESIGN §11.11 构件二/三/五 + eval ④⑤)。

④adopted 不触发写回;⑤同键第二批零 ask(收敛律 (20) 的机械面)。
外加:存储 round-trip/revision、采信三条件矩阵、kb_intent_search 四源冒烟。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8 import views as V
from main.ist_core.tools.knowledge import adjudication_store as ADJ

A = "203600000000000001"

KEY = {"intent_signature": "rr-new-member-tail-position",
       "conflict_shape": "expected_vs_observed", "version_family": "10.5"}


@pytest.fixture()
def adj_root(tmp_path, monkeypatch):
    root = tmp_path / "adjudications"
    monkeypatch.setattr(ADJ, "adjudications_root", lambda: root)
    return root


# ── 构件三:存储 round-trip ───────────────────────────────────────────────────


def test_write_and_find_roundtrip(adj_root):
    p = ADJ.write_adjudication(
        KEY, ruling="预期改为下一轮生效(用户确认)",
        anchor={"version": "10.5.0.585", "lineage": "user_proxy"},
        sides=[{"source_ref": "device_context", "quote": "r1 10.1.1.1 UP", "anchor": None}],
        meta={"autoid": A, "batch": "b1", "token": "confirm"})
    assert p.is_file() and p.parent == adj_root
    hits = ADJ.find_adjudications(**{k: v for k, v in KEY.items()})
    assert len(hits) == 1
    h = hits[0]
    assert h["token"] == "confirm" and h["intent_signature"] == KEY["intent_signature"]
    assert "下一轮生效" in h["body"] and "r1 10.1.1.1 UP" in h["body"]
    assert h["anchor"]["lineage"] == "user_proxy" and h["anchor"]["ts"]
    # 键失配 → 空(A3:失配保守回落 ask)
    assert ADJ.find_adjudications(intent_signature="other-sig") == []
    assert ADJ.find_adjudications(version_family="10.4") == []


def test_same_key_collision_appends_revision(adj_root):
    ADJ.write_adjudication(KEY, "裁决一", {"version": "v1", "lineage": "user_proxy"},
                           meta={"token": "confirm"})
    p = ADJ.write_adjudication(KEY, "裁决二(改口)", {"version": "v2", "lineage": "user_proxy"},
                               meta={"token": "correct"})
    text = p.read_text(encoding="utf-8")
    assert "裁决一" in text and "裁决二(改口)" in text and "## Revision @" in text
    hits = ADJ.find_adjudications(**KEY)
    assert len(hits) == 1                       # 同键=一个文件,全史在内
    assert hits[0]["token"] == "correct"        # frontmatter 跟最新裁决


def test_write_validates_key_and_lineage(adj_root):
    with pytest.raises(ValueError):
        ADJ.write_adjudication({**KEY, "intent_signature": ""}, "r",
                               {"lineage": "user_proxy"})
    with pytest.raises(ValueError):
        ADJ.write_adjudication(KEY, "r", {"version": "v"})   # 缺 lineage(A2 锚必填)


# ── 构件五:机械采信三条件矩阵 ────────────────────────────────────────────────

PANEL = {"intent_signature": KEY["intent_signature"],
         "conflict_shape": KEY["conflict_shape"],
         "version_family": KEY["version_family"],
         "sides": [], "retrieval_receipt": [], "hypothesis": "h", "ask": "?"}
CORPUS = "AN(config)# show slb\nr1 10.1.1.1 UP\nHealth check succeeded"


def _seed(adj_root, token="confirm", quote="r1 10.1.1.1 UP"):
    ADJ.write_adjudication(
        KEY, ruling="按下一轮生效编",
        anchor={"version": "10.5.0.585", "lineage": "user_proxy"},
        sides=[{"source_ref": "device_context", "quote": quote, "anchor": None}],
        meta={"token": token})


def test_adopt_same_key_matching_device(adj_root):
    _seed(adj_root)
    h = N._try_adopt(PANEL, CORPUS)
    assert h and h["token"] == "confirm"


def test_no_adopt_when_no_hit(adj_root):
    assert N._try_adopt({**PANEL, "intent_signature": "unseen-sig"}, CORPUS) is None


def test_no_adopt_when_device_behavior_changed(adj_root):
    _seed(adj_root, quote="r1 10.1.1.1 DOWN")   # 判例时行为 ≠ 本轮回显
    assert N._try_adopt(PANEL, CORPUS) is None


def test_no_adopt_when_no_device_record_in_adjudication(adj_root):
    ADJ.write_adjudication(KEY, "裁决", {"version": "v", "lineage": "user_proxy"},
                           sides=[{"source_ref": "manual.md", "quote": "文档侧",
                                   "anchor": None}], meta={"token": "confirm"})
    assert N._try_adopt(PANEL, CORPUS) is None   # 比不出=未知 → ask


def test_no_adopt_for_stop_or_defect_rulings(adj_root):
    _seed(adj_root, token="defect")
    assert N._try_adopt(PANEL, CORPUS) is None


# ── eval ⑤:同键第二批零 ask(收敛律回放) ─────────────────────────────────────


def _fs_with_panel(tmp_path, rnd=1, adopted=False):
    pdir = tmp_path / "outputs" / A
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "ask_panel.json").write_text(json.dumps({**PANEL, "autoid": A}),
                                         encoding="utf-8")
    fs = [
        {"ev": "authored", "aid": A, "round": rnd, "artifact": f"art{rnd}"},
        {"ev": "verdict", "aid": A, "run_id": f"r{rnd}", "ctx": "delivery",
         "result": "fail", "artifact": f"art{rnd}", "volume": "vol1", "signatures": []},
        {"ev": "attribution", "aid": A, "round": rnd, "run_id": f"r{rnd}",
         "layer": "V", "disposition": "reflow", "fix_direction": "x", "evidence": "e"},
        {"ev": "ask_panel", "aid": A, "round": rnd, "shape": PANEL["conflict_shape"],
         "intent_signature": PANEL["intent_signature"],
         "ref": str(pdir / "ask_panel.json")},
    ]
    if adopted:
        fs.append({"ev": "adopted", "aid": A, "round": rnd, "slug": "s",
                   "token": "confirm", "ruling": "按下一轮生效编"})
    return fs


def _vw(fs):
    return V.batch_view(fs, {"cases": [{"autoid": A}]})


def test_eval5_adopted_panel_not_in_ask_targets(tmp_path):
    """⑤采信后该 panel 不进 ask 边(同键第二批零 ask 的目标层断言)。"""
    fs = _fs_with_panel(tmp_path, adopted=False)
    assert sh.panel_waiting(fs, _vw(fs)) == [A]          # 未采信:要问
    fs2 = _fs_with_panel(tmp_path, adopted=True)
    assert sh.panel_waiting(fs2, _vw(fs2)) == []         # 已采信:免问
    t = sh.ask_targets({}, fs2, _vw(fs2))
    assert A not in t["panel"]


def test_eval5_second_batch_full_loop(adj_root, tmp_path):
    """⑤全环回放:批1 confirm→写回;批2 同 panel 收割→_try_adopt 背书→零 ask。"""
    # 批1:用户 confirm → 写回(ask_contradiction 写回接线的等价动作)
    ADJ.write_adjudication(
        KEY, ruling="h\n(用户确认:确认,按此继续)",
        anchor={"version": "10.5.0.585", "lineage": "user_proxy"},
        sides=[{"source_ref": "device_context", "quote": "r1 10.1.1.1 UP",
                "anchor": None}],
        meta={"autoid": A, "batch": "b1", "token": "confirm"})
    # 批2:同键 panel,设备行为未变 → 机械采信
    h = N._try_adopt(PANEL, CORPUS)
    assert h is not None
    fs = _fs_with_panel(tmp_path, rnd=1, adopted=True)
    assert sh.panel_waiting(fs, _vw(fs)) == []
    assert A not in sh.ask_targets({}, fs, _vw(fs))["panel"]


def test_eval4_adopt_never_writes_back(adj_root):
    """④采信只读判例库——回放采信后 adjudications/ 文件集不变(A5 人源专属)。"""
    _seed(adj_root)
    before = sorted(p.name for p in adj_root.glob("*.md"))
    for _ in range(3):
        assert N._try_adopt(PANEL, CORPUS)
    after = sorted(p.name for p in adj_root.glob("*.md"))
    assert before == after


# ── 构件二:kb_intent_search 四源冒烟 ─────────────────────────────────────────


def test_intent_search_spec_and_decision(adj_root, tmp_path, monkeypatch):
    from main.ist_core.tools.knowledge import intent_search as IS
    spec = tmp_path / "product"
    spec.mkdir()
    (spec / "sdns_manual_v105.md").write_text(
        "轮询算法下新增成员从下一轮开始参与调度。", encoding="utf-8")
    monkeypatch.setattr(IS, "_spec_root", lambda: spec)
    monkeypatch.setattr(IS, "_spec_db_path", lambda: tmp_path / "fts.sqlite")
    _seed(adj_root)
    out = IS.kb_intent_search.func(query="新增成员 下一轮", source_type="all",
                                   version_family="10.5")
    assert 'source="spec"' in out and "sdns_manual_v105" in out
    assert 'source="decision"' in out
    assert "[no hits in" in out or "hit(s)" in out      # miss 也如实陈述
    # enum 校验
    bad = IS.kb_intent_search.func(query="x", source_type="nope")
    assert bad.startswith("error")


def test_intent_search_reports_miss_per_source(tmp_path, monkeypatch, adj_root):
    from main.ist_core.tools.knowledge import intent_search as IS
    spec = tmp_path / "empty"
    spec.mkdir()
    monkeypatch.setattr(IS, "_spec_root", lambda: spec)
    monkeypatch.setattr(IS, "_spec_db_path", lambda: tmp_path / "fts2.sqlite")
    out = IS.kb_intent_search.func(query="不存在的词组xyzq", source_type="spec")
    assert "[no hits in spec]" in out
