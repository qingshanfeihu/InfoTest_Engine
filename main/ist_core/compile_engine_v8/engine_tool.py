"""compile_engine_run(V8):主 agent 一句话触发整条编译闭环的薄工具。

图套图边界(与 V6 同型):qa_agent 图经本工具进程内 invoke V8 图;checkpointer 分库
(runtime/compile_engine_v8_checkpoints.db,thread=v8:<out_name>)——账实分离(INV-7):
checkpoint 只存图游标+interrupt 挂起态+引用,业务真理在批目录 facts.jsonl。
[user] 孔桥接:interrupt payload(bed_gate/ask_decision/ask_contradiction 三类)→
既有 ask_user 面板 → Command(resume) 续跑。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

_MAX_INTERRUPT_ROUNDS = 12


import re as _re


def _panel(questions: list[dict]) -> dict:
    """interrupt 问题组 → ask_user 面板(≤4 题/批,面板 schema:question/header/options)
    → {key: 答案label}。非交互/异常 → {_non_interactive: True}。"""
    from main.ist_core.tools.ask_user import ask_user
    answers: dict = {}
    for i in range(0, len(questions), 4):
        batch = questions[i:i + 4]
        payload = [{k: v for k, v in q.items() if not str(k).startswith("_")} for q in batch]
        try:
            out = ask_user.func(payload)
        except Exception:  # noqa: BLE001
            logger.exception("ask 面板桥接失败")
            return {"_non_interactive": True}
        if isinstance(out, str) and (out.startswith("error") or "非交互" in out):
            return {"_non_interactive": True}
        for q in batch:
            header = str(q.get("header", ""))
            # 非贪婪到「下一键或串尾」:Other 自由输入可含引号,[^"]+ 会早停截断
            m = _re.search(rf'"{_re.escape(header)}"="(.*?)"(?=\. "|\.?\s*$)', out or "")
            if m:
                answers[str(q.get("_key", header))] = m.group(1)
    return answers


def _bridge(payload: dict) -> dict:
    """三类挂起 → 面板问题(形态转换,零语义判断)。"""
    kind = str(payload.get("kind") or "")
    if kind == "bed_gate":
        rep = payload.get("report") or {}
        anchor = rep.get("anchor") or {}
        cu = rep.get("cleanup") or {}
        _KIND_CN = {"segments": "分区配置残留", "sdns_config_files": "SDNS 配置文件残留",
                    "sync_peers": "同步对端配置残留", "build_anchor": "版本不匹配"}
        kinds = [_KIND_CN.get(str(f.get("kind")), str(f.get("kind")))
                 for f in (rep.get("findings") or []) if f.get("kind") != "build_anchor"]
        parts = []
        if kinds:
            parts.append(f"测试床上仍有残留:{'、'.join(kinds)}")
        cl, fl, sk = cu.get("cleaned") or [], cu.get("failed") or [], cu.get("skipped") or []
        if cl or fl or sk:
            seg = []
            if cl:
                seg.append(f"已自动清掉 {len(cl)} 项")
            if fl:
                seg.append(f"{len(fl)} 项清理被设备拒绝")
            if sk:
                seg.append(f"{len(sk)} 项引擎不认识、不敢动")
            parts.append("(" + ",".join(seg) + ")")
        if str(anchor.get("status")) == "match":
            parts.append(f"版本正常(实测 {str(anchor.get('device', ''))[-12:]},与配置同族)")
        else:
            parts.append(f"⚠ 版本不匹配:设备 {anchor.get('device', '?')} vs 配置 {anchor.get('config', '?')}")
        q = ";".join(parts) + "。如何处理?"
        qs = [{"question": q, "header": "床态体检",
               "options": [
                   {"label": "继续", "description": "接受现状照跑——残留不再清理,风险自担;所有结果记录在实测版本上"},
                   {"label": "停止", "description": "先人工清理/换床,之后同参数重跑会从这里续接"}],
               "_key": "decision"}]
        ans = _panel(qs)
        v = str(ans.get("decision") or "")
        return {"decision": "proceed" if "继续" in v else (v or "停止")}
    if kind == "ask_decision":
        qs = list(payload.get("questions") or [])
        for q in qs:
            q["_key"] = str(q.get("_autoid") or q.get("header") or "")
        return _panel(qs)
    if kind == "ask_contradiction":
        return _panel([_contradiction_question(c) for c in (payload.get("cases") or [])])
    return {"_non_interactive": True}


_SHAPE_CN = {"manual_vs_device": "手册与实机不符",
             "expected_vs_observed": "预期结果与上机行为不符",
             "method_vs_implementation": "验证方法与功能实现不符",
             "ordering_vs_persistence": "执行顺序与持久化状态互扰",
             "other": "意图记载有差异"}
_RECEIPT_CN = {"miss": "知识库未命中", "hit_conflicting": "命中但记载互斥",
               "hit_adopted_blocked": "命中但与实机矛盾未采用"}


# 引文截断上限:题面(用户裁决所见)与 briefs 重编注入(worker 所得)必须同一事实面
_QUOTE_CLIP = 300


def _side_cn(s: dict) -> str:
    src = str(s.get("source_ref") or "")
    label = "实机回显" if (src in ("device", "device_context", "causality", "detail_tail",
                                   "framework_traceback") or "last_run" in src) \
        else src.rsplit("/", 1)[-1]
    return f"{label}:『{str(s.get('quote') or '')[:_QUOTE_CLIP]}』"


def _contradiction_question(c: dict) -> dict:
    """问询目标 → 面板一题(§11.11 构件六:题面渲染自 panel,自然中文,零内部术语)。"""
    aid = str(c.get("autoid"))
    kind = str(c.get("kind") or "contra")
    title = str(c.get("title") or "")
    who = f"用例 …{aid[-6:]}" + (f"({title[:24]})" if title else "")
    if kind == "panel":
        p = c.get("panel") or {}
        sides = "；".join(_side_cn(s) for s in (p.get("sides") or [])[:3])
        rc = [str(r.get("outcome") or "") for r in (p.get("retrieval_receipt") or [])]
        searched = "、".join(sorted({_RECEIPT_CN.get(x, x) for x in rc if x}))
        shape_cn = _SHAPE_CN.get(str(p.get("conflict_shape") or ""), _SHAPE_CN["other"])
        q = (f"{who}:{shape_cn}。双方记载——{sides}。"
             + (f"已检索:{searched}。" if searched else "")
             + f"引擎的理解:{str(p.get('hypothesis') or '')[:300]}。"
             + str(p.get("ask") or "这样理解对吗?")
             + ("(该用例重编轮次已用尽,你的答案同时决定是否继续)" if c.get("cap_reached") else "")
             + " 如两者都不对,选 Other 直接写出正确的意图/预期。")
        return {"question": q, "header": f"确认{aid[-4:]}",
                "options": [
                    {"label": "确认,按此继续", "description": "按引擎的理解重编该用例"},
                    {"label": "确认产品缺陷", "description": "该差异是产品问题——记入缺陷候选单,该用例以缺陷结案"}],
                "_key": aid}
    if kind == "cap":
        q = (f"{who} 已重编 {c.get('rounds')} 轮仍未通过"
             + (f"(最近的修法方向:{str(c.get('evidence') or '')[:160]})" if c.get("evidence") else "")
             + ",引擎多轮未收敛。如何处理?")
        return {"question": q, "header": f"轮次{aid[-4:]}",
                "options": [
                    {"label": "继续,再修 2 轮", "description": "授权追加重编轮次"},
                    {"label": "挂起该案", "description": "先放一放,跑完其他用例;重跑同参数时会再次询问"},
                    {"label": "停止该案", "description": "以未通过如实报告,不再消耗轮次"}],
                "_key": aid}
    if kind == "env":
        q = (f"{who} 的失败被判为环境阻塞"
             + (f"(依据:{str(c.get('evidence') or '')[:160]})" if c.get("evidence") else "")
             + "。确认是环境问题吗?")
        return {"question": q, "header": f"环境{aid[-4:]}",
                "options": [
                    {"label": "确认环境问题,停止该案", "description": "以环境阻塞如实报告该用例"},
                    {"label": "不认可,隔离复跑", "description": "单独再跑一次验证这个判断"}],
                "_key": aid}
    if kind == "suspended":
        q = f"{who} 上批被挂起。本批如何处理?"
        return {"question": q, "header": f"挂起{aid[-4:]}",
                "options": [
                    {"label": "恢复处理", "description": "回到正常流程继续修"},
                    {"label": "保持挂起", "description": "本批继续不动它"}],
                "_key": aid}
    q = (f"{who} 单独验证通过、整卷复验第 {c.get('contradictions')} 次失败"
         f"(跨案持久态互扰嫌疑"
         + (f";{str(c.get('diagnosis') or '')[:120]}" if c.get("diagnosis") else "")
         + (f";既往选择:{c.get('prior_choices')}" if c.get("prior_choices") else "")
         + "),如何处置?")
    return {"question": q, "header": f"矛盾{aid[-4:]}",
            "options": [
                {"label": "重排复验", "description": "重排卷序后再终验一轮(互扰案排卷尾)"},
                {"label": "如实降级", "description": "该案不入交付卷,以未通过如实报告"}],
            "_key": aid}


@tool(parse_docstring=True)
def compile_engine_run(mindmap_path: str, product_version: str,
                       out_name: str = "", max_rounds: int = 3) -> str:
    """Run the V8 compile engine: mindmap → bed check → per-case authoring → ask on underdetermined → merge → on-device run → reconcile → attribution → targeted recompile → final delivery verify → writeback → report.

    Facts are append-only (workspace/outputs/<batch>/facts.jsonl); every on-device verdict is
    reconciled with an explicit outcome — swallowed verdicts are structurally impossible. Three
    user-decision edges may pause the run (bed anchor mismatch / underdetermined claims /
    delivery contradiction); answers resume from checkpoint. Re-calling with the same
    arguments resumes an interrupted run without re-burning device rounds.

    Args:
        mindmap_path: mindmap txt path (e.g. workspace/inputs/automatic_case/x.txt).
        product_version: product version (e.g. 10.5) — decides which manual workers consult.
        out_name: batch name (deliverables at workspace/outputs/<out_name>/); defaults to
            the mindmap filename.
        max_rounds: per-case recompile cap (default 3).

    Returns:
        Result summary; full report at workspace/outputs/<out_name>/delivery_report.md,
        machine-readable at engine_report.json, facts at facts.jsonl.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command
    from main.ist_core.compile_engine_v8.graph import build_v8_graph
    from main.ist_core.compile_engine_v8 import _shared as sh

    name = (out_name or Path(mindmap_path).stem).strip()
    root = sh.project_root()
    db = root / "runtime" / "compile_engine_v8_checkpoints.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    try:
        with SqliteSaver.from_conn_string(str(db)) as saver:
            g = build_v8_graph(checkpointer=saver)
            cfg = {"configurable": {"thread_id": f"v8:{name}"}, "recursion_limit": 200}
            state = {"mindmap_path": mindmap_path, "product_version": product_version,
                     "out_name": name, "max_rounds": int(max_rounds or 3)}
            res = g.invoke(state, cfg)
            rounds = 0
            while isinstance(res, dict) and "__interrupt__" in res and rounds < _MAX_INTERRUPT_ROUNDS:
                payload = res["__interrupt__"][0].value
                res = g.invoke(Command(resume=_bridge(payload)), cfg)
                rounds += 1
    except Exception as exc:  # noqa: BLE001
        logger.exception("V8 引擎异常")
        return (f"error: compile engine aborted — {type(exc).__name__}: {exc}\n"
                f"Progress is saved (checkpoint + facts); re-call with the same arguments to resume.")

    rp = sh.outputs_root() / name / "engine_report.json"
    if not rp.is_file():
        return f"error: engine finished without a report (state keys: {sorted((res or {}).keys())[:12]})"
    rep = json.loads(rp.read_text(encoding="utf-8"))
    t = rep.get("totals", {})
    lines = [
        f"compile engine (v8) done: {rep.get('outcome')}",
        f"cases {t.get('cases', 0)}: deliverable {t.get('deliverable', 0)}"
        + (f", labels {json.dumps({k: v for k, v in t.items() if k not in ('cases', 'deliverable') and v}, ensure_ascii=False)}"
           if any(v for k, v in t.items() if k not in ("cases", "deliverable")) else ""),
        f"full report (on disk): workspace/outputs/{name}/delivery_report.md",
        f"facts ledger: {rep.get('refs', {}).get('facts')}",
    ]
    return "\n".join(lines)
