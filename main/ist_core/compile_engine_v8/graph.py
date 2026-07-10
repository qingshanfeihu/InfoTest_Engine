"""V8 引擎图:节点表+条件边表(图即文档;拓扑门三方一致:本图 ↔ NODE_TYPES ↔ SKILL.md)。

条件边全部是 state 计数缓存的纯函数(缓存由各节点出口按视图重算;真理在事实流,INV-7)。

    prep            ok→bed_gate | error→closing
    bed_gate        ok→author | bed_blocked→closing
    author          欠定>0→ask_decision | 有待验卷→merge | 全躺→closing
    ask_decision    有待编(决策已答)→author | 有待验→merge | 全躺→closing
    merge           ok→run | error/nothing→closing
    run             ok→reconcile | busy/error→closing
    reconcile       矛盾≥2待问→ask_contradiction | 有 fail→attribute
                    | 全 deliverable→closing | 有待终验→merge
    attribute       reflow 待编→author | rerun/transient→merge
                    | 矛盾待问→ask_contradiction | 全终局→closing
    ask_contradiction 依用户答案:重排复验→merge | 其余→closing
    closing         →END
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8.state import V8State, NODE_TYPES


def _after_prep(s: dict) -> str:
    return "closing" if s.get("phase_status") == "error" else "bed_gate"


def _after_bed(s: dict) -> str:
    return "author" if s.get("phase_status") == "ok" else "closing"


def _after_author(s: dict) -> str:
    if s.get("n_awaiting_user", 0) > 0:
        return "ask_decision"
    if s.get("n_authored", 0) > 0 or s.get("n_subset_verified", 0) > 0:
        return "merge"
    return "closing"


def _after_ask_decision(s: dict) -> str:
    if s.get("n_pending", 0) > 0:
        return "author"
    if s.get("n_authored", 0) > 0:
        return "merge"
    return "closing"


def _after_merge(s: dict) -> str:
    return "run" if s.get("phase_status") == "ok" else "closing"


def _after_run(s: dict) -> str:
    return "reconcile" if s.get("phase_status") == "ok" else "closing"


def _after_reconcile(s: dict) -> str:
    if s.get("n_ask_contradiction", 0) > 0:
        return "ask_contradiction"
    if s.get("n_failed", 0) > 0:
        return "attribute"
    live = s.get("n_authored", 0) + s.get("n_subset_verified", 0)
    if live > 0:
        return "merge"          # 待终验(子集过)或新卷待验
    return "closing"


def _after_attribute(s: dict) -> str:
    if s.get("n_ask_contradiction", 0) > 0:
        return "ask_contradiction"
    if s.get("n_failed", 0) > 0 or s.get("n_pending", 0) > 0:
        return "author"         # reflow 定向重编(author 内部按处置/封顶筛)
    if s.get("n_authored", 0) + s.get("n_subset_verified", 0) > 0:
        return "merge"          # rerun_isolated/transient:不重编直接复跑
    return "closing"


def _after_ask_contradiction(s: dict) -> str:
    if s.get("n_ask_contradiction", 0) > 0:
        return "closing"        # 未获答案(非交互/面板失败)→ 如实收口,禁 ask↔attribute 空转
    if s.get("n_failed", 0) > 0:
        return "attribute"      # 计数<2 的矛盾案/翻转案继续归因定向回环(验收发现#7)
    if s.get("n_authored", 0) + s.get("n_subset_verified", 0) > 0:
        return "merge"
    return "closing"


def build_v8_graph(checkpointer=None):
    g = StateGraph(V8State)
    for name in NODE_TYPES:
        g.add_node(name, getattr(N, name))
    g.add_edge(START, "prep")
    g.add_conditional_edges("prep", _after_prep, ["bed_gate", "closing"])
    g.add_conditional_edges("bed_gate", _after_bed, ["author", "closing"])
    g.add_conditional_edges("author", _after_author, ["ask_decision", "merge", "closing"])
    g.add_conditional_edges("ask_decision", _after_ask_decision, ["author", "merge", "closing"])
    g.add_conditional_edges("merge", _after_merge, ["run", "closing"])
    g.add_conditional_edges("run", _after_run, ["reconcile", "closing"])
    g.add_conditional_edges("reconcile", _after_reconcile,
                            ["ask_contradiction", "attribute", "merge", "closing"])
    g.add_conditional_edges("attribute", _after_attribute,
                            ["ask_contradiction", "author", "merge", "closing"])
    g.add_conditional_edges("ask_contradiction", _after_ask_contradiction,
                            ["attribute", "merge", "closing"])
    g.add_edge("closing", END)
    return g.compile(checkpointer=checkpointer)


graph = build_v8_graph()
