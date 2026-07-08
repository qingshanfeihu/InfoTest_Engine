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
# 不具备 rework 触发资格的 suspect(仍产 facts/note,走 fail 路径注入):2026-07-08 对 dongkl
# 13 张真机 PASS 卷实测,cname 成员未本地定义在 12/13 上误火(委托外部 DNS 是 cname 用例常态,
# 该语义歧义离线判不动)——当 rework 触发必致告警疲劳+派发风暴;它只在「上机真 fail + dig 返回
# CNAME 串而非 IP」的合取下才有诊断力,故由 _build_brief 在 verify_fail 重编时并入设备证据旁。
_PROBE_NO_REWORK = frozenset({"cname_member_not_local_host_suspect"})


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
        sh.emit(f"准备完成:{len(led.data['cases'])} 个用例 → 待编写")

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
def _linker_fact_note(aid: str) -> str:
    """上一轮成品卷上的引用结构事实(离线链接器,只取无 rework 资格那批的 note)。

    这些事实单独看是常态形态(cname 成员未本地定义在 13 张真机 PASS 卷的 12 张上同形),
    不配触发 rework;但上机 fail 后与设备回显**合取**就有诊断力——dig 返回 CNAME 记录串
    而非 IP + 成员未本地定义 = 解析链在成员域名处断头(035413 三轮 escalated 根因)。
    """
    try:
        from main.ist_core.tools.device.compile_pipeline import _grade_extract_facts
        d = sh.outputs_root() / aid
        facts = _grade_extract_facts(d / "case.xlsx", d / "case.provenance.json") or {}
    except Exception:  # noqa: BLE001
        return ""
    notes = []
    for k in _PROBE_NO_REWORK:
        base = k[: -len("_suspect")]
        if facts.get(k) and str(facts.get(base + "_note") or "").strip():
            notes.append(str(facts[base + "_note"]).strip())
    return "\n".join(notes)


def _intent_summary(aid: str, state: dict) -> str:
    """从 manifest 抽本 case 的意图摘要(标题/分组/step_intents 的 desc→expected)。

    为什么内联而不只按引用:意图只给 manifest 路径时,响度拼不过 brief 里内联的归因方向——
    trace 019f3bc3 实证,R3 worker fs_read 过 manifest、却全程没质疑过「dig 该返回 IP」,
    注意力被内联的 priority 定向钉死。现布局把意图放在紧邻指令区的位置(recency=注意力
    最高位,官方长上下文实践),与方向争夺注意力;全文仍按引用(envelope.manifest_path),
    出入以 manifest 为准。
    """
    try:
        mp = sh.project_root() / str(state.get("manifest_ref") or "")
        m = sh.read_json(mp, {}) or {}
        c = next((x for x in (m.get("cases") or [])
                  if str(x.get("autoid")) == aid), None)
        if not isinstance(c, dict):
            return ""
        lines = [f"标题:{c.get('title', '')}  分组:{' / '.join(c.get('group_path') or [])}"]
        for si in (c.get("step_intents") or [])[:8]:
            d = str(si.get("desc") or "").strip()
            e = str(si.get("expected") or "").strip()
            if d or e:
                lines.append(f"- {d}" + (f" → 期望:{e}" if e else ""))
        return "\n".join(lines)[:1200]
    except Exception:  # noqa: BLE001
        return ""


