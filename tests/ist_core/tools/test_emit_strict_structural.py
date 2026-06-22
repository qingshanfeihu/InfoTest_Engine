"""qa_emit_xlsx 的 v2 结构门集成（strict_structural opt-in）+ v1 行为不变。"""

from __future__ import annotations

import json

from main.ist_core.tools.device.emit_xlsx_tool import qa_emit_xlsx

_DANGLING = [
    {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 172.16.34.200"},
    {"E": "check_point", "F": "found", "G": "172.16.34.200"},
]


def test_strict_structural_rejects_dangling_assertion():
    r = qa_emit_xlsx.invoke({
        "autoid": "t_dangling", "steps_json": json.dumps(_DANGLING),
        "init_commands": "sdns on", "strict_structural": True,
    })
    assert r.startswith("error")
    assert "dangling_assertion" in r


def test_v1_default_skips_structural_gate(tmp_path):
    # strict_structural 默认 False → 结构门不介入（v1 行为不变）。
    # 该步骤会通过结构门之外的正常流程（这里只断言"不因结构门报错"）。
    r = qa_emit_xlsx.invoke({
        "autoid": "t_v1compat", "steps_json": json.dumps(_DANGLING),
        "init_commands": "sdns on", "out_name": "t_v1compat",
    })
    assert "dangling_assertion" not in r


def test_strict_structural_passes_well_formed_case():
    good = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 172.16.34.200"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
        {"E": "check_point", "F": "found", "G": "172.16.34.200"},
    ]
    r = qa_emit_xlsx.invoke({
        "autoid": "t_good", "steps_json": json.dumps(good),
        "init_commands": "sdns on", "strict_structural": True, "out_name": "t_good",
    })
    # 结构门 + IP 门都过 → 正常产出（不含结构违规）
    assert "dangling_assertion" not in r
    assert "cmd_not_in_allowlist" not in r
