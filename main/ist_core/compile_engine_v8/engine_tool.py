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
        _CHAN_CN = {"segments": "分区配置", "sdns_config_files": "SDNS 配置文件",
                    "sync_peers": "同步对端配置", "interface_addresses": "接口地址"}
        kinds, failed_probes, stuck = [], [], []
        for f in (rep.get("findings") or []):
            k = str(f.get("kind"))
            if k == "build_anchor":
                continue
            cn = _CHAN_CN.get(k, k)
            if f.get("probe_failed"):
                failed_probes.append(cn)
            elif f.get("ledger_stuck"):
                stuck.append(cn)
            else:
                kinds.append(cn + "残留")
        parts = []
        if kinds:
            parts.append(f"测试床上仍有残留:{'、'.join(kinds)}")
        if stuck:
            parts.append(f"上批留下的{'、'.join(stuck)}改动,自动恢复尝试未成"
                         f"(命令被拒或生成失败)——需要人工恢复后继续")
        if failed_probes:
            parts.append(f"{'、'.join(failed_probes)}通道探测未完成(探针命令被设备拒绝,"
                         f"该通道床态未知——「继续」为床态不明自担风险,或「停止」后重跑重探/人工核查)")
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
        qs = [_contradiction_question(c) for c in (payload.get("cases") or [])]
        raw = _panel(qs)
        if raw.get("_non_interactive"):
            return raw
        # label→token 引擎同源精确映射(W3:label 是引擎自己产的,不猜;
        # Other 自由输入不在表 → token 空,节点侧语义兜底)
        out: dict = {}
        for q in qs:
            k = str(q.get("_key") or "")
            if k in raw:
                label = raw[k]
                out[k] = {"answer": label,
                          "token": (q.get("_tokens") or {}).get(label, "")}
        return out
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
    """问询目标 → 面板一题(§11.11 构件六:题面渲染自 panel,自然中文,零内部术语)。
    片4:题面携「已试修法」清单(队列空证明的用户可见半——问到你不是因为没试,
    是引擎侧导出修法已试尽/修法在引擎权限外)。"""
    aid = str(c.get("autoid"))
    kind = str(c.get("kind") or "contra")
    title = str(c.get("title") or "")
    who = f"用例 …{aid[-6:]}" + (f"({title[:24]})" if title else "")
    tried = [str(x) for x in (c.get("tried") or []) if x]
    if tried and kind in ("cap", "env", "bed", "contra"):
        who += f"[引擎已试:{ '、'.join(tried[:3]) }]"
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
                "_tokens": {"确认,按此继续": "confirm", "确认产品缺陷": "defect"},
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
                "_tokens": {"继续,再修 2 轮": "continue", "挂起该案": "suspend",
                            "停止该案": "stop"},
                "_key": aid}
    if kind == "env":
        q = (f"{who} 的失败被判为环境阻塞"
             + (f"(依据:{str(c.get('evidence') or '')[:160]})" if c.get("evidence") else "")
             + "。确认是环境问题吗?")
        return {"question": q, "header": f"环境{aid[-4:]}",
                "options": [
                    {"label": "确认环境问题,停止该案", "description": "以环境阻塞如实报告该用例"},
                    {"label": "不认可,隔离复跑", "description": "单独再跑一次验证这个判断"}],
                "_tokens": {"确认环境问题,停止该案": "stop", "不认可,隔离复跑": "retry"},
                "_key": aid}
    if kind == "bed":
        if c.get("self_polluter"):
            # G2((40) 分类学):自污染者——卷面自身含无恢复步的网络层写,复跑=
            # 再污染(run12 六次拆床实证),「复跑」出口对此类是毒药,不提供
            tau = "；".join(str(t) for t in (c.get("suggested_tau") or [])[:3])
            q = (f"{who} 的卷面自身含网络层配置写而**无案尾恢复步**"
                 + (f"(缺恢复:{('、'.join(str(x) for x in c.get('missing_tau') or [])[:60])})"
                    if c.get("missing_tau") else "")
                 + "——每次执行都会重新污染共享床(复跑只会再拆一次,不是出路)。如何处置?")
            return {"question": q, "header": f"缺清理{aid[-4:]}",
                    "options": [
                        {"label": "重编补自清", "description":
                            f"重新编写并在断言后追加恢复步(建议:{tau or '逆序 no 回放'})——推荐"},
                        {"label": "挂起到下批", "description": "本批不动它,下批处理"},
                        {"label": "如实降级", "description": "该案不入交付卷,以未通过如实报告"}],
                    "_tokens": {"重编补自清": "reflow_tau", "挂起到下批": "suspend",
                                "如实降级": "downgrade"},
                    "_key": aid}
        # 文案与证据强度匹配(run14 实弹修:交换子配对是必要条件推断,假阳 20-26%
        # 理论自认;设备失联/命令失败呈同样症状——「唯一根治」类断言语气曾在
        # 11 案设备失联批上全部乱断言)
        _grp = [str(a)[-6:] for a in (c.get("group_aids") or []) if str(a) != str(aid)]
        _grp_note = (f"本题代表 {len(_grp) + 1} 个同因用例(另含尾号 {'、'.join(_grp[:6])})"
                     f",你的答案将应用到全部。" if _grp else "")
        q = (f"{who} 被批级配对判为**疑似测试床状态污染**"
             + (f"(依据:{str(c.get('evidence') or '')[:200]})" if c.get("evidence") else "")
             + "。注意:此判定是必要条件推断(非确证)——若设备/环境本身有异常,"
               "症状与污染同形。若判定属实:整卷复跑洗不掉,须清理床上残留(床权在你)。"
             + _grp_note + "如何处置?")
        return {"question": q, "header": f"床态{aid[-4:]}",
                "options": [
                    {"label": "挂起到下批", "description": "床治理后下批续跑该案(重跑同参数时会询问恢复)"},
                    {"label": "床已处理,复跑验证", "description": "你已清理残留——引擎复跑一次验证"},
                    {"label": "如实降级", "description": "该案不入交付卷,以未通过如实报告"}],
                "_tokens": {"挂起到下批": "suspend", "床已处理,复跑验证": "retry",
                            "如实降级": "downgrade"},
                "_key": aid}
    if kind == "suspended":
        _g2 = [str(a)[-6:] for a in (c.get("group_aids") or []) if str(a) != str(aid)]
        q = (f"{who} 上批被挂起。"
             + (f"本题代表 {len(_g2) + 1} 个同因挂起用例(另含尾号 {'、'.join(_g2[:8])})"
                f",答案应用到全部。" if _g2 else "")
             + "本批如何处理?")
        return {"question": q, "header": f"挂起{aid[-4:]}",
                "options": [
                    {"label": "恢复处理", "description": "回到正常流程继续修"},
                    {"label": "保持挂起", "description": "本批继续不动它"}],
                "_tokens": {"恢复处理": "resume", "保持挂起": "keep"},
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
            "_tokens": {"重排复验": "reorder", "如实降级": "downgrade"},
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
