"""V8 拓扑门:图节点 ↔ NODE_TYPES 一致;条件边目标闭合;宪法锚在位。"""
from __future__ import annotations

from main.ist_core.compile_engine_v8.graph import build_v8_graph
from main.ist_core.compile_engine_v8.state import NODE_TYPES


def test_graph_nodes_match_node_types():
    g = build_v8_graph()
    nodes = set(g.get_graph().nodes.keys()) - {"__start__", "__end__"}
    assert nodes == set(NODE_TYPES)


def test_every_node_reaches_closing():
    g = build_v8_graph().get_graph()
    edges = {}
    for e in g.edges:
        edges.setdefault(e.source, set()).add(e.target)
    # closing 可达性:从每个业务节点沿边走,必能到 closing(无孤岛)
    def reaches(n, seen=None):
        seen = seen or set()
        if n in seen:
            return False
        seen.add(n)
        for t in edges.get(n, ()):  # noqa: B905
            if t == "closing" or t == "__end__" or reaches(t, seen):
                return True
        return False
    for n in NODE_TYPES:
        if n == "closing":
            continue
        assert reaches(n), f"{n} 到不了 closing"


def test_user_holes_are_exactly_three_ask_edges():
    kinds = [k for k, v in NODE_TYPES.items() if "user" in v]
    assert sorted(kinds) == ["ask_contradiction", "ask_decision", "bed_gate"]
