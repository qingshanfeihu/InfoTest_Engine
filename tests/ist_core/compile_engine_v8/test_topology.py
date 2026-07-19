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


# ── ⑤A-④(P2-3 拓扑门第三方补齐,team4_skill_audit.md:91):此前门只断言 图↔NODE_TYPES 两方,
# SKILL.md frontmatter 的 engine.phases/graph 无人看守——图改动时 SKILL 声明会静默过期。补 SKILL
# 一方,凑齐 CLAUDE.md 承诺的「图↔SKILL↔NODE_TYPES 三方一致」。────────────────────────────────


def _compile_skill_frontmatter():
    from pathlib import Path
    from main.ist_core.skills.loader import read_skill_frontmatter
    p = Path(__file__).resolve().parents[3] / "main/ist_core/skills/ist-compile-engine/SKILL.md"
    return read_skill_frontmatter(p), p


def test_skill_phases_match_node_types():
    """P2-3(第三方):SKILL.md frontmatter `engine.phases` YAML 声明 == list(NODE_TYPES)(内容+序)。
    图↔NODE_TYPES 已有两测;缺这条 SKILL 一方,图节点增删/改序时 SKILL.phases 静默过期无人拦。"""
    fm, p = _compile_skill_frontmatter()
    assert fm is not None, f"读不到 SKILL.md frontmatter:{p}"
    phases = (fm.get("engine") or {}).get("phases")
    assert phases == list(NODE_TYPES), \
        f"SKILL.md engine.phases 与 NODE_TYPES 漂移:\n  SKILL={phases}\n  NODE ={list(NODE_TYPES)}"


def test_skill_engine_graph_pointer_importable():
    """P2-3:SKILL.md `engine.graph` 指针(module:attr)可导入——Studio/langgraph.json 消费面不腐,
    指针指向的 graph 对象必须真实存在(防 SKILL 声明与代码脱节)。"""
    import importlib
    fm, _ = _compile_skill_frontmatter()
    ptr = str((fm.get("engine") or {}).get("graph") or "")
    assert ":" in ptr, f"engine.graph 指针格式应为 module:attr,实为 {ptr!r}"
    mod_name, attr = ptr.split(":", 1)
    mod = importlib.import_module(mod_name)
    assert hasattr(mod, attr), f"engine.graph 指针 {ptr} 的 attr `{attr}` 不可导入"
