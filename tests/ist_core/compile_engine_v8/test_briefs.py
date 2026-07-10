"""V8 brief 构建门(V6 语义等价迁移):首败即全历史/布局(数据顶指令尾)/FINAL 标记/矛盾段。"""
from __future__ import annotations

import json

import pytest

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8.briefs import build_brief

A = "209030000000000001"


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    (outputs / "b").mkdir(parents=True)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    (outputs / "b" / "manifest.json").write_text(json.dumps(
        {"cases": [{"autoid": A, "title": "t", "group_path": ["g"],
                    "step_intents": [{"desc": "INTENT-DESC", "expected": "EXP"}]}]},
        ensure_ascii=False), encoding="utf-8")
    lr = outputs / "b" / "last_run.json"
    lr.write_text(json.dumps([{"autoid": A, "device_context": "ROUND1-DEV"}]),
                  encoding="utf-8")
    state = {"manifest_ref": "outputs/b/manifest.json", "product_version": "10.5",
             "max_rounds": 3, "device_build": "10.5.0.585", "out_name": "b"}
    return state, str(lr.relative_to(tmp_path))


def _facts(lr_ref, rounds=1, contra=False):
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"}]
    fs.append({"ev": "verdict", "aid": A, "run_id": "r1",
               "ctx": "subset" if contra else "delivery", "result": "pass" if contra else "fail",
               "artifact": "a1", "volume": "v", "evidence_ref": lr_ref, "signatures": []})
    if contra:
        fs.append({"ev": "verdict", "aid": A, "run_id": "r2", "ctx": "delivery",
                   "result": "fail", "artifact": "a1", "volume": "v",
                   "evidence_ref": lr_ref, "signatures": []})
    fs.append({"ev": "attribution", "aid": A, "round": rounds, "run_id": "r1",
               "layer": "V", "disposition": "reflow", "fix_direction": "FIX0"})
    for r in range(2, rounds + 1):
        fs.append({"ev": "authored", "aid": A, "round": r, "artifact": f"a{r}"})
    return fs


def test_round1_brief_is_lightweight(rig):
    state, _ = rig
    b = build_brief(A, state, [])
    assert b.splitlines()[0].lstrip().startswith("{")
    assert "Recompile round" not in b and "device_evidence" not in b
    assert "INTENT-DESC" in b


def test_first_retry_gets_full_history_and_max_note(rig):
    """首败即全历史(2026-07-09 裁决;V6 等价语义迁移)。"""
    state, lr_ref = rig
    b = build_brief(A, state, _facts(lr_ref, rounds=1))
    assert "Recompile round" in b and "thinking depth is max" in b
    assert "ROUND1-DEV" in b and "FIX0" in b
    assert "FINAL attempt" not in b     # R2 非最后一轮(max_rounds=3)


def test_final_attempt_marker(rig):
    state, lr_ref = rig
    b = build_brief(A, state, _facts(lr_ref, rounds=2))
    assert "FINAL attempt" in b


def test_layout_envelope_first_data_top_instructions_last(rig):
    """布局门(官方长上下文实践):机读信封首行;数据区在前,intent 紧邻指令,round_task 收尾。"""
    state, lr_ref = rig
    b = build_brief(A, state, _facts(lr_ref, rounds=1))
    env = json.loads(b.splitlines()[0])
    assert env["autoid"] == A and env["device_build"] == "10.5.0.585"
    order = ["<device_evidence>", "<intent", "<round_task>"]
    pos = [b.find(t) for t in order]
    assert all(p >= 0 for p in pos) and pos == sorted(pos)
    assert b.rstrip().endswith("</round_task>")


def test_contradiction_brief_carries_interference_note(rig):
    state, lr_ref = rig
    b = build_brief(A, state, _facts(lr_ref, rounds=1, contra=True))
    assert "passed in isolation but failed in the full-volume run" in b
