"""C2: cli 命令按完整 cli_syntax 去重 — no/show/clear/配置 四态并存。"""
from __future__ import annotations

from main.ist_core.memory.footprint.merger import _append_cli_command
from main.ist_core.memory.footprint.schema import RawFact, leaf_template


def _mk(syntax, key, params=None):
    return RawFact(
        fact_kind="cli_command", feature_path=["slb", "real", "http"],
        fact_key=key, cli_syntax=syntax, parameters=params or [],
        evidence_file="x.md", evidence_quote=syntax,
    )


def test_four_states_coexist_despite_same_fact_key():
    """旧逻辑按 fact_key 去重会丢 3 条；现按 cli_syntax 全留。"""
    fp = leaf_template("slb.real.http")
    states = [
        "slb real http <rs_name>",
        "no slb real http",
        "show slb real http",
        "clear slb real http",
    ]
    for syn in states:
        assert _append_cli_command(fp, _mk(syn, "syntax")) == "append"
    cmds = {c["command"] for c in fp["cli"]["commands"]}
    assert cmds == set(states)


def test_identical_syntax_dedups():
    fp = leaf_template("slb.real.http")
    _append_cli_command(fp, _mk("show slb real http", "k1"))
    r = _append_cli_command(fp, _mk("show slb real http", "k2"))
    assert r == "skip"
    assert len(fp["cli"]["commands"]) == 1


def test_identical_syntax_merges_params():
    fp = leaf_template("slb.real.http")
    _append_cli_command(fp, _mk("slb real http <rs_name>", "k1"))
    r = _append_cli_command(
        fp, _mk("slb real http <rs_name>", "k2", [{"name": "rs_name", "type": "string"}])
    )
    assert r == "append"
    assert len(fp["cli"]["commands"]) == 1
    target = fp["cli"]["commands"][0]
    assert [p["name"] for p in target["parameters"]] == ["rs_name"]
