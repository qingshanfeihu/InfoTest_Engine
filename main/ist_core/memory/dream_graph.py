"""LangGraph wrapper for the memory consolidation (Dream) task.

注册到 langgraph.json 后，可以用 `client.crons.create(assistant_id="memory_dream", schedule="0 3 * * *", ...)` 调度。

不引入新功能——直接调 main.ist_core.memory.dream.run_dream_with_gates。
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)


class DreamState(TypedDict, total=False):
    messages: list
    report: dict
    reason: str


def _run(state: DreamState) -> DreamState:
    """单节点：跑五道闸 + DreamTask；返回报告/拒绝原因到 state。"""
    try:
        from main.ist_core.memory.dream import run_dream_with_gates
        report, reason = run_dream_with_gates()
    except Exception as exc:
        logger.exception("dream graph 运行异常: %s", exc)
        return {"reason": f"crashed: {exc}", "report": {}}

    if report is None:
        return {"reason": reason, "report": {}}
    return {
        "reason": reason,
        "report": {
            "duration_s": report.duration_s,
            "orient_count": report.orient_count,
            "gather_bytes": report.gather_bytes,
            "decisions": list(report.decisions),
            "pruned_count": report.pruned_count,
        },
    }


def build_dream_graph():
    g = StateGraph(DreamState)
    g.add_node("run_dream", _run)
    g.add_edge(START, "run_dream")
    g.add_edge("run_dream", END)
    return g.compile()


graph = build_dream_graph()
