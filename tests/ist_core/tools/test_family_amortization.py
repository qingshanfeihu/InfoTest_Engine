"""意图族摊销回归(V4 步骤3,定理3.10 H_G 共享)。

实证(2026-07-04,docs/PLAN_v4_engine.md 调研 C/D):参数化首步句式在 dongkl 34 case
聚出 14 族(最大 12,25/34 被多成员族覆盖);曾试 _intent_similarity 同数据 0 族不可用。
族内配置骨架重合 45-51%(算法族)——族首推导一次,族内 compile_skeleton 复用。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from main.ist_core.tools.device import compile_prep, compile_skeleton


def test_prep_families_on_real_mindmap():
    out = compile_prep.invoke({"mindmap_path": "workspace/inputs/automatic_case/dongkl.txt",
                               "out_name": "_pytest_fam"})
    try:
        assert "意图族" in out
        m = json.loads(Path("workspace/outputs/_pytest_fam/manifest.json").read_text())
        fams = m["families"]
        assert max(f["size"] for f in fams) >= 10           # 算法 12 族(实证下限收紧到10)
        covered = sum(f["size"] for f in fams if f["size"] >= 2)
        assert covered >= 20                                 # 实证 25/34
        assert all("family" in c for c in m["cases"])
        for f in fams:
            assert f["head"] in f["members"]
    finally:
        shutil.rmtree(Path("workspace/outputs/_pytest_fam"), ignore_errors=True)


def test_skeleton_extracts_config_lines(tmp_path):
    from main.ist_core.tools.device import compile_emit
    aid = "203031750000000801"
    try:
        blocks = [
            {"kind": "CONFIG", "cmds": ["sdns on", "sdns listener 172.16.34.70",
                                        "sdns host name t.com", "sdns service ip s1 172.16.35.213",
                                        "sdns pool name p1", "sdns pool service p1 s1",
                                        "sdns host pool t.com p1"], "desc": "基线"},
            {"kind": "OBSERVE_ASSERT", "host": "routera", "cmd": "dig @172.16.34.70 t.com",
             "asserts": [{"op": "found", "pattern": r"\b172\.16\.35\.213\b"}]},
        ]
        r = compile_emit.invoke({"autoid": aid, "blocks": blocks, "out_name": aid})
        assert "已产出" in r
        sk = compile_skeleton.invoke({"autoid": aid})
        assert "族骨架" in sk and "sdns on" in sk and "sdns host pool t.com p1" in sk
        assert "断言形态摘要" in sk
    finally:
        shutil.rmtree(Path("workspace/outputs") / aid, ignore_errors=True)


def test_skeleton_missing_volume_errors():
    assert compile_skeleton.invoke({"autoid": "203031750000009999"}).startswith("error")


def test_skeleton_rejects_path_traversal():
    from main.ist_core.tools.device import compile_skeleton
    for aid in ["../../../../etc/x", "..", "a/b/c"]:
        assert compile_skeleton.invoke({"autoid": aid}).startswith("error")
