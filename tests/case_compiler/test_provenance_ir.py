"""V3 步骤1：三层 Provenance IR + compile_emit 旁挂（默认空＝V2 行为不变）。"""

from __future__ import annotations

import json
from pathlib import Path

from main.case_compiler.provenance_ir import (
    CaseProvenance, StepIR, StepSource, parse_provenance, steps_match,
)
from main.ist_core.tools.device.emit_xlsx_tool import compile_emit


def _prov():
    return CaseProvenance(autoid="t1", steps=[
        StepIR("APV_0", "cmd_config", "sdns listener 172.16.34.200", "G",
               StepSource("footprint", "sdns.listener")),
        StepIR("APV_0", "cmd_config", "show sdns listener", "G", StepSource("footprint", "sdns.listener")),
        StepIR("check_point", "found", "172.16.34.200", "V", StepSource("manual", "10.5_cli:1234")),
    ])


def test_roundtrip_json():
    p = _prov()
    p2 = CaseProvenance.from_json(p.to_json())
    assert p2.autoid == "t1"
    assert len(p2.steps) == 3
    assert p2.steps[0].layer == "G"
    assert p2.steps[0].source.kind == "footprint"
    assert p2.steps[2].source.ref == "10.5_cli:1234"


def test_invalid_layer_and_kind_coerced():
    s = StepIR("APV_0", "cmd_config", "x", "Z", StepSource("bogus", "r"))
    assert s.layer == "V"
    assert s.source.kind == "unknown"


def test_layer_steps_filter():
    p = _prov()
    assert len(p.layer_steps("G")) == 2
    assert len(p.layer_steps("V")) == 1
    assert len(p.layer_steps("E")) == 0


def test_parse_provenance_empty_returns_none():
    assert parse_provenance("") is None
    assert parse_provenance("   ") is None
    assert parse_provenance("{bad json") is None


def test_steps_match():
    p = _prov()
    steps = [{"E": s.E, "F": s.F, "G": s.G} for s in p.steps]
    assert steps_match(p, steps)
    steps[0]["G"] = "different"
    assert not steps_match(p, steps)
    assert not steps_match(p, steps[:2])


def test_emit_without_provenance_writes_no_sidecar(tmp_path):
    steps = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 172.16.34.200"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
        {"E": "check_point", "F": "found", "G": "172.16.34.200"},
    ]
    r = compile_emit.invoke({"autoid": "t_noprov", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_noprov"})
    assert "已产出" in r
    assert "provenance" not in r
    root = Path(__file__).resolve().parents[2]
    assert not (root / "workspace" / "outputs" / "t_noprov" / "case.provenance.json").exists()


def test_emit_with_provenance_writes_sidecar():
    p = _prov()
    steps = [{"E": s.E, "F": s.F, "G": s.G} for s in p.steps]
    r = compile_emit.invoke({"autoid": "t1", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_prov",
                             "provenance_json": p.to_json()})
    assert "provenance 已旁挂: G=2 E=0 V=1" in r
    root = Path(__file__).resolve().parents[2]
    sidecar = root / "workspace" / "outputs" / "t_prov" / "case.provenance.json"
    assert sidecar.exists()
    loaded = CaseProvenance.from_json(sidecar.read_text(encoding="utf-8"))
    assert len(loaded.steps) == 3


def test_emit_with_step_count_mismatch_skips_sidecar():
    # 只有「步骤数」不一致才跳过旁挂（E/F/G 不一致已不触发——emit 按位置回填）
    p = _prov()
    steps = [{"E": s.E, "F": s.F, "G": s.G} for s in p.steps]
    steps.append({"E": "APV_0", "F": "cmd_config", "G": "show sdns pool"})  # steps 比 provenance 多一步
    r = compile_emit.invoke({"autoid": "t1", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_prov_mismatch",
                             "provenance_json": p.to_json()})
    assert "不一致" in r


def test_emit_backfills_efg_when_draft_omits_them():
    # draft 的 provenance 不抄 E/F/G（留空），emit 按位置回填、步骤数一致即旁挂成功（不空转）
    p = _prov()
    steps = [{"E": s.E, "F": s.F, "G": s.G} for s in p.steps]
    for s in p.steps:
        s.E = s.F = s.G = ""
    r = compile_emit.invoke({"autoid": "t1", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_prov_backfill",
                             "provenance_json": p.to_json()})
    assert "已旁挂" in r


# --- 不瞎写硬契约：device_runtime ⟺ <RUNTIME> 占位双向自洽 ---
from main.case_compiler.provenance_ir import check_runtime_consistency, RUNTIME_PLACEHOLDER


def _prov_runtime(cp_g: str, cp_kind: str):
    """构造一个 show + check_point 的 provenance，check_point 的 G/来源由参数定。"""
    return CaseProvenance(autoid="t_rt", steps=[
        StepIR("APV_0", "cmd_config", "show sdns listener", "G", StepSource("footprint", "sdns.listener")),
        StepIR("check_point", "found", cp_g, "V", StepSource(cp_kind, "x")),
    ])


def test_runtime_consistency_clean_placeholder():
    # 占位 + device_runtime：自洽
    assert check_runtime_consistency(_prov_runtime(RUNTIME_PLACEHOLDER, "device_runtime")) == []


def test_runtime_consistency_clean_concrete():
    # 具体值 + manual：自洽
    assert check_runtime_consistency(_prov_runtime("172.16.34.200", "manual")) == []


def test_runtime_consistency_abstain_but_fabricated():
    # 标 device_runtime 却填具体值 = 假装弃权实则编数 → 抓
    probs = check_runtime_consistency(_prov_runtime("172.16.34.200", "device_runtime"))
    assert len(probs) == 1 and "却填了具体值" in probs[0]


def test_runtime_consistency_placeholder_but_lies_source():
    # 填占位却谎称 footprint 有源 → 抓
    probs = check_runtime_consistency(_prov_runtime(RUNTIME_PLACEHOLDER, "footprint"))
    assert len(probs) == 1 and "来源必须标 device_runtime" in probs[0]


def test_emit_rejects_fabricated_runtime_value():
    """strict_structural 链：标 device_runtime 却编数 → emit 打回。"""
    p = _prov_runtime("172.16.34.200", "device_runtime")
    steps = [{"E": s.E, "F": s.F, "G": s.G} for s in p.steps]
    r = compile_emit.invoke({"autoid": "t_rt", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_rt_bad",
                             "strict_structural": True, "provenance_json": p.to_json()})
    assert r.startswith("error") and "不瞎写契约" in r


def test_emit_accepts_honest_placeholder():
    """strict_structural 链：占位 + device_runtime 自洽 → 正常产出 + 旁挂。"""
    p = _prov_runtime(RUNTIME_PLACEHOLDER, "device_runtime")
    steps = [{"E": s.E, "F": s.F, "G": s.G} for s in p.steps]
    r = compile_emit.invoke({"autoid": "t_rt", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_rt_ok",
                             "strict_structural": True, "provenance_json": p.to_json()})
    assert "已产出" in r and "provenance 已旁挂" in r
