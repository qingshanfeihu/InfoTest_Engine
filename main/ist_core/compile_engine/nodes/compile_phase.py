"""编译段节点:prep([mech])→ worker_fanout([llm]孔①)→ ask_decision([user]孔②)。"""

from __future__ import annotations

import concurrent.futures as cf
import json
import re
import time
from pathlib import Path

from main.ist_core.compile_engine import ledger as L
from main.ist_core.compile_engine.nodes import _shared as sh
from main.ist_core.compile_engine.questions import (
    build_questions, load_ledgers, validate_questions, FORM_BY_KIND,
)

_TAIL_RE = re.compile(r"^状态：(produced|needs_user_decision|failed)", re.MULTILINE)
_MAX_REWORK = 3


# ---------------------------------------------------------------- [mech] prep
def prep(state: dict) -> dict:
    """脑图→manifest→ledger 初始化(幂等:manifest 新鲜且 ledger 已有 case 则跳过)。"""
    out_name = str(state.get("out_name") or Path(str(state.get("mindmap_path"))).stem)
    led = sh.load_ledger({**state, "out_name": out_name})
    manifest = sh.outputs_root() / out_name / "manifest.json"

    if not (manifest.is_file() and led.data["cases"]):
        from main.ist_core.tools.device.compile_prep import compile_prep
        res = compile_prep.invoke({"mindmap_path": str(state.get("mindmap_path")),
                                   "out_name": out_name})
        if not manifest.is_file():
            sh.emit_tick(led, {**state, "out_name": out_name}, "prep")
            return {"phase_status": "error", "out_name": out_name,
                    "error": f"prep 未产出 manifest: {str(res)[:200]}"}
        m = sh.read_json(manifest, {})
        for c in (m.get("cases") or []):
            aid = str(c.get("autoid") or "").strip()
            if aid and not led.case(aid).get("state"):
                led.transition(aid, L.S_PENDING)
        led.save()
        sh.emit(f"prep 完成: {len(led.data['cases'])} case → pending")

    # dispatched 孤儿回收(resume 缺口,2026-07-06):进程死在 worker 在飞时,这些
    # case 停在 dispatched——重启后无人认领。prep 是幂等重跑入口:无新鲜产出的
    # dispatched 回收为 pending 重派;盘上已有产出的按 produced 落账(事实优先)。
    orphans = led.in_state(L.S_DISPATCHED)
    for aid in orphans:
        xp = sh.outputs_root() / aid / "case.xlsx"
        if xp.is_file():
            led.transition(aid, L.S_PRODUCED, produced_mtime=xp.stat().st_mtime,
                           last_detail="orphan-recovered(盘上有产出)")
        else:
            led.transition(aid, L.S_PENDING, redispatch_reason="orphan_recovered")
    if orphans:
        led.save()
        sh.emit(f"回收 {len(orphans)} 个派发孤儿(进程中断残留)")

    sh.emit_tick(led, {**state, "out_name": out_name}, "prep")
    return {"phase_status": "ok", "out_name": out_name,
            "manifest_ref": str(manifest.relative_to(sh.project_root())),
            "ledger_ref": str(led.path.relative_to(sh.project_root())),
            "round": int(state.get("round") or 0),
            "wave": int(state.get("wave") or 0),
            **sh.counts_update(led)}


# ------------------------------------------------------- [llm]孔① worker_fanout
def _build_brief(aid: str, state: dict, case_led: dict, out_name: str) -> str:
    """机读信封(worker 契约零改动)+可选附件引用——数据按引用,不内联 manifest。"""
    envelope = {
        "autoid": aid,
        "manifest_path": state.get("manifest_ref", ""),
        "product_version": state.get("product_version", ""),
        "round": int(case_led.get("rounds_used") or 0) + 1,
        "redispatch_reason": case_led.get("redispatch_reason") or None,
    }
    adv = sh.outputs_root() / out_name / "advisory.md"
    if adv.is_file():
        envelope["advisory_path"] = str(adv.relative_to(sh.project_root()))
    ud = sh.outputs_root() / aid / "user_decision.json"
    if ud.is_file():
        envelope["user_decision_path"] = str(ud.relative_to(sh.project_root()))
    parts = [json.dumps(envelope, ensure_ascii=False)]
    fix = case_led.get("attribution", {}).get("fix_direction") if isinstance(
        case_led.get("attribution"), dict) else None
    if fix:
        parts.append(f"\n## 定向重做\n针对以下问题改,保留正确部分:\n{str(fix)[:1500]}")
    ev = case_led.get("evidence_excerpt")
    if ev:
        parts.append(f"\n## 上机设备证据(原文节选)\n```\n{str(ev)[:4000]}\n```")
    return "\n".join(parts)


