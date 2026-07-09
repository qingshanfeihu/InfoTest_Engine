"""compile_engine_run:V6 引擎图的薄工具(main agent 一句话触发整条编译闭环)。

图套图,薄工具衔接(docs/PLAN 数据结构学):qa_agent 图经本工具进程内 invoke
引擎 StateGraph;工具边界隔离两图的 checkpointer/中间件/递归预算。
- checkpointer 分库:runtime/compile_engine_checkpoints.db(同步 SqliteSaver),
  thread_id=engine:<out_name> —— 进程死了重调本工具即续跑(官方 persistence 模式)。
- [user] 孔桥接:引擎图 `interrupt({kind: ask_decision, questions})` 挂起 →
  本工具把 questions 转给既有 ask_user 线程面板 → `Command(resume=answers)` 续跑
  (官方 HIL 模式;非交互模式 answers={_non_interactive: True},引擎标 awaiting_user)。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MAX_INTERRUPT_ROUNDS = 8   # ask 分批上限(每批 ≤4 题;防面板异常导致的无限挂起循环)


def _bridge_ask(questions: list[dict]) -> dict:
    """interrupt payload → ask_user 面板 → {autoid: 答案label} 。"""
    from main.ist_core.tools.ask_user import ask_user
    answers: dict = {}
    for i in range(0, len(questions), 4):     # ask_user 硬限 ≤4 题/次
        batch = questions[i:i + 4]
        payload = [{k: v for k, v in q.items() if not str(k).startswith("_")} for q in batch]
        out = ask_user.func(payload)
        if isinstance(out, str) and (out.startswith("error") or "非交互" in out):
            answers["_non_interactive"] = True
            return answers
        for q in batch:
            header = str(q.get("header", ""))
            m = re.search(rf'"{re.escape(header)}"="([^"]+)"', out or "")
            if m:
                answers[str(q.get("_autoid", ""))] = m.group(1)
    return answers


@tool(parse_docstring=True)
def compile_engine_run(mindmap_path: str, product_version: str,
                       out_name: str = "", max_rounds: int = 3) -> str:
    """Run the V6 compile engine: mindmap → per-case authoring → ask the user on underdetermined → merge → on-device run → attribution → targeted recompile → iterate to fixpoint → writeback → delivery report.

    The whole loop is driven by a deterministic state machine in one call (underdetermined
    cases pop a user panel mid-run); after an interruption, re-calling this tool with the
    same out_name resumes from checkpoint without re-burning device rounds.

    Args:
        mindmap_path: mindmap txt path (e.g. workspace/inputs/automatic_case/dongkl.txt).
        product_version: product version (e.g. 10.5) — decides which manual workers consult;
            if absent, ask the user first.
        out_name: batch name (deliverables at workspace/outputs/<out_name>/); defaults to
            the mindmap filename.
        max_rounds: on-device/recompile loop cap (default 3; on hitting the cap the
            remainder is reported honestly).

    Returns:
        Result summary (the full report lands in delivery_report.md); machine-readable
        entirety in workspace/outputs/<out_name>/engine_report.json.
    """
    root = Path(__file__).resolve().parents[4]
    name = (out_name or "").strip() or Path(mindmap_path).stem
    db = root / "runtime" / "compile_engine_checkpoints.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from main.ist_core.compile_engine.graph import build_compile_engine_graph

    # 引擎运行元信息 → .events.jsonl(TUI 引擎卡建卡信号;失败静默)
    try:
        from main.ist_core.skills.loader import _fork_emit_event
        _fork_emit_event({"event": "run_meta", "run": name, "kind": "engine",
                          "mindmap": str(mindmap_path),
                          "ledger": f"workspace/outputs/{name}/engine_ledger.json"})
    except Exception:  # noqa: BLE001
        pass

    # fork token 计量:execute_fork_skill 在 fork invoke 上显式挂 _ForkUsageTally,
    # 不依赖 callback 传播——引擎/线程池路径天然覆盖,无需开关。
    return _run_engine_graph(db, name, mindmap_path, product_version, max_rounds, root)


def _run_engine_graph(db, name, mindmap_path, product_version, max_rounds, root) -> str:
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from main.ist_core.compile_engine.graph import build_compile_engine_graph

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_compile_engine_graph(checkpointer=saver)
        config = {"configurable": {"thread_id": f"engine:{name}"},
                  "recursion_limit": 120}
        init = {"mindmap_path": str(mindmap_path),
                "product_version": str(product_version),
                "out_name": name, "max_rounds": int(max_rounds)}

        # resume 语义:同 thread 有挂起的 interrupt → 直接从挂起点继续;否则新跑。
        try:
            snap = graph.get_state(config)
            pending_interrupt = bool(getattr(snap, "next", None)) if snap else False
            result = graph.invoke(init if not pending_interrupt else None, config)

            for _ in range(_MAX_INTERRUPT_ROUNDS):
                intr = (result or {}).get("__interrupt__")
                if not intr:
                    break
                payload = getattr(intr[0], "value", None) or {}
                if not (isinstance(payload, dict) and payload.get("kind") == "ask_decision"):
                    answers = {"_non_interactive": True}   # 未知挂起类型:保守不猜
                else:
                    answers = _bridge_ask(list(payload.get("questions") or []))
                result = graph.invoke(Command(resume=answers), config)
        except Exception as exc:  # noqa: BLE001 — 引擎异常必须可读返回:进度在
            # checkpoint+ledger+盘上产物,修复后同参数重调即续跑,已完成的不重烧。
            logger.exception("compile_engine 异常")
            return (f"error: compile engine aborted — {type(exc).__name__}: {exc}\n"
                    f"Progress is saved (checkpoint + ledger + produced volumes); after fixing, "
                    f"re-call this tool with the same arguments to resume.")

    # 报告摘要(机读全量在 engine_report.json)
    rp = root / "workspace" / "outputs" / name / "engine_report.json"
    if not rp.is_file():
        return f"error: engine finished without a report (state={json.dumps(result, ensure_ascii=False, default=str)[:300]})"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    return _summarize_report(rep, str(rp.relative_to(root)), name)


def _summarize_report(rep: dict, report_ref: str, name: str) -> str:
    t = rep.get("totals", {})
    lines = [
        f"compile engine done: {rep.get('outcome')} (rounds {rep.get('rounds')})",
        f"cases {t.get('cases', 0)}: on-device pass {t.get('passed', 0)}"
        f", awaiting user {t.get('awaiting_user', 0)}"
        f", blocked/defect-annotated {t.get('failed_terminal', 0)}"
        f", escalated to human {t.get('escalated', 0)}",
        f"full report (on disk): {rep.get('refs', {}).get('delivery_md') or '—'}",
        f"machine-readable report: {report_ref}",
    ]
    # 非 pass 用例逐条附证据:main 复述曾凭上下文记忆重构设备回显(伪造配置会话、
    # 把「设备不支持」说成「执行成功」)——返回里给真原文摘录,复述才有据可引。
    evid = []
    for aid, cc in sorted((rep.get("cases") or {}).items()):
        st = str(cc.get("state") or "")
        if st not in ("escalated", "failed_terminal"):
            continue
        reason = cc.get("escalation_reason") or cc.get("detail") or st
        tag = "escalated to human" if st == "escalated" else "terminal-annotated"
        line = f"- [{tag}] …{aid[-6:]}: {reason}"
        ev = cc.get("fail_evidence") or []
        last = ev[-1] if ev and isinstance(ev[-1], dict) else {}
        ctx = str(last.get("device_context") or "").strip()
        if ctx:
            line += f" | last-round device echo: {ctx[:200]}"
        evid.append(line)
    if evid:
        lines.append("Evidence for non-pass cases (when restating device behavior quote only "
                     "the excerpts below, engine_report fail_evidence, or last_run.json "
                     "device_context — never reconstruct echoes from memory):")
        lines.extend(evid)
        lines.append(f"full per-round echoes: fail_evidence per case in {report_ref}; "
                     f"whole-volume raw text at workspace/outputs/{name}/last_run.json")
    if rep.get("error"):
        lines.append(f"abort reason: {rep['error']}")
    return "\n".join(lines)
