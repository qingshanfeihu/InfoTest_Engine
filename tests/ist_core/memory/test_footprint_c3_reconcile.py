"""C3: 全树 reconcile —— 补建中间节点 + 俄罗斯方块叠加 level + children。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.ist_core.memory.footprint.reconcile import reconcile, _height_to_level
from main.ist_core.memory.footprint.schema import node_template


def _seed(tmp: Path, leaves: list[str]) -> Path:
    nodes = tmp / "nodes"
    nodes.mkdir(parents=True)
    for fid in leaves:
        n = node_template(fid)
        n["cli"]["commands"].append({"fact_key": "syntax", "command": fid.replace(".", " ")})
        (nodes / f"{fid}.json").write_text(json.dumps(n, ensure_ascii=False))
    return nodes


def _tree(nodes: Path) -> dict[str, tuple[str, list]]:
    out = {}
    for f in nodes.glob("*.json"):
        d = json.loads(f.read_text())
        out[d["feature_id"]] = (d["level"], d.get("children", []))
    return out


def test_height_to_level():
    assert _height_to_level(0) == "leaf"
    assert _height_to_level(1) == "trunk"
    assert _height_to_level(2) == "branch"
    assert _height_to_level(5) == "branch"


def test_slb_tree_levels(tmp_path):
    nodes = _seed(tmp_path, [
        "slb.all", "slb.policy.default", "slb.policy.static",
        "slb.group.member", "slb.group.method", "slb.mode.ircookie",
    ])
    reconcile(tmp_path)
    t = _tree(nodes)
    assert t["slb"][0] == "branch"
    assert t["slb.policy"][0] == "trunk"
    assert t["slb.group"][0] == "trunk"
    assert t["slb.mode"][0] == "trunk"
    assert t["slb.policy.default"][0] == "leaf"
    assert t["slb.all"][0] == "leaf"


def test_intermediate_nodes_backfilled(tmp_path):
    nodes = _seed(tmp_path, ["slb.policy.default"])
    stats = reconcile(tmp_path)
    t = _tree(nodes)
    
    assert "slb" in t and "slb.policy" in t
    assert stats["created"] == 2


def test_children_written_to_disk(tmp_path):
    nodes = _seed(tmp_path, ["slb.all", "slb.policy.default", "slb.group.member"])
    reconcile(tmp_path)
    t = _tree(nodes)
    assert set(t["slb"][1]) == {"slb.all", "slb.policy", "slb.group"}
    assert t["slb.policy"][1] == ["slb.policy.default"]


def test_node_both_command_and_parent(tmp_path):
    """http.rewrite.body 既有 cli 又有子节点 → trunk 但保留内容。"""
    nodes = _seed(tmp_path, ["http.rewrite.body", "http.rewrite.body.limit"])
    reconcile(tmp_path)
    t = _tree(nodes)
    assert t["http.rewrite.body"][0] == "trunk"
    
    d = json.loads((nodes / "http.rewrite.body.json").read_text())
    assert len(d["cli"]["commands"]) == 1


def test_empty_dir(tmp_path):
    (tmp_path / "nodes").mkdir()
    stats = reconcile(tmp_path)
    assert stats["total"] == 0
