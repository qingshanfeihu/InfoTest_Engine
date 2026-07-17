"""provenance 必传门回归(V4 步骤0,2026-07-04)。

实证:main-orchestrated 主路 worker 产的 34 卷 provenance.json 数量=0——公共契约
断裂使 grade 免检索/四层归因/上机写回全部名存实亡(V3 步骤2/4/5 的机械根因)。
prompt 层约束在长上下文下必被遗忘(2026-07-02 零 grade 合并同型事故),故 A 层强制;
原生对象通道优先(字符串通道经供应商序列化实证拖尾失败)。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from main.ist_core.tools.device import compile_emit
from main.ist_core.compile_engine_v8 import _shared as _sh

AID = "203031750000000601"

_STEPS = [
    {"D": "触发", "E": "test_env", "F": "routera", "G": "dig @172.16.34.70 t.com"},
    {"D": "断言", "E": "check_point", "F": "found", "G": r"\b172\.16\.35\.213\b"},
]
_INIT = ("sdns on\nsdns listener 172.16.34.70\nsdns host name t.com\n"
         "sdns service ip s1 172.16.35.213\nsdns pool name p1\n"
         "sdns pool service p1 s1\nsdns host pool t.com p1")
_PROV = {"autoid": AID, "steps": [
    {"layer": "V", "source": {"kind": "manual", "ref": "cli_10.5_Chapter26.md"}},
    {"layer": "V", "source": {"kind": "membership_derived", "ref": "init p1 成员集合"}},
]}


@pytest.fixture()
def _mandatory(monkeypatch):
    monkeypatch.delenv("IST_PROVENANCE_OPTIONAL", raising=False)
    yield
    shutil.rmtree(_sh.outputs_root() / AID, ignore_errors=True)


def test_emit_rejects_missing_provenance(_mandatory):
    out = compile_emit.invoke({"autoid": AID, "steps": _STEPS,
                               "init_commands": _INIT, "out_name": AID})
    assert out.startswith("error") and "provenance" in out


def test_emit_accepts_native_provenance_object(_mandatory):
    out = compile_emit.invoke({"autoid": AID, "steps": _STEPS, "init_commands": _INIT,
                               "out_name": AID, "provenance": _PROV})
    assert "produced structurally-correct" in out, out
    pv = _sh.outputs_root() / AID / "case.provenance.json"
    assert pv.is_file()
    j = json.loads(pv.read_text(encoding="utf-8"))
    assert j.get("steps") and j["steps"][0].get("layer") in ("G", "E", "V")


def test_emit_optional_env_restores_old_behavior(_mandatory, monkeypatch):
    monkeypatch.setenv("IST_PROVENANCE_OPTIONAL", "1")
    out = compile_emit.invoke({"autoid": AID, "steps": _STEPS,
                               "init_commands": _INIT, "out_name": AID})
    assert "produced structurally-correct" in out
