# -*- coding: utf-8 -*-
"""G1 配对恢复门+G2/G3 接线(DESIGN §17;理论锚 (39) τ/(40) 分类学)。

金标准=655203/233 六次拆床形态:创建型 L2/L3 写无案内恢复 → emit 呈报携逆元
建议;补 τ 放行;自污染者面板出口=重编补自清;pass 但缺 τ 不入交付卷。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.case_compiler.tau_coverage import check_tau_coverage

ROOT = Path(__file__).resolve().parents[3]


# ------------------------------------------------------------- 判定器单元
def test_tau_missing_vlan_and_bond():
    """233/203 病灶形态:vlan/bond/ip 写无恢复 → missing+正确逆元建议。"""
    steps = [{"E": "APV_0", "F": "cmds_config",
              "G": "no ip address port2\nvlan port2 vlan100 100\n"
                   "ip address vlan100 172.16.34.70 255.255.255.0"}]
    r = check_tau_coverage(steps)
    assert not r.ok
    cmds = {m["cmd"]: m["suggested_inverse"] for m in r.missing}
    assert cmds["vlan port2 vlan100 100"] == "no vlan vlan100"
    assert cmds["ip address vlan100 172.16.34.70 255.255.255.0"] == "no ip address vlan100"
    assert "no ip address port2" in r.out_of_scope  # 删除型:第一版如实不判(恢复需原值)


def test_tau_covered_when_teardown_present():
    """案尾逆序 no 回放 → 全覆盖(233 的正解卷面形态)。"""
    steps = [{"E": "APV_0", "F": "cmds_config",
              "G": "no ip address port2\nvlan port2 vlan100 100\n"
                   "ip address vlan100 172.16.34.70 255.255.255.0"},
             {"E": "check_point", "F": "found", "G": r"172\.16"},
             {"E": "APV_0", "F": "cmds_config",
              "G": "no ip address vlan100\nno vlan vlan100\n"
                   "ip address port2 172.16.34.70 255.255.255.0"}]
    r = check_tau_coverage(steps)
    assert r.ok, r.missing


def test_tau_bond_form():
    steps = [{"E": "APV_0", "F": "cmd_config", "G": "bond interface bond1 port1"}]
    r = check_tau_coverage(steps)
    assert not r.ok and r.missing[0]["suggested_inverse"] == "no bond interface bond1"


def test_tau_persist_out_of_scope():
    """持久面写第一版不判(排尾+批末收敛缓解,L3 根治)——如实归 out_of_scope。"""
    steps = [{"E": "APV_0", "F": "cmd_config", "G": "write memory"}]
    r = check_tau_coverage(steps)
    assert r.ok and "write memory" in r.out_of_scope


def test_tau_functional_writes_not_flagged():
    """功能层写(sdns/slb——框架 per-case clear 辖区)不在本门辖区。"""
    steps = [{"E": "APV_0", "F": "cmds_config",
              "G": "sdns on\nsdns listener 172.16.34.70\nslb virtual http v1 172.16.34.70 80"}]
    r = check_tau_coverage(steps)
    assert r.ok and not r.out_of_scope


# ------------------------------------------------------------- emit 门
def _emit(autoid: str, steps: list, **kw):
    from main.ist_core.tools.device.emit_xlsx_tool import compile_emit
    return compile_emit.func(autoid=autoid, steps=steps,
                             init_commands="sdns on", out_name=autoid, **kw)


@pytest.fixture()
def aid():
    autoid = "203699999999000003"
    yield autoid
    import shutil
    shutil.rmtree(ROOT / "workspace" / "outputs" / autoid, ignore_errors=True)


def _polluter_steps(with_tau: bool = False) -> list:
    g = ("no ip address port2\nvlan port2 vlan100 100\n"
         "ip address vlan100 172.16.34.70 24")
    steps = [
        {"E": "APV_0", "F": "cmds_config", "G": g, "desc": "vlan 迁移"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener", "desc": "观测"},
        {"E": "check_point", "F": "found", "G": r"172\.16\.34\.70", "desc": "断言"},
    ]
    if with_tau:
        steps.append({"E": "APV_0", "F": "cmds_config",
                      "G": "no ip address vlan100\nno vlan vlan100\n"
                           "ip address port2 172.16.34.70 24",
                      "desc": "案尾恢复"})
    return steps


def test_gate_reports_missing_tau(aid):
    out = _emit(aid, _polluter_steps(with_tau=False))
    assert out.startswith("error: paired-teardown gate"), out[:200]
    assert "no vlan vlan100" in out and "NEEDS_USER_DECISION" in out
    nd = ROOT / "workspace" / "outputs" / aid / "needs_decision.json"
    claims = json.loads(nd.read_text(encoding="utf-8"))["claims"]
    mt = [c for c in claims if c.get("claim_kind") == "missing_teardown"]
    assert mt and "no vlan vlan100" in mt[0]["suggested_tau"]
    assert not (ROOT / "workspace" / "outputs" / aid / "case.xlsx").exists()


def test_gate_passes_with_tau(aid):
    out = _emit(aid, _polluter_steps(with_tau=True))
    assert not out.startswith("error: paired-teardown gate"), out[:200]


def test_gate_user_decision_escape(aid):
    outd = ROOT / "workspace" / "outputs" / aid
    outd.mkdir(parents=True, exist_ok=True)
    (outd / "needs_decision.json").write_text(json.dumps({
        "autoid": aid, "claims": [{"claim_kind": "missing_teardown",
                                   "commands": ["vlan port2 vlan100 100"]}]}),
        encoding="utf-8")
    (outd / "user_decision.json").write_text(json.dumps({
        "autoid": aid, "decision": "改预期"}), encoding="utf-8")
    out = _emit(aid, _polluter_steps(with_tau=False))
    assert not out.startswith("error: paired-teardown gate")


def test_gate_env_off(aid, monkeypatch):
    monkeypatch.setenv("IST_TAU_GATE", "0")
    out = _emit(aid, _polluter_steps(with_tau=False))
    assert not out.startswith("error: paired-teardown gate")


# ------------------------------------------------------------- 题面与 token
def test_questions_missing_teardown_wording():
    from main.ist_core.compile_engine_v8.questions import build_questions, validate_questions
    a = "203699999999000004"
    ledgers = {a: {"autoid": a, "claims": [{
        "claim_kind": "missing_teardown", "commands": ["vlan port2 vlan100 100"],
        "suggested_tau": ["no vlan vlan100"], "reason": "缺案尾恢复"}]}}
    qs = build_questions(ledgers)
    assert len(qs) == 1 and "残留" in qs[0]["question"]
    assert "no vlan vlan100" in qs[0]["options"][0]["description"]
    assert validate_questions(qs, ledgers)


def test_answer_token_reflow_tau():
    from main.ist_core.compile_engine_v8.nodes import _answer_token, _TOKEN_CN
    assert _answer_token("bed", "重编补自清") == "reflow_tau"
    assert _answer_token("bed", "床已处理,复跑验证") == "retry"
    assert "reflow_tau" in _TOKEN_CN


def test_bed_panel_self_polluter_options():
    from main.ist_core.compile_engine_v8.engine_tool import _contradiction_question
    q = _contradiction_question({
        "autoid": "203699999999000005", "kind": "bed", "self_polluter": True,
        "missing_tau": ["vlan port2 vlan100 100"],
        "suggested_tau": ["no vlan vlan100"]})
    labels = [o["label"] for o in q["options"]]
    assert "重编补自清" in labels and "床已处理,复跑验证" not in labels, labels
    assert q["_tokens"]["重编补自清"] == "reflow_tau"
