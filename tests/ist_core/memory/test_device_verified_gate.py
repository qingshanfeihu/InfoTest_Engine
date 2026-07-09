"""device_verified 第二权威源回归(V6 支柱2a;E1:v12 footprint 写回 28/28 skip 根治)。

四象限:pass+命令在卷→写入;pass+命令不在卷→拒(幻觉);fail 卷→拒;无台账→拒。
另守:开关回退、writeback 降级重试链。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.memory.footprint.schema import RawFact
from main.ist_core.memory.footprint import merger as M

_A = "203099999999900401"


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    led = tmp_path / "runtime" / "logs" / "verified_runs.jsonl"
    led.parent.mkdir(parents=True)
    monkeypatch.setattr(M, "_project_root", lambda: tmp_path)

    def write(verdict="pass", cmds=("sdns on", "show statistics sdns pool p1"), run_ts=100.0):
        with led.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"autoid": _A, "verdict": verdict, "run_ts": run_ts,
                                "apv_cmds": list(cmds)}, ensure_ascii=False) + "\n")
    return write


def _fact(cmd="show statistics sdns pool p1", run_ts=100.0):
    return RawFact(fact_kind="cli_command", feature_path=["statistics", "sdns"],
                   fact_key=cmd, cli_syntax=cmd,
                   device_evidence={"autoid": _A, "run_ts": run_ts})


def test_pass_and_on_sheet_accepted(ledger):
    ledger()
    assert M._evidence_supports(_fact()) is True


def test_hallucinated_command_rejected(ledger):
    ledger()
    assert M._evidence_supports(_fact(cmd="sdns magic nonexistent")) is False


def test_fail_run_rejected(ledger):
    ledger(verdict="fail")
    assert M._evidence_supports(_fact()) is False


def test_no_ledger_entry_rejected(ledger):
    ledger(run_ts=999.0)   # run_ts 不匹配 = 没这条记录
    assert M._evidence_supports(_fact(run_ts=100.0)) is False


def test_switch_off_restores_manual_only(ledger, monkeypatch):
    ledger()
    monkeypatch.setenv("IST_WRITEBACK_DEVICE_AUTHORITY", "0")
    assert M._evidence_supports(_fact()) is False


def test_device_evidence_never_falls_back_to_manual(ledger):
    # 传了 device_evidence 但校验不过 → 不回落手册分支(防绕行)
    ledger(verdict="fail")
    f = _fact()
    f.evidence_file = "10.5_cli__part1.md"
    f.evidence_quote = "sdns"
    assert M._evidence_supports(f) is False


def test_evidence_persists_device_run_anchor():
    """K 锚持久化(理论 §5.1):device_evidence 的 (autoid, run_ts, build) 落进
    条目 evidence.device_run;缺位诚实缺位(uncertain 只有 autoid 谱系锚)。"""
    f = _fact()
    f.device_evidence = {"autoid": "203031750000000777", "run_ts": 123.0,
                         "build": "10.5.0.583"}
    ev = M._evidence(f)
    assert ev["device_run"] == {"autoid": "203031750000000777", "run_ts": 123.0,
                                "build": "10.5.0.583"}
    f2 = _fact()
    f2.device_evidence = {"autoid": "203031750000000777", "run_ts": None}
    ev2 = M._evidence(f2)
    assert ev2["device_run"] == {"autoid": "203031750000000777"}
    f3 = _fact()
    f3.device_evidence = {}
    assert "device_run" not in M._evidence(f3)