def _build_brief(aid: str, state: dict, case_led: dict, out_name: str) -> str:
    """机读信封(worker 契约零改动)+可选附件引用——数据按引用,不内联 manifest。

    末轮增强(2026-07-07):前 max_rounds-1 次上机均 fail 的最后一次(与 worker_fanout 的
    effort=max 同判据 rounds_used>=max_rounds-1),改喂全历史设备回显+逐轮归因+前几次配置卷
    路径(数据按引用),让顶满思考深度的 worker 拿到前几次全貌、别重复错法;非末轮维持轻量
    (只喂最新一轮证据)不膨胀上下文。

    去劫持(2026-07-08,trace 019f3bc3 取证驱动):①意图摘要内联(不再只按引用);②归因方向
    降级为「上一轮假设」并要求先独立复核设备行为再采信;③末轮首要动作=先答「配置实现意图
    了吗」。三轮 escalated 的机制正是 brief 以自信的错方向开路+意图只按引用,方向越锁越死。

    布局(2026-07-08 官方长上下文实践):数据置顶、指令在末——首行机读信封 →
    <device_evidence>(逐轮 <document>) → <prior_config_rolls> → <structural_facts> →
    <prior_hypothesis> → <intent> → <round_task>(指令)。意图从"置顶"改为"紧邻指令区"
    (recency=注意力最高位),归因假设居中(响度降级)——去劫持目标不变,实现从措辞升级为位置。
    """
    max_rounds = int(state.get("max_rounds") or 3)
    rounds_used = int(case_led.get("rounds_used") or 0)
    envelope = {
        "autoid": aid,
        "manifest_path": state.get("manifest_ref", ""),
        "product_version": state.get("product_version", ""),
        "round": rounds_used + 1,
        "redispatch_reason": case_led.get("redispatch_reason") or None,
    }
    adv = sh.outputs_root() / out_name / "advisory.md"
    if adv.is_file():
        envelope["advisory_path"] = str(adv.relative_to(sh.project_root()))
    ud = sh.outputs_root() / aid / "user_decision.json"
    if ud.is_file():
        envelope["user_decision_path"] = str(ud.relative_to(sh.project_root()))
    # 布局(2026-07-08 官方长上下文实践):首行机读信封(卡片/解析读首行) → 数据区(长数据
    # 置顶:逐轮设备回显 → 配置卷路径 → 结构事实 → 归因假设) → 意图 → 指令区(最末)。
    # 官方实测把查询/指令放末尾对长输入提升可达 30%;意图紧邻指令=recency 注意力最高位,
    # 归因假设居中=响度降级(去劫持目标不变,实现换成位置而非只靠措辞)。
    parts = [json.dumps(envelope, ensure_ascii=False)]
    tail: list[str] = []   # 指令区,最后拼接

    is_last = rounds_used >= max_rounds - 1
    hist = [e for e in (case_led.get("fail_evidence") or []) if isinstance(e, dict)]

    # ── 数据区 ──────────────────────────────────────────────────────────
    if is_last and hist:
        # 末轮全回显:思考深度已由 worker_fanout 升到 max,配套喂前几次全历史。
        docs = []
        for e in hist:
            rn = e.get("round")
            sig = "/".join(x for x in (str(e.get("layer") or ""),
                                       str(e.get("disposition") or "")) if x)
            fd = str(e.get("fix_direction") or "")
            dc = str(e.get("device_context") or "")[:6000]
            docs.append(
                f'<document label="第{rn}次上机"' + (f' attribution="归因:{sig}"' if sig else "") + ">\n"
                + (f"<fix_direction>{fd[:800]}</fix_direction>\n" if fd else "")
                + f"<device_context>\n{dc}\n</device_context>\n</document>")
        parts.append("<device_evidence>\n" + "\n".join(docs) + "\n</device_evidence>")
        hist_dir = sh.outputs_root() / aid / "history"
        prev = sorted(hist_dir.glob("case.r*.xlsx")) if hist_dir.is_dir() else []
        if prev:
            listing = "\n".join(f"- {p.relative_to(sh.project_root())}" for p in prev)
            parts.append("<prior_config_rolls note=\"前几次配置卷,fs_read 逐卷对比\">\n"
                         + listing + "\n</prior_config_rolls>")
        tail.append(
            f"<round_task>\n最后一次编写(前 {rounds_used} 次上机均失败,思考深度已升至 max)。\n"
            "先不看逐轮归因的方向,对上面每一轮设备回显独立回答:配置实现意图了吗——"
            "dig/show 观测到的形态是不是意图要的那类东西(意图要 IP,观测就得是 A/AAAA 记录"
            "而不是 CNAME 串;意图要状态翻转,观测就得真翻转)。形态不对而断言又没写错,"
            "根因通常在配置结构(缺对象定义/引用断头/绑定关系错),沿前几轮方向继续修语法"
            "只会把同一个失败修得更精致。之后再逐轮评估归因哪些成立、哪些已被回显证伪。"
            "\n</round_task>")
    else:
        ev = case_led.get("evidence_excerpt")
        if ev:
            parts.append("<device_evidence note=\"上机设备证据原文节选\">\n"
                         + str(ev)[:4000] + "\n</device_evidence>")

    # fail 重编时注入上一轮卷面的引用结构事实(与设备回显对照才有诊断力,见 _linker_fact_note)
    if case_led.get("fail_evidence"):
        _fact = _linker_fact_note(aid)
        if _fact:
            parts.append("<structural_facts note=\"上一轮卷面引用结构,机械提取,与设备回显对照判断\">\n"
                         + _fact + "\n</structural_facts>")

    fix = case_led.get("attribution", {}).get("fix_direction") if isinstance(
        case_led.get("attribution"), dict) else None
    if fix:
        # 归因方向是假设不是结论——归因也会看错主次(035413 三轮:方向全盯配置语法,
        # dig 恒返回 CNAME 串而非 IP 的功能失效没人碰)。先独立复核,再决定采不采信。
        parts.append(
            "<prior_hypothesis note=\"上一轮归因假设,可能已被设备证伪,先独立复核再采信\">\n"
            "下面是上一轮归因给的修法方向。它是假设不是结论——先自己对设备回显回答"
            "「配置实现意图了吗:dig/show 观测到的形态是不是意图要的那类东西」,"
            "答案与这个方向一致再沿用;不一致时以你对意图和回显的判断为准,并在返回里说明分歧:\n"
            f"{str(fix)[:1500]}\n</prior_hypothesis>")

    # 意图(需求原件摘要;紧邻指令区=注意力最高位,首轮/重编轮都给,意图是不变量)
    intent = _intent_summary(aid, state)
    if intent:
        parts.append("<intent note=\"这条 case 的意图,需求原件摘要,全文在 manifest_path\">\n"
                     + intent + "\n</intent>")

    return "\n".join(parts + tail)


