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


def test_multi_round_evidence_latest_inline_earlier_by_ref(rig):
    """载荷按引用(X8 效率债,2026-07-11):多轮 fail 只有最新轮回显全文内联,
    更早轮降级为 ref 引用+归因结论行(fs_read 现查)——旧版全轮内联随轮数线性膨胀。"""
    state, lr_ref = rig
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery", "result": "fail",
           "artifact": "a1", "volume": "v", "evidence_ref": lr_ref, "signatures": []},
          {"ev": "attribution", "aid": A, "round": 1, "run_id": "r1",
           "layer": "V", "disposition": "reflow", "fix_direction": "FIX-R1"},
          {"ev": "authored", "aid": A, "round": 2, "artifact": "a2"},
          {"ev": "verdict", "aid": A, "run_id": "r2", "ctx": "delivery", "result": "fail",
           "artifact": "a2", "volume": "v", "evidence_ref": lr_ref, "signatures": []},
          {"ev": "attribution", "aid": A, "round": 2, "run_id": "r2",
           "layer": "V", "disposition": "reflow", "fix_direction": "FIX-R2"}]
    b = build_brief(A, state, fs)
    assert b.count("ROUND1-DEV") == 1                      # 回显全文只出现一次(最新轮)
    assert f'ref="{lr_ref}"' in b and "earlier" in b       # 早轮按引用
    assert "FIX-R1" in b and "FIX-R2" in b                 # 归因结论行全轮保留


# ── 污点二落地:执行失败行显式高亮 + 引导查自己序列(2026-07-13) ────────────────
def test_exec_failure_lines_surfaced_and_guides_sequence_fix(tmp_path, monkeypatch):
    """last_run 有 anomaly_lines(自身执行失败)→ brief 独立高亮 + round_task 引导
    「fault 在本案命令序列,不是床污染」——让 worker 重编改写法而非当污染。"""
    outputs = tmp_path / "outputs"
    (outputs / "b").mkdir(parents=True)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    (outputs / "b" / "manifest.json").write_text(json.dumps(
        {"cases": [{"autoid": A, "title": "t", "group_path": ["g"], "step_intents": []}]},
        ensure_ascii=False), encoding="utf-8")
    lr = outputs / "b" / "last_run.json"
    lr.write_text(json.dumps([{"autoid": A, "device_context": "…write all…",
                               "anomaly_lines": ["Failed to execute the command",
                                                 "A configuration file named X already exists"]}]),
                  encoding="utf-8")
    lr_ref = str(lr.relative_to(tmp_path))
    state = {"manifest_ref": "outputs/b/manifest.json", "product_version": "10.5",
             "max_rounds": 3, "device_build": "10.5.0.585", "out_name": "b"}
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery", "result": "fail",
           "artifact": "a1", "volume": "v", "evidence_ref": lr_ref, "signatures": []},
          {"ev": "attribution", "aid": A, "round": 1, "run_id": "r1",
           "layer": "V", "disposition": "reflow", "fix_direction": "FIX0"}]
    b = build_brief(A, state, fs)
    assert "<execution_failures" in b
    assert "Failed to execute the command" in b
    assert "THIS case's own command sequence" in b            # 引导查序列
    assert "do not treat this as bed cleanup" in b            # 明确不是床污染


def test_no_exec_failure_block_when_no_anomaly(tmp_path, monkeypatch):
    """无 anomaly_lines(普通 fail)→ 不加执行失败块/引导(不噪音)。"""
    outputs = tmp_path / "outputs"
    (outputs / "b").mkdir(parents=True)
    monkeypatch.setattr(sh, "project_root", lambda: tmp_path)
    monkeypatch.setattr(sh, "outputs_root", lambda: outputs)
    (outputs / "b" / "manifest.json").write_text(json.dumps(
        {"cases": [{"autoid": A, "title": "t", "step_intents": []}]}, ensure_ascii=False),
        encoding="utf-8")
    lr = outputs / "b" / "last_run.json"
    lr.write_text(json.dumps([{"autoid": A, "device_context": "clean fail, no exec error"}]),
                  encoding="utf-8")
    lr_ref = str(lr.relative_to(tmp_path))
    state = {"manifest_ref": "outputs/b/manifest.json", "product_version": "10.5",
             "max_rounds": 3, "device_build": "10.5.0.585", "out_name": "b"}
    fs = [{"ev": "authored", "aid": A, "round": 1, "artifact": "a1"},
          {"ev": "verdict", "aid": A, "run_id": "r1", "ctx": "delivery", "result": "fail",
           "artifact": "a1", "volume": "v", "evidence_ref": lr_ref, "signatures": []},
          {"ev": "attribution", "aid": A, "round": 1, "run_id": "r1",
           "layer": "V", "disposition": "reflow", "fix_direction": "FIX0"}]
    b = build_brief(A, state, fs)
    assert "<execution_failures" not in b
    assert "THIS case's own command sequence" not in b


