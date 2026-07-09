"""compile_emit 的分布区间断言（dist 声明）集成：展开 → 过结构门 + 守恒/反恒真门 + provenance 同步。"""

from __future__ import annotations

import json
from pathlib import Path

from main.ist_core.tools.device.emit_xlsx_tool import compile_emit

_ROOT = Path(__file__).resolve().parents[3]


def _dist_steps(buckets, total=30):
    return [
        {"E": "APV_0", "F": "cmd_config", "G": 'sdns host method "x" "rr"'},
        {"E": "test_env", "F": "clientc", "G": f"dnsperf -s 172.16.34.70 -n {total}"},
        {"E": "APV_0", "F": "cmd_config", "G": "show statistics sdns pool p1"},
        {"E": "check_point", "F": "dist",
         "dist": {"total": total, "field": "Hit:\\s*", "buckets": buckets}},
    ]


def test_dist_expands_and_passes_strict_gate():
    steps = _dist_steps([{"anchor": "m1", "expected": 10, "tol": 2},
                         {"anchor": "m2", "expected": 10, "tol": 2},
                         {"anchor": "m3", "expected": 10, "tol": 2}])
    r = compile_emit.invoke({"autoid": "t_dist", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_dist",
                             "strict_structural": True})
    assert not r.split("\n")[0].startswith("error"), r
    assert "check_points=present" in r            # 3 条展开断言均落地、非悬空
    assert "dangling_assertion" not in r


def test_dist_conservation_break_rejected():
    # Σ上界=8 容纳不下 total=30 → 守恒门打回
    steps = _dist_steps([{"anchor": "m1", "expected": 3, "tol": 1},
                         {"anchor": "m2", "expected": 3, "tol": 1}], total=30)
    r = compile_emit.invoke({"autoid": "t_dist_cb", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "strict_structural": True})
    assert r.startswith("error") and "守恒" in r


def test_dist_tautology_wide_rejected():
    # 单桶区间宽到上界≥total → 反恒真门打回
    steps = _dist_steps([{"anchor": "m1", "expected": 15, "tol": 20},
                         {"anchor": "m2", "expected": 15, "tol": 20}], total=30)
    r = compile_emit.invoke({"autoid": "t_dist_tw", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "strict_structural": True})
    assert r.startswith("error") and ("恒真" in r or "上界" in r)


def test_dist_provenance_expands_in_tandem():
    steps = _dist_steps([{"anchor": "m1", "expected": 15, "tol": 3},
                         {"anchor": "m2", "expected": 15, "tol": 3}], total=30)
    prov = {"autoid": "t_dist_prov", "provisional": True, "steps": [
        {"E": "", "F": "", "G": "", "layer": "G", "source": {"kind": "intent", "ref": "rr"}},
        {"E": "", "F": "", "G": "", "layer": "E", "source": {"kind": "env_facts", "ref": "vip"}},
        {"E": "", "F": "", "G": "", "layer": "G", "source": {"kind": "footprint", "ref": "stat"}},
        {"E": "", "F": "", "G": "", "layer": "V", "source": {"kind": "distribution_derived", "ref": "rr"}},
    ]}
    r = compile_emit.invoke({"autoid": "t_dist_prov", "steps_json": json.dumps(steps),
                             "init_commands": "sdns on", "out_name": "t_dist_prov",
                             "strict_structural": True, "provenance_json": json.dumps(prov)})
    assert "provenance side-mounted" in r, r
    # dist 1 步 → 展开成 2 条 distribution_derived V，与展开后 steps 逐位对齐
    p = _ROOT / "workspace" / "outputs" / "t_dist_prov" / "case.provenance.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    vd = [s for s in d["steps"] if s["source"]["kind"] == "distribution_derived"]
    assert len(vd) == 2
    assert all(s["layer"] == "V" for s in vd)