def _dispatch_one(executor, aid: str, brief: str, t0: float) -> tuple[str, str]:
    """派单个 worker,按盘上事实+机读尾块判终态。返回 (终态, 详情)。"""
    out = executor.call("compile-worker", brief, tag=f"engine:{aid[-6:]}")
    xlsx = sh.outputs_root() / aid / "case.xlsx"
    fresh = xlsx.is_file() and xlsx.stat().st_mtime >= t0 - 1
    m = _TAIL_RE.search(out or "")
    tail = m.group(1) if m else ""
    if fresh:
        return L.S_PRODUCED, "盘上产出(新鲜)"
    if tail == "needs_user_decision" or "NEEDS_USER_DECISION" in (out or "")[-2000:]:
        nd = sh.outputs_root() / aid / "needs_decision.json"
        if nd.is_file():
            return L.S_PENDING_DECISION, "欠定(台账在盘)"
        return L.S_ESCALATED, "报欠定但无台账"
    return L.S_ESCALATED, f"未产出(尾块={tail or '无'}): {(out or '')[-300:]}"


def worker_fanout(state: dict) -> dict:
    """对 pending_compile 集并发派 compile-worker;终态写 ledger(盘上事实为准)。"""
    led = sh.load_ledger(state)
    pending = led.in_state(L.S_PENDING)
    if not pending:
        return {"phase_status": "nothing_to_do", **sh.counts_update(led)}

    round_no = int(state.get("round") or 0)
    led.record_dispatch(pending, round_no=round_no, allowed_from={L.S_PENDING})
    for aid in pending:
        led.transition(aid, L.S_DISPATCHED)
    led.save()
    sh.emit(f"wave{int(state.get('wave') or 0) + 1}: 派 {len(pending)} worker")
    sh.emit_tick(led, state, "worker_fanout")

    executor, limiter, ceiling = sh.fork_executor(len(pending))
    out_name = str(state.get("out_name"))
    t0 = time.time()

    def _run(aid: str) -> None:
        c = led.case(aid)
        rework = 0
        final, detail = L.S_ESCALATED, "未执行"
        while rework <= _MAX_REWORK:
            with limiter:
                final, detail = _dispatch_one(executor, aid, _build_brief(aid, state, c, out_name), t0)
            c["rounds_used"] = int(c.get("rounds_used") or 0) + 1
            if final == L.S_PRODUCED:
                # 机械探针(grade 出主路后的第二道闸):suspect 信号带反馈重做
                try:
                    from main.ist_core.tools.device.compile_pipeline import _grade_extract_facts
                    facts = _grade_extract_facts(aid) or {}
                    sus = [k for k, v in facts.items() if k.endswith("_suspect") and v]
                except Exception:  # noqa: BLE001
                    sus = []
                if sus and rework < _MAX_REWORK:
                    rework += 1
                    c["redispatch_reason"] = f"probe:{','.join(sus)}"
                    sh.emit(f"{aid[-6:]} 探针 {sus} → 重做 {rework}/{_MAX_REWORK}")
                    continue
            break
        led.transition(aid, final,
                       produced_mtime=(sh.outputs_root() / aid / "case.xlsx").stat().st_mtime
                       if final == L.S_PRODUCED else None,
                       last_detail=detail)
        sh.emit_tick(led, state, "worker_fanout")   # 每 case 落账即刷引擎卡

    with cf.ThreadPoolExecutor(max_workers=ceiling) as ex:
        list(ex.map(_run, pending))
    led.save()
    sh.emit(f"wave 完成: produced={len(led.in_state(L.S_PRODUCED))} "
            f"欠定={len(led.in_state(L.S_PENDING_DECISION))}")
    sh.emit_tick(led, state, "worker_fanout")
    return {"phase_status": "ok", "wave": int(state.get("wave") or 0) + 1,
            **sh.counts_update(led)}


