"""compile_engine_run:V6 引擎图的薄工具(main agent 一句话触发整条编译闭环)。

图套图,薄工具衔接(docs/PLAN 数据结构学):qa_agent 图经本工具进程内 invoke
引擎 StateGraph;工具边界隔离两图的 checkpointer/中间件/递归预算。
- checkpointer 分库:runtime/compile_engine_checkpoints.db(同步 SqliteSaver),
  thread_id=engine:<out_name> —— 进程死了重调本工具即续跑(官方 persistence 模式)。
- [user] 孔桥接:引擎图 `interrupt({kind: ask_decision, questions})` 挂起 →
  本工具把 questions 转给既有 ask_user 线程面板 → `Command(resume=answers)` 续跑
  (官方 HIL 模式;非交互模式 answers={_non_interactive: True},引擎标 awaiting_user)。
`IST_COMPILE_ENGINE=0` → 返回 engine_disabled(SKILL 兜底段引导走 v5 编排)。
"""

from __future__ import annotations

import json
import logging
import os
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
    """跑 V6 编译引擎:脑图→逐case编写→欠定问用户→合并→上机→归因→定向重编→循环到
    不动点→写回→交付报告。整条闭环由确定性状态机驱动,一次调用完成(中途欠定会弹
    面板问用户);被打断后重调本工具(同 out_name)自动从断点续跑,不重复烧设备轮。

    Args:
        mindmap_path: 脑图 txt 路径(如 workspace/inputs/automatic_case/dongkl.txt)。
        product_version: 产品版本(如 10.5)——worker 查哪个手册的依据,没有就先问用户。
        out_name: 批名(产物目录 workspace/outputs/<out_name>/);省略取脑图文件名。
        max_rounds: 上机-重编循环上限(默认 3;到顶如实报告剩余)。

    Returns:
        交付报告人话摘要;机读全量在 workspace/outputs/<out_name>/engine_report.json。
    """
    if (os.environ.get("IST_COMPILE_ENGINE") or "1").strip().lower() in ("0", "false", "no"):
        return ("engine_disabled: V6 引擎已关闭(IST_COMPILE_ENGINE=0)——"
                "按 ist-compile skill 的 v5 编排流程执行。")

    root = Path(__file__).resolve().parents[4]
    name = (out_name or "").strip() or Path(mindmap_path).stem
    db = root / "runtime" / "compile_engine_checkpoints.db"
    db.parent.mkdir(parents=True, exist_ok=True)

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

    # 报告摘要(机读全量在 engine_report.json)
    rp = root / "workspace" / "outputs" / name / "engine_report.json"
    if not rp.is_file():
        return f"error: 引擎结束但无报告(state={json.dumps(result, ensure_ascii=False, default=str)[:300]})"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    t = rep.get("totals", {})
    lines = [
        f"编译引擎完成: {rep.get('outcome')}(轮次 {rep.get('rounds')})",
        f"用例 {t.get('cases', 0)} 个:上机通过 {t.get('passed', 0)}"
        f",待用户拍板 {t.get('awaiting_user', 0)}"
        f",阻塞/缺陷标注 {t.get('failed_terminal', 0)}"
        f",升级人工 {t.get('escalated', 0)}",
        f"机读报告: {rp.relative_to(root)}",
    ]
    if rep.get("error"):
        lines.append(f"中止原因: {rep['error']}")
    return "\n".join(lines)