def _dispatch_one(executor, aid: str, brief: str, t0: float,
                  effort: str = "") -> tuple[str, str]:
    """派单个 worker,按盘上事实+机读尾块判终态。返回 (终态, 详情)。

    effort（可选,空|max）：升级重编的最后一次(rounds_used 已达上限前一步)传 max,把
    思考深度顶满——对标用户「最后一次跑把 thinking 强度改 max」。
    """
    out = executor.call("compile-worker", brief, tag=f"engine:{aid[-6:]}", effort=effort)
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
    sh.emit(f"第{int(state.get('wave') or 0) + 1}批:派发 {len(pending)} 个编写")
    sh.emit_tick(led, state, "worker_fanout")

    executor, limiter, ceiling = sh.fork_executor(len(pending))
    out_name = str(state.get("out_name"))
    max_rounds = int(state.get("max_rounds") or 3)
    t0 = time.time()

    def _run(aid: str) -> None:
        c = led.case(aid)
        rework = 0
        probe_fired: set[str] = set()   # 已提示过的 suspect——同信号只触发一次 rework(防原地打转)
        final, detail = L.S_ESCALATED, "未执行"
        while rework <= _MAX_REWORK:
            # 最后一次(前 max_rounds-1 轮已 fail):思考深度顶满 max,并让 brief 带上全历史证据。
            # rounds_used 是本 case 已跑过的写轮,达 max_rounds-1 即"这是最后一次机会"。
            eff = "max" if int(c.get("rounds_used") or 0) >= max_rounds - 1 else ""
            with limiter:
                final, detail = _dispatch_one(
                    executor, aid, _build_brief(aid, state, c, out_name), t0, effort=eff)
            c["rounds_used"] = int(c.get("rounds_used") or 0) + 1
            if final == L.S_PRODUCED:
                # 机械探针(grade 出主路后的第二道闸):suspect 信号带反馈重做。
                # 2026-07-08 修:此处曾单参调 _grade_extract_facts(aid)——签名是 (xp, prov),
                # TypeError 被 except 吞掉,探针自引擎上线**从未生效**(dongkl 全批零 probe: 记录
                # 即此)。按签名传成品卷与 provenance 路径。
                try:
                    from main.ist_core.tools.device.compile_pipeline import _grade_extract_facts
                    _case_dir = sh.outputs_root() / aid
                    facts = _grade_extract_facts(
                        _case_dir / "case.xlsx", _case_dir / "case.provenance.json") or {}
                    sus = [k for k, v in facts.items() if k.endswith("_suspect") and v
                           and k not in _PROBE_NO_REWORK]
                    # 同一 suspect 只触发一次 rework:卷面判断类信号在同卷上是稳态的,
                    # worker 已看过提示仍维持原判就尊重它——重复触发=原地打转白烧派发。
                    sus = [k for k in sus if k not in probe_fired]
                except Exception:  # noqa: BLE001
                    facts, sus = {}, []
                if sus and rework < _MAX_REWORK:
                    rework += 1
                    probe_fired.update(sus)
                    # suspect 名之外,带上对应 *_note 的事实说明(有则),worker 才知道具体哪里、为什么
                    notes = [str(facts.get(k[: -len("_suspect")] + "_note") or "").strip()
                             for k in sus]
                    notes = [n for n in notes if n]
                    c["redispatch_reason"] = (f"probe:{','.join(sus)}"
                                              + (("\n" + "\n".join(notes))[:1200] if notes else ""))
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
    sh.emit(f"本批完成:产出 {len(led.in_state(L.S_PRODUCED))} · "
            f"欠定 {len(led.in_state(L.S_PENDING_DECISION))}")
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