# ------------------------------------------------------ [user]孔② ask_decision
def ask_decision(state: dict) -> dict:
    """欠定汇总 → `interrupt(questions)` 图级挂起 → 拿用户答案落 compile_user_decision。

    官方 HIL 模式(langgraph-human-in-the-loop skill):interrupt+Command(resume)+
    checkpointer——挂起即持久化,进程死了 resume 照接(会话死锁教训的图层根治)。
    薄工具在边界把 interrupt payload 桥接给既有 ask_user 面板。
    resume 时节点**从头重跑**(官方语义)——interrupt 之前只做纯读聚合,幂等:
    已有 user_decision.json 的 case 直接落定,不再进问题集。
    """
    led = sh.load_ledger(state)
    pend = led.in_state(L.S_PENDING_DECISION)
    if not pend:
        return {"phase_status": "nothing_to_do", **sh.counts_update(led)}

    from main.ist_core.tools.device.verifiability_tool import compile_user_decision

    # 幂等前段(重跑安全):台账缺失→escalate;已有决策文件→直接落定
    ledgers = load_ledgers(sh.outputs_root(), pend)
    for aid in list(pend):
        if aid not in ledgers:
            led.transition(aid, L.S_ESCALATED, last_detail="欠定无台账")
            pend.remove(aid)
        elif (sh.outputs_root() / aid / "user_decision.json").is_file():
            led.transition(aid, L.S_PENDING, redispatch_reason="user_decision")
            pend.remove(aid)
            ledgers.pop(aid, None)
    if not pend:
        led.save()
        sh.emit_tick(led, state, "ask_decision")
        return {"phase_status": "ok", **sh.counts_update(led)}

    questions = build_questions(ledgers)
    if not validate_questions(questions, ledgers):   # 模板自检(构造即合法,失败=bug)
        led.save()
        sh.emit_tick(led, state, "ask_decision")
        return {"phase_status": "error", "error": "问题模板自检失败", **sh.counts_update(led)}

    # 图级挂起:payload JSON 可序列化(官方要求);内部键(_autoid 等)留给桥接方路由。
    # 期望的 resume 答案:{autoid: 选项label, ..., "_non_interactive": bool}
    from langgraph.types import interrupt
    answers = interrupt({"kind": "ask_decision", "questions": questions})
    answers = answers if isinstance(answers, dict) else {}
    non_interactive = bool(answers.get("_non_interactive"))

    for q in questions:
        aid = q["_autoid"]
        if led.case(aid).get("state") != L.S_PENDING_DECISION:
            continue
        ans = str(answers.get(aid, "") or "")
        decision = next((d for d in ("改过程", "改预期", "改描述") if d in ans), "")
        if non_interactive or not decision:
            led.transition(aid, L.S_AWAITING_USER, last_detail="用户未答/非交互")
            continue
        drop = q["_ordering"] and decision == "改预期"   # 选项文本已显式写明放弃
        form = q["_form"] if decision == "改过程" else (
            "captured_relation" if decision == "改预期" else "")
        res = compile_user_decision.func(
            aid, decision, assertion_form=form, drop_ordering=drop,
            note=f"engine ask_decision: {ans[:120]}")
        if str(res).startswith("error"):
            led.transition(aid, L.S_AWAITING_USER, last_detail=f"决策落盘失败: {str(res)[:160]}")
            continue
        if decision == "改描述":
            led.transition(aid, L.S_AWAITING_USER, last_detail="改描述:待人工厘清")
        else:
            led.transition(aid, L.S_PENDING, redispatch_reason="user_decision")
    led.save()
    sh.emit_tick(led, state, "ask_decision")
    return {"phase_status": "ok", **sh.counts_update(led)}
