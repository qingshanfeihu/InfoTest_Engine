"""C1: feature_path 正则净化测试 — 对齐 CLI legend，不含启发式字典。"""
from __future__ import annotations

from main.ist_core.memory.footprint.extractor import (
    _feature_path_from_syntax,
    extract_facts,
)


def test_strip_op_prefix_show():
    assert _feature_path_from_syntax("show slb all") == ["slb", "all"]
    assert _feature_path_from_syntax("show running") == ["running"]


def test_strip_op_prefix_no_clear():
    assert _feature_path_from_syntax("no slb real http") == ["slb", "real", "http"]
    assert _feature_path_from_syntax("clear slb real http") == ["slb", "real", "http"]


def test_strip_notation_params():
    assert _feature_path_from_syntax("slb real http <rs_name>") == ["slb", "real", "http"]
    assert _feature_path_from_syntax("slb real http <rs_name> [port]") == ["slb", "real", "http"]
    assert _feature_path_from_syntax("slb policy default <virtual_service> <group_name>") == [
        "slb", "policy", "default"
    ]


def test_strip_enum_braces():
    assert _feature_path_from_syntax("ha synconfig bootup {on|off}") == ["ha", "synconfig", "bootup"]
    assert _feature_path_from_syntax("http rewrite body {on|off}") == ["http", "rewrite", "body"]
    assert _feature_path_from_syntax("slb mode ircookie [x|y]") == ["slb", "mode", "ircookie"]


def test_strip_markdown_escape():
    assert _feature_path_from_syntax(r"slb group member [current\_cookie\_value]") == [
        "slb", "group", "member"
    ]


def test_four_states_collapse_to_one_node():
    """show/no/clear/<param> 四态归到同一 feature_path。"""
    paths = {
        tuple(_feature_path_from_syntax(s))
        for s in [
            "show slb real http",
            "no slb real http",
            "clear slb real http",
            "slb real http <rs_name>",
        ]
    }
    assert paths == {("slb", "real", "http")}


def test_extract_cli_derives_path_from_syntax():
    """cli_command 的 feature_path 由 cli_syntax 派生，不信任 LLM 给的 path。"""
    mock = {"facts": [{
        "fact_kind": "cli_command",
        "feature_path": ["wrong", "path", "on"],
        "fact_key": "syntax",
        "cli_syntax": "ha synconfig bootup on",
        "evidence_file": "x.md", "evidence_quote": "ha synconfig bootup on",
    }]}
    facts = extract_facts("thread_id: t\n", llm_chat=lambda s, u: mock)
    assert len(facts) == 1
    
    
    assert facts[0].feature_path[:3] == ["ha", "synconfig", "bootup"]
    assert facts[0].cli_syntax == "ha synconfig bootup on"
