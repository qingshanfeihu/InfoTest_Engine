"""引擎图定义(声明式 DSL 核心):节点表 + 条件边表。

图即文档:`graph.get_graph()` 可渲染(langgraph dev Studio);拓扑门断言
节点集与 state.NODE_TYPES、SKILL.md phases 三方一致。条件边全部是
**state 机读计数的纯函数**——LLM 永远不当胶水。

条件边表(与 docs/PLAN 1.4 一致):
    prep           ok→worker_fanout | error→report
    worker_fanout  有欠定→ask_decision | 有产出→merge | 全躺→report
    ask_decision   拿到决策(pending>0)→worker_fanout | 有产出→merge | 全挂→report
    merge          ok→run_digest | error/nothing→report
    run_digest     有fail→attribute | 全pass·subset→merge(终验) | 全pass·full→writeback
                   | device_busy/error→report
    attribute      重派(pending>0 且 round<max)→worker_fanout
                   | 仅transient待复跑→merge | 全终态→writeback | 封顶→writeback
    writeback      →report ;  report →END
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from main.ist_core.compile_engine.state import CompileEngineState, NODE_TYPES
from main.ist_core.compile_engine import nodes as N


# ---- 条件边(纯函数,只读 state 计数) ----

def _after_prep(s: dict) -> str:
    return "report" if s.get("phase_status") == "error" else "worker_fanout"


def _after_fanout(s: dict) -> str:
    if s.get("phase_status") == "error":
        return "report"
    if s.get("n_pending_decision", 0) > 0:
        return "ask_decision"
    if s.get("n_produced", 0) > 0 or s.get("n_failed_active", 0) > 0:
        return "merge"
    return "report"


def _after_ask(s: dict) -> str:
    if s.get("phase_status") == "error":
        return "report"
    if s.get("n_pending_compile", 0) > 0:
        return "worker_fanout"
    if s.get("n_produced", 0) > 0:
        return "merge"
    return "report"


def _after_merge(s: dict) -> str:
    return "run_digest" if s.get("phase_status") == "ok" else "report"


def _after_run(s: dict) -> str:
    if s.get("phase_status") in ("device_busy", "error"):
        return "report"
    if s.get("n_failed_active", 0) > 0:
        return "attribute"
    if s.get("run_scope") == "subset":
        return "merge"          # 修复轮全过 → 终验整卷
    return "writeback"          # 整卷全过 → 不动点达成


def _after_attribute(s: dict) -> str:
    max_rounds = int(s.get("max_rounds") or 3)
    if s.get("n_pending_compile", 0) > 0 and int(s.get("round") or 0) < max_rounds:
        return "worker_fanout"   # 定向重编(派发集⊆fail 由 ledger 审计强制)
    if s.get("n_failed_active", 0) > 0 and int(s.get("round") or 0) < max_rounds:
        return "merge"           # 仅 transient:不重编直接复跑
    return "writeback"           # 全终态/封顶 → 写回已 pass 的,如实报告其余


def build_compile_engine_graph(checkpointer=None):
    """构建引擎图。checkpointer 传 SqliteSaver 得断点续跑;Studio 用 None。"""
    g = StateGraph(CompileEngineState)
    for name in NODE_TYPES:
        g.add_node(name, getattr(N, name))
    g.add_edge(START, "prep")
    g.add_conditional_edges("prep", _after_prep, ["worker_fanout", "report"])
    g.add_conditional_edges("worker_fanout", _after_fanout,
                            ["ask_decision", "merge", "report"])
    g.add_conditional_edges("ask_decision", _after_ask,
                            ["worker_fanout", "merge", "report"])
    g.add_conditional_edges("merge", _after_merge, ["run_digest", "report"])
    g.add_conditional_edges("run_digest", _after_run,
                            ["attribute", "merge", "writeback", "report"])
    g.add_conditional_edges("attribute", _after_attribute,
                            ["worker_fanout", "merge", "writeback"])
    g.add_edge("writeback", "report")
    g.add_edge("report", END)
    return g.compile(checkpointer=checkpointer)


# Studio/可视化用(无 checkpointer,dev server 自管持久化;langgraph.json 指向这里)
graph = build_compile_engine_graph()
