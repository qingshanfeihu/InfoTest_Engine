"""通用欠定上报工具(补 655173 型欠定台账通道,2026-07-13)。

655173 实证:worker 声称「本床无验证路径」型欠定,但 compile_check_verifiability 入参
只表达分布类断言可验性(algo/n_requests/n_pools),承载不了它——worker 停手返回
STATUS: needs_user_decision 却无台账,引擎按 A 层「先问后落」不认散文声称,判 escalated。
compile_report_underdetermined 补这个结构化上报通道。
"""
from __future__ import annotations

import json

from main.ist_core.tools.device.verifiability_tool import (
    compile_report_underdetermined, _land_needs_decision,
)


def _outdir(tmp_path, autoid, monkeypatch):
    """把落盘根重定向到 tmp(工具用 __file__.parents[4]/workspace/outputs)。"""
    import main.ist_core.tools.device.verifiability_tool as vt
    real = vt._land_needs_decision

    def _redirected(aid, kind, entry):
        nd = tmp_path / aid
        nd.mkdir(parents=True, exist_ok=True)
        p = nd / "needs_decision.json"
        data = {"autoid": aid, "claims": []}
        if p.is_file():
            data = json.loads(p.read_text())
        data["claims"] = [c for c in data["claims"] if c.get("claim_kind") != kind]
        data["claims"].append({**entry, "claim_kind": kind})
        p.write_text(json.dumps(data, ensure_ascii=False))
        return True

    monkeypatch.setattr(vt, "_land_needs_decision", _redirected)


def test_report_lands_ledger_and_returns_marker(tmp_path, monkeypatch):
    _outdir(tmp_path, "203600000000000173", monkeypatch)
    out = compile_report_underdetermined.func(
        autoid="203600000000000173",
        reason="trigger host routera cannot emit the HTTP/2 form the intent requires; "
               "no equivalent variant on this bed",
        suggested_fix="change the expected to what this bed can observe, or note the missing capability")
    assert "NEEDS_USER_DECISION" in out
    assert "verification_path_absent" in out
    assert "routera cannot emit" in out
    # 台账落盘且结构化
    p = tmp_path / "203600000000000173" / "needs_decision.json"
    assert p.is_file()
    data = json.loads(p.read_text())
    claim = data["claims"][0]
    assert claim["claim_kind"] == "verification_path_absent"
    assert "routera" in claim["reason"]


def test_ordering_sensitive_flag_recorded(tmp_path, monkeypatch):
    _outdir(tmp_path, "203600000000000200", monkeypatch)
    compile_report_underdetermined.func(
        autoid="203600000000000200", reason="ordered trace not observable here",
        ordering_sensitive=True)
    data = json.loads((tmp_path / "203600000000000200" / "needs_decision.json").read_text())
    assert data["claims"][0]["ordering_sensitive"] is True


def test_shared_ledger_merges_by_claim_kind(tmp_path):
    """verifiability 与通用上报共用 _land_needs_decision:同 claim_kind 合并、不同并存。"""
    import main.ist_core.tools.device.verifiability_tool as vt
    from pathlib import Path
    # 直接测共享函数的合并语义(重定向 root 到 tmp via monkeypatch-free 路径构造)
    outd = tmp_path / "workspace" / "outputs" / "203600000000000201"
    outd.mkdir(parents=True)

    import unittest.mock as mock
    with mock.patch.object(Path, "resolve", return_value=tmp_path / "x" / "x" / "x" / "x" / "x"):
        # parents[4] = tmp_path
        vt._land_needs_decision("203600000000000201", "distribution", {"reason": "a"})
        vt._land_needs_decision("203600000000000201", "verification_path_absent", {"reason": "b"})
        vt._land_needs_decision("203600000000000201", "distribution", {"reason": "a2"})
    data = json.loads((outd / "needs_decision.json").read_text())
    kinds = sorted(c["claim_kind"] for c in data["claims"])
    assert kinds == ["distribution", "verification_path_absent"]   # distribution 合并为一条
    dist = next(c for c in data["claims"] if c["claim_kind"] == "distribution")
    assert dist["reason"] == "a2"                                   # 最新覆盖
