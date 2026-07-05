"""provenance 自动组装回归(V6 支柱3,E2:emit 打回率 48-52% 的构造式根治)。

守:①blocks+ref 不传 provenance → emit 成功且盘上 IR 与机械映射逐位一致;
②显式 provenance 优先;③开关回旧行为(必传门);④emit_stats 台账落行。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.tools.device.emit_xlsx_tool import compile_emit

_ROOT = Path(__file__).resolve().parents[3]
_A = "203099999999900301"

_BLOCKS = [
    {"kind": "CONFIG", "ref": "footprint:sdns.listener",
     "cmds": ["sdns on", "sdns listener 172.16.34.70"], "desc": "基线"},
    {"kind": "OBSERVE_ASSERT", "host": "routera", "cmd": "dig @172.16.34.70 t.com",
     "cmd_ref": "precedent:sdns_method.xlsx", "desc": "触发",
     "asserts": [{"op": "found", "pattern": "NOERROR", "ref": "config_derived", "desc": "解析成功"}]},
    {"kind": "SLEEP", "seconds": 2},
]


@pytest.fixture(autouse=True)
def _clean():
    shutil.rmtree(_ROOT / "workspace" / "outputs" / _A, ignore_errors=True)
    yield
    shutil.rmtree(_ROOT / "workspace" / "outputs" / _A, ignore_errors=True)


def test_autoassemble_from_refs(monkeypatch):
    monkeypatch.delenv("IST_PROVENANCE_OPTIONAL", raising=False)
    out = compile_emit.func(_A, blocks=_BLOCKS)
    assert "已产出" in out, out[:300]
    prov = json.loads((_ROOT / "workspace" / "outputs" / _A / "case.provenance.json")
                      .read_text(encoding="utf-8"))
    steps = prov["steps"]
    assert [s["layer"] for s in steps] == ["G", "G", "V", "E"]
    assert steps[0]["source"] == {"kind": "footprint", "ref": "sdns.listener"}
    assert steps[1]["source"] == {"kind": "precedent", "ref": "sdns_method.xlsx"}
    assert steps[2]["source"]["kind"] == "config_derived"
    assert steps[3]["source"]["kind"] == "emit_auto"


def test_explicit_provenance_wins(monkeypatch):
    monkeypatch.setenv("IST_PROVENANCE_OPTIONAL", "1")
    explicit = {"autoid": _A, "steps": [
        {"layer": "G", "source": {"kind": "manual", "ref": "cli_20:99"}},
        {"layer": "V", "source": {"kind": "intent", "ref": ""}},
        {"layer": "E", "source": {"kind": "emit_auto", "ref": ""}}]}
    out = compile_emit.func(_A, blocks=_BLOCKS, provenance=explicit)
    assert "已产出" in out, out[:300]
    prov = json.loads((_ROOT / "workspace" / "outputs" / _A / "case.provenance.json")
                      .read_text(encoding="utf-8"))
    assert prov["steps"][0]["source"]["kind"] == "manual"   # 显式优先,非 footprint


def test_switch_restores_mandatory_gate(monkeypatch):
    monkeypatch.setenv("IST_PROV_AUTOASSEMBLE", "0")
    monkeypatch.delenv("IST_PROVENANCE_OPTIONAL", raising=False)
    out = compile_emit.func(_A, blocks=_BLOCKS)
    assert out.startswith("error:") and "provenance" in out


def test_emit_stats_ledger(monkeypatch):
    stats = _ROOT / "runtime" / "logs" / "emit_stats.jsonl"
    before = stats.read_text(encoding="utf-8").count("\n") if stats.is_file() else 0
    compile_emit.func(_A, blocks=_BLOCKS)
    lines = stats.read_text(encoding="utf-8").splitlines()
    assert len(lines) > before
    rec = json.loads(lines[-1])
    assert rec["autoid"] == _A and rec["channel"] == "blocks" and "reason_class" in rec
