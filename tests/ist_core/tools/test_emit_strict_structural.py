"""compile_emit 的结构门集成：必崩门(found_times/dangling)无条件 + 启发式门(allowlist)仍 opt-in。"""

from __future__ import annotations

import json

from main.ist_core.tools.device.emit_xlsx_tool import compile_emit

_DANGLING = [
    # cmds_config(多条)框架遍历不收返回 → result=None → found(None) 抛 TypeError 崩整份文件 = 真
    # dangling。(单条 cmd_config 返回 output 非 None、不崩——见 test_structural_gate 正向用例)
    {"E": "APV_0", "F": "cmds_config", "G": "sdns listener 172.16.34.200"},
    {"E": "check_point", "F": "found", "G": "172.16.34.200"},
]


def test_strict_structural_rejects_dangling_assertion():
    r = compile_emit.invoke({
        "autoid": "t_dangling", "steps_json": json.dumps(_DANGLING),
        "init_commands": "sdns on", "strict_structural": True,
    })
    assert r.startswith("error")
    assert "dangling_assertion" in r


def test_default_still_blocks_crash_gates_but_skips_heuristic_gates(tmp_path):
    """必崩门(dangling/found_times)**无条件**——strict_structural 默认 False 也拦。

    旧行为「v1 默认跳过全部结构门」已被有意反转：悬空断言漏网实证崩了整份文件
    (dongkl 778012 重编版 → 1 pass + 33 unknown)。启发式门(cmd allowlist,可能误杀)
    仍 opt-in——两类门的边界见 structural_gate.check_crash_gates_mandatory docstring。
    """
    r = compile_emit.invoke({
        "autoid": "t_v1compat", "steps_json": json.dumps(_DANGLING),
        "init_commands": "sdns on", "out_name": "t_v1compat",
    })
    assert r.startswith("error") and "dangling_assertion" in r   # 必崩门:默认也拦
    assert "cmd_not_in_allowlist" not in r                        # 启发式门:默认不跑


def test_strict_structural_passes_well_formed_case():
    good = [
        {"E": "APV_0", "F": "cmd_config", "G": "sdns listener 172.16.34.200"},
        {"E": "APV_0", "F": "cmd_config", "G": "show sdns listener"},
        {"E": "check_point", "F": "found", "G": "172.16.34.200"},
    ]
    r = compile_emit.invoke({
        "autoid": "t_good", "steps_json": json.dumps(good),
        "init_commands": "sdns on", "strict_structural": True, "out_name": "t_good",
    })
    # 结构门 + IP 门都过 → 正常产出（不含结构违规）
    assert "dangling_assertion" not in r
    assert "cmd_not_in_allowlist" not in r
