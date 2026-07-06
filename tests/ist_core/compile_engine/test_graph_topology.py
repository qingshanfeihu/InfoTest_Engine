"""拓扑门(P1-G1a):图节点集 == SKILL.md phases == NODE_TYPES 三方一致;
条件边目标在图内;每节点类型 ∈ {mech, llm, user}。图漂移即红。"""
from __future__ import annotations

import re
from pathlib import Path

from main.ist_core.compile_engine.graph import graph
from main.ist_core.compile_engine.state import NODE_TYPES

_ROOT = Path(__file__).resolve().parents[3]


def test_nodes_match_node_types():
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == set(NODE_TYPES), f"图节点与 NODE_TYPES 漂移: {nodes ^ set(NODE_TYPES)}"
    assert set(NODE_TYPES.values()) <= {"mech", "llm", "user"}


def test_nodes_match_skill_phases():
    md = (_ROOT / "main/ist_core/skills/ist-compile-engine/SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"phases:\s*\[([^\]]+)\]", md)
    assert m, "SKILL.md 缺 engine.phases 声明"
    phases = {p.strip() for p in m.group(1).split(",")}
    assert phases == set(NODE_TYPES), f"SKILL phases 与图漂移: {phases ^ set(NODE_TYPES)}"


def test_edges_targets_exist():
    g = graph.get_graph()
    nodes = set(g.nodes)
    for e in g.edges:
        assert e.source in nodes and e.target in nodes


def test_llm_and_user_holes_declared():
    md = (_ROOT / "main/ist_core/skills/ist-compile-engine/SKILL.md").read_text(encoding="utf-8")
    assert "worker: compile-worker" in md and "attributor: compile-attributor" in md
    # 孔位 skill 真实存在
    assert (_ROOT / "main/ist_core/skills/compile-worker/SKILL.md").is_file()
    assert (_ROOT / "main/ist_core/skills/compile-attributor/SKILL.md").is_file()
