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
import os
import re
from pathlib import Path

from langchain_core.tools import tool

from main.knowledge_paths import user_output_dir

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
        结果摘要(完整报告落盘 delivery_report.md);机读全量在 workspace/outputs/<out_name>/engine_report.json。
    """
    root = Path(__file__).resolve().parents[4]
    name = (out_name or "").strip() or Path(mindmap_path).stem
    db = root / "runtime" / "compile_engine_checkpoints.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    # 设置环境变量，让工具函数知道 out_name
    os.environ["IST_COMPILE_OUT_NAME"] = name

    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from main.ist_core.compile_engine.graph import build_compile_engine_graph

    # 引擎运行元信息 → .events.jsonl(TUI 引擎卡建卡信号;失败静默)
    try:
        from main.ist_core.skills.loader import _fork_emit_event
        _fork_emit_event({"event": "run_meta", "run": name, "kind": "engine",
                          "mindmap": str(mindmap_path),
                          "ledger": str((user_output_dir() / name / "engine_ledger.json")
                                         .relative_to(root))})
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
            return (f"error: 编译引擎异常中断——{type(exc).__name__}: {exc}\n"
                    f"进度已保存(checkpoint+台账+已产出卷面),修复后同参数重调本工具续跑。")

    # 报告摘要(机读全量在 engine_report.json)
    rp = user_output_dir() / name / "engine_report.json"
    if not rp.is_file():
        return f"error: 引擎结束但无报告(state={json.dumps(result, ensure_ascii=False, default=str)[:300]})"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    return _summarize_report(rep, str(rp.relative_to(root)), name)


def _summarize_report(rep: dict, report_ref: str, name: str) -> str:
    t = rep.get("totals", {})
    lines = [
        f"编译引擎完成: {rep.get('outcome')}(轮次 {rep.get('rounds')})",
        f"用例 {t.get('cases', 0)} 个:上机通过 {t.get('passed', 0)}"
        f",待用户拍板 {t.get('awaiting_user', 0)}"
        f",阻塞/缺陷标注 {t.get('failed_terminal', 0)}"
        f",升级人工 {t.get('escalated', 0)}",
        f"完整报告(已落盘): {rep.get('refs', {}).get('delivery_md') or '—'}",
        f"机读报告: {report_ref}",
    ]
    # 非 pass 用例逐条附证据:main 复述曾凭上下文记忆重构设备回显(伪造配置会话、
    # 把「设备不支持」说成「执行成功」)——返回里给真原文摘录,复述才有据可引。
    evid = []
    for aid, cc in sorted((rep.get("cases") or {}).items()):
        st = str(cc.get("state") or "")
        if st not in ("escalated", "failed_terminal"):
            continue
        reason = cc.get("escalation_reason") or cc.get("detail") or st
        tag = "升级人工" if st == "escalated" else "标注终态"
        line = f"- [{tag}] …{aid[-6:]}: {reason}"
        ev = cc.get("fail_evidence") or []
        last = ev[-1] if ev and isinstance(ev[-1], dict) else {}
        ctx = str(last.get("device_context") or "").strip()
        if ctx:
            line += f" | 末轮设备回显: {ctx[:200]}"
        evid.append(line)
    if evid:
        lines.append("非 pass 用例证据(复述设备行为只引用下面的原文摘录、"
                     "engine_report 的 fail_evidence 或 last_run.json 的"
                     " device_context,不要凭记忆重构回显):")
        lines.extend(evid)
        lines.append(f"完整逐轮回显: {report_ref} 各 case 的 fail_evidence;"
                     f"整卷原文 workspace/outputs/{name}/last_run.json")
    if rep.get("error"):
        lines.append(f"中止原因: {rep['error']}")
    return "\n".join(lines)