# ── D9 注入措辞去事实化(2026-07-16,777976 洗白链取证驱动) ─────────────────────


def test_fix_direction_marked_hypothesis(rig):
    """retry brief:上轮归因带 confidence="hypothesis" 假设框,原文仍在
    (措辞是 re-verify 不是 distrust——正确归因的定向价值保留)。"""
    state, lr_ref = rig
    b = build_brief(A, state, _facts(lr_ref, rounds=1))
    assert 'confidence="hypothesis"' in b
    assert 'status="hypothesis"' in b
    assert "not established fact" in b
    assert "FIX0" in b                                  # fix_direction 原文不动


def test_intent_note_marks_expected_as_author_claim(rig):
    """intent note 成对措辞:①作者预期非设备已证事实;②预期仍是断言期望值唯一来源
    (单标"未证实"会滑向 worker 自决改预期——observe-then-assert 反向重演)。"""
    state, _ = rig
    b = build_brief(A, state, [])
    assert "author's anticipated outcome" in b and "not device-verified" in b
    assert "sole source of assertion expectations" in b
    assert "never" in b and "replace the expectation with the observed value" in b


def test_user_adjudication_stays_authoritative(rig, tmp_path):
    """裁决块措辞不被 D9 连带弱化:用户裁决仍是最高权威(highest authority)。"""
    state, lr_ref = rig
    panel_path = sh.outputs_root() / "b" / "panel.json"
    panel_path.write_text(json.dumps({
        "conflict_shape": "expected_vs_observed", "hypothesis": "H",
        "sides": [{"source_ref": "s", "quote": "q"}]}), encoding="utf-8")
    fs = _facts(lr_ref, rounds=1) + [
        {"ev": "ask_panel", "aid": A, "round": 1, "shape": "expected_vs_observed",
         "ref": str(panel_path.relative_to(sh.project_root()))},
        {"ev": "decision", "aid": A, "question_id": f"panel:{A}:1",
         "answer": "纠正:按手册 X 编", "token": "correct"}]
    b = build_brief(A, state, fs)
    assert "highest authority" in b                     # 权威序不因假设框松动
    assert 'confidence="hypothesis"' in b               # 两块并存、物理分离


def test_hypothesis_markup_switch_off(rig, monkeypatch):
    """IST_BRIEF_HYPOTHESIS_MARKUP=0 → 回退旧措辞(对照轮/紧急回退口)。"""
    monkeypatch.setenv("IST_BRIEF_HYPOTHESIS_MARKUP", "0")
    state, lr_ref = rig
    b = build_brief(A, state, _facts(lr_ref, rounds=1))
    assert "hypothesis" not in b
    assert "author's anticipated outcome" not in b
    assert "FIX0" in b


# ── F8a 兄弟上下文(§18.11):同组 title 一行式内联,check 按引用不内联 ──────────

def test_brief_siblings_block(monkeypatch):
    from main.ist_core.compile_engine_v8 import _shared as sh
    from main.ist_core.compile_engine_v8 import briefs as BR
    A, B, C = "203600000000000015", "203600000000000030", "203600000000000044"
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": A, "title": "1.执行write file后重启设备", "group_path": ["功能", "配置保存"],
         "step_intents": [{"desc": "[check1]配置未被保存", "expected": ""}]},
        {"autoid": B, "title": "1.执行write all后重启设备", "group_path": ["功能", "配置保存"],
         "step_intents": [{"desc": "[check1]配置未被保存", "expected": ""}]},
        {"autoid": C, "title": "1.配置sdns listener,使用全域名功能", "group_path": ["功能", "全域名"],
         "step_intents": []}]})
    b = BR.build_brief(A, {"manifest_ref": "m.json", "max_rounds": 3}, [])
    assert "<siblings" in b
    assert "write all" in b                      # 兄弟 title 内联(变体轴可见)
    assert "…" + B[-6:] in b
    assert C[-6:] not in b.split("<siblings")[1]  # 异组不入
    assert "配置未被保存" not in b.split("<siblings")[1]  # 兄弟 check/期望不内联(D14/D15)


def test_brief_no_siblings_no_block(monkeypatch):
    from main.ist_core.compile_engine_v8 import _shared as sh
    from main.ist_core.compile_engine_v8 import briefs as BR
    A = "203600000000000059"
    monkeypatch.setattr(sh, "manifest", lambda st: {"cases": [
        {"autoid": A, "title": "全域名", "group_path": ["功能", "全域名"], "step_intents": []}]})
    b = BR.build_brief(A, {"manifest_ref": "", "max_rounds": 3}, [])
    assert "<siblings" not in b
