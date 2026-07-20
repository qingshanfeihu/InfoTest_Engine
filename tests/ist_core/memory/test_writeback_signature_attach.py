"""gap② S2-reduced:device_run 证据挂载手册签名 + verbatim 标记可读回。

Design 裁决(2026-07-20):
⑴ 挂接判据=**命令词 token 序列完全相等**;不等宁可新建带 `syntax_provenance:
   "device_run_verbatim"` 的条目——保守侧,绝不污染手册签名。
⑵ 打了标记的条目在渲染/检索层必须**真区分**,否则重蹈 #61「知识存了读不回」。

边界:本组不触 `_append_behavior` 的 uncertain→verified 升格分支(R2 单独派单)。
"""
from __future__ import annotations

from main.ist_core.memory.footprint.merger import (
    _append_cli_command, command_words,
)
from main.ist_core.memory.footprint.schema import RawFact


def _manual_node() -> dict:
    """已有手册出处签名的节点(source_file 为凭)。"""
    return {"cli": {"commands": [{
        "fact_key": "ssl activate certificate <host_name> [certificate_index]",
        "command": "ssl activate certificate <host_name> [certificate_index]",
        "evidence": {"source_file": "cli_10.5_Chapter11.md",
                     "quoted_text": "ssl activate certificate <host_name>"},
    }]}}


def _device_fact(cmd: str) -> RawFact:
    return RawFact(
        fact_kind="cli_command", feature_path=["ssl", "activate"],
        fact_key=cmd, cli_syntax=cmd,
        evidence_file="", evidence_quote=cmd,
        device_evidence={"autoid": "205400000000000003", "run_ts": 1784472473.5,
                         "build": "InfosecOS_Beta_APV_HG_K_10_5_0_585"},
        raw_invocation=cmd + ",prompt=YES",
    )


# ------------------------------------------------------------------ 命令词提取
def test_command_words_stops_at_arg_and_placeholder():
    assert command_words("ssl activate certificate vh1") == ["ssl", "activate", "certificate"]
    assert command_words("ssl activate certificate <host_name> [idx]") == \
        ["ssl", "activate", "certificate"]


def test_command_words_does_not_strip_verbs():
    """与 _behavior_feature_head 的关键差别:show 保留——否则观测命令会与配置命令判等。"""
    assert command_words("show ssl certificate vh1") == ["show", "ssl", "certificate"]
    from main.ist_core.compile_engine_v8.uncertain import _behavior_feature_head
    assert _behavior_feature_head("show ssl certificate vh1") != \
        command_words("show ssl certificate vh1"), "两函数语义必须保持不同,勿混用"


# --------------------------------------------------------------- ⑴ 挂载/不挂载
def test_attaches_device_run_to_existing_manual_signature():
    fp = _manual_node()
    res = _append_cli_command(fp, _device_fact("ssl activate certificate vh1"))
    cmds = fp["cli"]["commands"]
    assert len(cmds) == 1, f"命令词相等时不得新建重条目:{[c['command'] for c in cmds]}"
    assert res == "update"
    ev = cmds[0]["evidence"]
    assert ev["device_run"]["autoid"] == "205400000000000003"
    assert ev["device_run"]["build"].endswith("585")
    assert ev["source_file"] == "cli_10.5_Chapter11.md", "手册签名与出处必须原样保留"
    assert cmds[0]["command"] == "ssl activate certificate <host_name> [certificate_index]"


def test_observation_command_does_not_attach_to_config_signature():
    """裁决⑴保守侧的核心反例:`show ssl certificate` 命令词序列 ≠ 配置命令,不得挂载。"""
    fp = {"cli": {"commands": [{
        "fact_key": "ssl certificate <host_name>",
        "command": "ssl certificate <host_name>",
        "evidence": {"source_file": "cli.md", "quoted_text": "ssl certificate"},
    }]}}
    _append_cli_command(fp, _device_fact("show ssl certificate vh1"))
    cmds = fp["cli"]["commands"]
    assert len(cmds) == 2, "观测命令必须另立条目,不能挂到配置命令的手册签名上"
    assert cmds[1]["syntax_provenance"] == "device_run_verbatim"
    assert cmds[0]["evidence"].get("device_run") is None, "手册签名不得被观测命令污染"


def test_no_manual_signature_creates_marked_entry():
    fp = {"cli": {"commands": []}}
    _append_cli_command(fp, _device_fact("ssl activate certificate vh1"))
    entry = fp["cli"]["commands"][0]
    assert entry["syntax_provenance"] == "device_run_verbatim"
    assert entry["evidence"]["raw_invocation"] == "ssl activate certificate vh1,prompt=YES"


def test_non_manual_entry_is_not_an_attach_target():
    """只往手册出处签名上累证据;verbatim 条目之间不互相挂载(否则实参条目滚雪球)。"""
    fp = {"cli": {"commands": [{
        "fact_key": "ssl activate certificate vh9",
        "command": "ssl activate certificate vh9",
        "evidence": {"quoted_text": "ssl activate certificate vh9"},
        "syntax_provenance": "device_run_verbatim",
    }]}}
    _append_cli_command(fp, _device_fact("ssl activate certificate vh1"))
    assert len(fp["cli"]["commands"]) == 2


def test_manual_sourced_fact_gets_no_verbatim_marker():
    """健康路径(手册出处写回)不打标记——标记只标设备原文。"""
    fp = {"cli": {"commands": []}}
    manual = RawFact(fact_kind="cli_command", feature_path=["ssl", "activate"],
                     fact_key="ssl activate certificate <host_name>",
                     cli_syntax="ssl activate certificate <host_name>",
                     evidence_file="cli.md", evidence_quote="ssl activate certificate")
    _append_cli_command(fp, manual)
    assert "syntax_provenance" not in fp["cli"]["commands"][0]


# --------------------------------------------------------------- ⑵ 读得回
def test_render_surfaces_verbatim_marker():
    from main.ist_core.tools.knowledge.footprint_lookup import _format_node
    node = {"feature_id": "ssl.activate", "level": "leaf", "cli": {"commands": [
        {"fact_key": "a", "command": "ssl activate certificate <host_name>",
         "evidence": {"source_file": "cli.md"}},
        {"fact_key": "b", "command": "ssl activate certificate vh1",
         "evidence": {}, "syntax_provenance": "device_run_verbatim"},
    ]}}
    out = _format_node(node)
    manual_line = [l for l in out.splitlines() if "<host_name>" in l][0]
    verbatim_line = [l for l in out.splitlines() if "vh1" in l][0]
    assert "verbatim" in verbatim_line, f"标记未浮现,worker 读不回:{verbatim_line}"
    assert "verbatim" not in manual_line, "手册签名不该被标注"


# ------------------------------------------- Design 精化:歧义(多签名命中)不赌挂载
def test_ambiguous_multi_signature_match_creates_verbatim_entry_instead():
    """同命令词序列命中多条手册签名 → 无从判该挂哪条,不挂;新建带标记条目。"""
    fp = {"cli": {"commands": [
        {"fact_key": "s1", "command": "ssl activate certificate <host_name>",
         "evidence": {"source_file": "ch11.md"}},
        {"fact_key": "s2", "command": "ssl activate certificate <host_name> <type>",
         "evidence": {"source_file": "ch12.md"}},
    ]}}
    _append_cli_command(fp, _device_fact("ssl activate certificate vh1"))
    cmds = fp["cli"]["commands"]
    assert len(cmds) == 3, "歧义时不得挑一条挂"
    assert cmds[2]["syntax_provenance"] == "device_run_verbatim"
    for i in (0, 1):
        assert "device_run" not in cmds[i]["evidence"], "歧义时任何一条签名都不该被写入"


def test_single_match_still_attaches_after_ambiguity_rule():
    """精化不得误伤唯一命中的正常路径。"""
    fp = _manual_node()
    assert _append_cli_command(fp, _device_fact("ssl activate certificate vh1")) == "update"
    assert len(fp["cli"]["commands"]) == 1
