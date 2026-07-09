"""收尾节点:writeback([mech])→ report([mech])。"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from main.ist_core.compile_engine import ledger as L
from main.ist_core.compile_engine.nodes import _shared as sh

logger = logging.getLogger(__name__)


# ------------------------------------------------------------- [mech] writeback
def writeback_one(aid: str, lr_ref: str, led) -> bool:
    """单 case 真 PASS 双写回:先例库(compile_writeback)+ footprint G 段(device_verified
    第二权威源)。幂等(mirror 同名覆盖/footprint 按 fact_key dedup),失败只记不阻断。

    verify_phase 在 case 转 PASSED 时**即时**调用(2026-07-08 selfheal1 实证:writeback
    只在批末发生时,608 R2 重编检索不到同批 570 R2 刚 PASS 的同族形态——正解在批内产生
    却流不到兄弟 case;570/608 意图同族,即时写回后 compile_precedent 立即可命中)。
    批末 writeback 节点保持兜底(防中途崩溃漏写)。passed 是 ledger 终态,写回安全。
    """
    ok = False
    try:
        from main.ist_core.tools.device.precedent_tools import compile_writeback
        compile_writeback.func(autoid=aid, last_run_path=lr_ref)
        ok = True
    except Exception:  # noqa: BLE001
        led.data["audit"]["notes"].append({"autoid": aid, "event": "precedent_writeback_fail"})
    try:
        from main.ist_core.tools.knowledge.footprint_writeback import compile_footprint_writeback
        pv = f"workspace/outputs/{aid}/case.provenance.json"
        compile_footprint_writeback.func(autoid=aid, provenance_path=pv,
                                         on_device_passed=True)
    except Exception:  # noqa: BLE001
        led.data["audit"]["notes"].append({"autoid": aid, "event": "footprint_writeback_fail"})
    try:
        _promote_behavior_candidates(aid, led)
    except Exception:  # noqa: BLE001
        led.data["audit"]["notes"].append({"autoid": aid, "event": "behavior_promote_fail"})
    try:
        from main.ist_core.memory.footprint.signals import emit_signal
        emit_signal("writeback_done", aid, source="closing.writeback_one", precedent=ok)
    except Exception:  # noqa: BLE001
        pass
    return ok


def writeback(state: dict) -> dict:
    """真 PASS 双写回(批末兜底轮;主写回已随 verify_phase 的 lock_pass 即时发生)。
    失败只记不阻断。"""
    led = sh.load_ledger(state)
    passed = led.in_state(L.S_PASSED)
    # 自愈环入库端(2026-07-08):fail/escalated 的行为观察以 uncertain 级入库——必须在
    # report._cleanup_temp 删 per-autoid 目录之前、且在"无 passed 早退"之前(全 fail 批
    # 恰恰是观察最有价值的批)。此前这些候选被整体丢弃,正解形态卡在知识断层外
    # (pe1 570/608 实证)。失败只记不阻断。
    try:
        _ingest_uncertain_observations(led)
    except Exception:  # noqa: BLE001
        led.data["audit"]["notes"].append({"event": "uncertain_ingest_fail"})
    if not passed:
        led.save()
        return {"phase_status": "nothing_to_do", **sh.counts_update(led)}
    lr_ref = str(state.get("last_run_ref") or "")
    wrote = sum(1 for aid in passed if writeback_one(aid, lr_ref, led))
    led.save()
    sh.emit(f"写回先例:{wrote}/{len(passed)} 个通过用例")
    sh.emit_tick(led, state, "writeback")
    return {"phase_status": "ok", **sh.counts_update(led)}


def _behavior_feature_head(cmd: str) -> list[str]:
    """观测命令 → 行为知识挂载的叶节点路径 token(剥算子动词与参数值)。

    uncertain 入库与 PASS 晋升**必须同函数**取 head——两路 feature_path/fact_key 同源,
    同一观察的 uncertain→verified 升级(merger 按 fact_key 对齐)才遇得上。动词表来自
    文法数据(domain_grammar verb_classes),不再各处手写((no,show,clear) 硬编码曾与
    文法漂移,红线评审 2026-07-08 低危项)。参数值 token(数字/IP/含点)剥掉只留命令词。
    """
    from main.case_compiler import domain_grammar as _dg
    strip = set(_dg.verbs("mutating") + _dg.verbs("config_query_probes"))
    return [t for t in (cmd or "").split()
            if t.lower() not in strip and t.isalpha()] or (cmd or "").split()[:1]


def _ingest_uncertain_observations(led) -> None:
    """fail/escalated case 的行为候选以 uncertain 级入库(自愈环入库端,2026-07-08)。

    与 _promote_behavior_candidates 的分工:PASS 候选走 device_verified 门升 verified;
    fail/escalated 候选**不冒充 verified**——RawFact 带 validity="uncertain" +
    observed_under 语境短句,merger 的 uncertain 分支放行(锚定=behavior_tool 入口的
    卷面命令门 + autoid 记录),渲染层按观察组并列展示、标注不确定。同 fact_key 将来
    PASS 实证时由 merger 升级分支就地转 verified。``FOOTPRINT_UNCERTAIN_WRITEBACK=0`` 关。
    """
    if (os.environ.get("FOOTPRINT_UNCERTAIN_WRITEBACK") or "1").strip().lower() in ("0", "false", "no"):
        return
    import hashlib
    from main.ist_core.memory.footprint.schema import RawFact
    from main.ist_core.memory.footprint.router import route_facts
    from main.ist_core.memory.footprint.merger import merge_fact
    from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS
    ingested = 0
    for aid in (led.in_state(L.S_FAILED_TERMINAL) + led.in_state(L.S_ESCALATED)):
        cands = sh.read_json(sh.outputs_root() / aid / "behavior_candidates.json", []) or []
        for c in cands:
            cmd = str(c.get("observe_cmd") or "").strip()
            content = str(c.get("content") or "").strip()
            if not cmd or not content:
                continue
            note = str(c.get("note") or "").strip()
            ctx = (note[:120] if note
                   else f"fail/escalated 轮观察(autoid …{aid[-6:]}),配置形态见该批取证")
            head = _behavior_feature_head(cmd)
            rf = RawFact(fact_kind="behavior", feature_path=head,
                         fact_key=f"{' '.join(head)}:{hashlib.sha1(content.encode()).hexdigest()[:8]}",
                         cli_syntax=cmd, content=content,
                         device_evidence={"autoid": aid, "run_ts": None},
                         source_thread=f"engine_uncertain:{aid}",
                         validity="uncertain", observed_under=ctx)
            try:
                for routed in route_facts([rf], Path(KNOWLEDGE_FOOTPRINTS)):
                    if merge_fact(routed, Path(KNOWLEDGE_FOOTPRINTS)).action != "skip":
                        ingested += 1
                        from main.ist_core.memory.footprint.signals import emit_signal
                        emit_signal("uncertain_ingested", rf.fact_key,
                                    source="closing._ingest_uncertain_observations",
                                    autoid=aid, observed_under=ctx)
            except Exception:  # noqa: BLE001
                continue
    if ingested:
        sh.emit(f"未定观察入库 {ingested} 条(uncertain 级,PASS 实证后自动升级)")


def _promote_behavior_candidates(aid: str, led) -> None:
    """行为候选晋升(V6 支柱2b 两段闸第二段):case 真 PASS 才把候选转
    RawFact(behavior)+device_evidence 入库——merger 的 device_verified 门再校验
    「观测命令真实出现在该 PASS 卷面」。fail/awaiting 的候选永不到这里。
    ``FOOTPRINT_BEHAVIOR_WRITEBACK=0`` 关。"""
    if not sh.env_flag("FOOTPRINT_BEHAVIOR_WRITEBACK"):
        return
    cand_path = sh.outputs_root() / aid / "behavior_candidates.json"
    cands = sh.read_json(cand_path, []) or []
    if not cands:
        return
    # 该 aid 最近一条 PASS 台账(device_evidence 锚)
    ledger_file = sh.project_root() / "runtime" / "logs" / "verified_runs.jsonl"
    ref = None
    if ledger_file.is_file():
        for line in ledger_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if str(rec.get("autoid")) == aid and str(rec.get("verdict")) == "pass":
                ref = {"autoid": aid, "run_ts": rec.get("run_ts")}
                if rec.get("build"):   # K 锚 build 位透传(理论 §5.1)
                    ref["build"] = str(rec["build"])
    if ref is None:
        return
    import hashlib
    from main.ist_core.memory.footprint.schema import RawFact
    from main.ist_core.memory.footprint.router import route_facts
    from main.ist_core.memory.footprint.merger import merge_fact
    from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS
    promoted = 0
    for c in cands:
        cmd = str(c.get("observe_cmd") or "").strip()
        content = str(c.get("content") or "").strip()
        if not cmd or not content:
            continue
        # 行为知识挂**叶节点**(剥前缀后全 token):截 2 段会落父节点,而 lookup
        # 对父节点只展开子树命令、不渲染父自身 behaviors——知识存了却读不回
        # (2026-07-06 种子实证)。head 取法与 uncertain 入库同函数(升级对齐)。
        head = _behavior_feature_head(cmd)
        rf = RawFact(fact_kind="behavior", feature_path=head,
                     fact_key=f"{' '.join(head)}:{hashlib.sha1(content.encode()).hexdigest()[:8]}",
                     cli_syntax=cmd, content=content,
                     device_evidence=dict(ref),
                     source_thread=f"engine_behavior:{aid}")
        try:
            for routed in route_facts([rf], Path(KNOWLEDGE_FOOTPRINTS)):
                if merge_fact(routed, Path(KNOWLEDGE_FOOTPRINTS)).action != "skip":
                    promoted += 1
        except Exception:  # noqa: BLE001
            continue
    if promoted:
        sh.emit(f"{aid[-6:]} 行为知识晋升 {promoted} 条")


# --------------------------------------------------------------- [mech] report
def report(state: dict) -> dict:
    """机读交付判定 + engine_report.json;结果摘要作为薄工具返回值素材。

    交付判定(用户判据机读形式):非 pass 的 case 全部 ∈ {awaiting_user,
    failed_terminal(DC/env/frozen), escalated} → delivered_with_labels;
    全 pass → delivered_all_pass;否则 stopped(带原因)。
    """
    led = sh.load_ledger(state)
    c = led.counts()
    n_total = len(led.data["cases"])
    n_pass = c.get(L.S_PASSED, 0)
    nonterminal = {k: v for k, v in c.items() if k not in L.TERMINAL_STATES and v}

    if state.get("phase_status") == "error" or state.get("error"):
        outcome = "error"
    elif n_pass == n_total and n_total > 0:
        outcome = "delivered_all_pass"
    elif not nonterminal and n_total > 0:
        outcome = "delivered_with_labels"
    else:
        outcome = "stopped"

    rep = {
        "outcome": outcome,
        "generated_at": time.time(),
        "totals": {"cases": n_total, "passed": n_pass, **c},
        "rounds": int(state.get("round") or 0),
        "waves": int(state.get("wave") or 0),
        "error": state.get("error") or "",
        "cases": {aid: {"state": cc.get("state"),
                        "rounds_used": cc.get("rounds_used"),
                        "verdicts": cc.get("verdict_history", []),
                        "detail": cc.get("last_detail", ""),
                        "runtime_underdetermined": bool(cc.get("runtime_underdetermined")),
                        "escalation_reason": cc.get("escalation_reason", ""),
                        "fail_evidence": cc.get("fail_evidence", []),
                        "attribution": cc.get("attribution", {})}
                  for aid, cc in sorted(led.data["cases"].items())},
        "audit": led.data.get("audit", {}),
        "refs": {"manifest": state.get("manifest_ref"),
                 "merged_xlsx": state.get("merged_xlsx_ref"),
                 "last_run": state.get("last_run_ref"),
                 "ledger": state.get("ledger_ref")},
    }
    out_name = str(state.get("out_name") or "engine")
    delivered = outcome in ("delivered_all_pass", "delivered_with_labels")
    # 收尾①(交付成功):归档非 pass 卷 + md 报告——**写 engine_report 前产出**(refs 进报告),
    # 两者都读 per-autoid/manifest,必须早于清 temp。收尾失败不阻断交付。
    fin_summary = ""
    if delivered:
        try:
            arch = _archive_unsuccessful(led, out_name)
            md = _write_unsuccessful_md(led, state, rep, out_name)
            rep["refs"]["archive_xlsx"] = arch
            rep["refs"]["unsuccessful_md"] = md
            # 人话交付报告落盘(refs 已就位后写,报告里可引路径):不依赖 main 的可截断转述,
            # 报告本体在盘上、截断也丢不了。
            delivery_md = _write_delivery_md(led, state, rep, out_name)
            rep["refs"]["delivery_md"] = delivery_md
            n_np = len(_nonpass_autoids(led))
            fin_summary = (f"归档非通过 {n_np}" + (f"→{Path(arch).parent.name}" if arch else "")
                           + (" · 逐例md✓" if md else "") + (" · 交付md✓" if delivery_md else ""))
        except Exception:  # noqa: BLE001
            logger.debug("交付收尾:归档/md 失败", exc_info=True)
    rp = sh.outputs_root() / out_name / "engine_report.json"
    rp.parent.mkdir(parents=True, exist_ok=True)
    tmp = rp.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    import os
    os.replace(tmp, rp)
    # 收尾②:清 temp——**最后一步**(md/归档/engine_report 均已落盘、读取已完成)。
    if delivered:
        try:
            n_rm = _cleanup_temp(led, out_name)
            fin_summary += (f" · 清{n_rm}项" if n_rm else " · 留临时")
        except Exception:  # noqa: BLE001
            logger.debug("交付收尾:清 temp 失败", exc_info=True)
    _oc = {"delivered_all_pass": "全部交付", "delivered_with_labels": "交付(含标注)",
           "stopped": "中止", "error": "出错"}.get(outcome, outcome)
    sh.emit(f"报告:{_oc} 通过 {n_pass}/{n_total}"
            + (" · " + fin_summary if fin_summary else ""))
    sh.emit_tick(led, state, "report")
    return {"phase_status": "ok",
            "report_ref": str(rp.relative_to(sh.project_root())),
            **sh.counts_update(led)}


# ============================================ 交付收尾:归档卷 + md 报告 + 清 temp
# 需求(用户 2026-07-07):① 非 pass 用例(缺陷/改描述/编写卡死/上机对不上/设备报错)如实
# 归档进独立 excel(主卷保持全绿);② 出 unsuccessful_cases.md 全量报告(脑图原始/自动化/
# ask_user 改动/逐轮 CUT/设备原文/main 判断/bug);③ 交付后清 temp。md 自足→不押 LangSmith。
# **顺序铁律**:先产全量交付物(archive→md,读 per-autoid/manifest/provenance)再删。

_NONPASS_STATES = (L.S_FAILED_TERMINAL, L.S_ESCALATED, L.S_AWAITING_USER)


def _nonpass_autoids(led) -> list[str]:
    return sorted(a for a, c in led.data["cases"].items()
                  if c.get("state") in _NONPASS_STATES)


def _fail_category(attr: dict, st: str) -> str:
    """失败分类(桶):由 attribution.layer/disposition + state 机械判,给 md 一眼归类。"""
    disp = str((attr or {}).get("disposition") or "")
    layer = str((attr or {}).get("layer") or "")
    if st == L.S_ESCALATED:
        return "编写卡死/引擎穷尽(升级人工)"
    if disp == "defect_candidate" or layer == "product_defect":
        return "产品缺陷"
    if disp == "env_blocked":
        return "环境阻塞"
    if layer == "G":
        return "设备执行报错/语法拒绝"
    if layer == "V":
        return "上机输出与编写不符"
    if st == L.S_AWAITING_USER:
        return "改描述/待人工厘清"
    return "未分类"


# 内部代码 → 人读描述:报告面向人,别把 layer/disposition/escalation_reason 这类机器 code
# 直接甩给读者(用户实证:md 里「layer E · disposition env_blocked」不适合阅读)。
_LAYER_CN = {"G": "设备语法/能力拒绝", "E": "环境/IP 问题", "V": "断言与设备真实行为不符",
             "transient": "瞬态偶发(不可复现)", "product_defect": "疑似产品缺陷"}
_DISP_CN = {"reflow": "带反馈重编", "frozen": "冻结换法重编", "env_blocked": "环境阻塞(跑完为先)",
            "defect_candidate": "缺陷候选(走缺陷单)", "fixed": "已修复待复跑"}
_REASON_CN = {"max_rounds_exhausted": "轮次耗尽仍未通过", "attribution_missing": "引擎归因缺失(不知如何处置)",
              "env_blocked": "环境阻塞(设备/环境层面,非用例问题)", "product_defect": "疑似产品缺陷",
              "defect_candidate": "缺陷候选(走缺陷单)", "frozen": "同签名连续 fail 冻结",
              "known_defect(DC)": "命中已知缺陷"}


def _readable_attr(attr: dict) -> str:
    """归因 layer/disposition → 人读一行(空则返回空串)。"""
    parts = [_LAYER_CN.get(str((attr or {}).get("layer", "")), ""),
             _DISP_CN.get(str((attr or {}).get("disposition", "")), "")]
    return " · ".join(p for p in parts if p)


def _readable_reason(raw: str) -> str:
    """escalation_reason/detail code → 人读;未知原样返回。"""
    return _REASON_CN.get(str(raw or "").strip(), str(raw or "").strip())


def _archive_unsuccessful(led, out_name: str) -> str | None:
    """全部非 pass case 合并成归档卷,落**主交付目录内** ``<批名>/unsuccessful_cases.xlsx``。

    走 ``compile_emit_merged`` 的 ``cases_json`` 通道——**gate-free**:交付门(grade 凭证/
    lint/CUT 拒)是给主交付卷的,归档的本就是过不了门的失败卷,自己 ``_load_case_rows`` 抽行
    绕过。emit 只会写 ``<名>/case.xlsx``,故先 emit 到临时 ``<批名>_unsuccessful`` 再移入主
    目录(与主卷 case.xlsx/delivery_report.md 同处、一眼可见,2026-07-07 用户要求),命名
    ``unsuccessful_cases.xlsx`` 不与主卷撞名。返回相对路径或 None(无非 pass / 全部回读失败)。"""
    aids = _nonpass_autoids(led)
    if not aids:
        return None
    from main.ist_core.tools.device.precedent_tools import _load_case_rows
    from main.ist_core.tools.device.emit_xlsx_tool import compile_emit_merged
    cases = []
    for aid in aids:
        xp = sh.outputs_root() / aid / "case.xlsx"
        if not xp.is_file():
            continue
        try:
            rows = _load_case_rows(str(xp))
        except Exception:  # noqa: BLE001
            continue
        if rows:
            cases.append({"autoid": aid, "steps": rows})
    if not cases:
        return None
    arch_name = f"{out_name}_unsuccessful"
    compile_emit_merged.func(cases_json=json.dumps(cases, ensure_ascii=False),
                             out_name=arch_name)
    src = sh.outputs_root() / arch_name / "case.xlsx"
    if not src.is_file():
        return None
    # 挡进主交付目录:emit 落临时 <批名>_unsuccessful/case.xlsx → 移入 <批名>/unsuccessful_cases.xlsx
    # (_cleanup_temp 只删 per-autoid/_fails_r*/manifest/last_run,主目录 xlsx 当交付物保留)→ 清临时目录。
    # 移动失败回退原独立卷路径(不阻断交付)。
    import shutil
    dst = sh.outputs_root() / out_name / "unsuccessful_cases.xlsx"
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        shutil.rmtree(sh.outputs_root() / arch_name, ignore_errors=True)
    except Exception:  # noqa: BLE001
        return str(src.relative_to(sh.project_root())) if src.is_file() else None
    return str(dst.relative_to(sh.project_root())) if dst.is_file() else None


def _clean_device_echo(text: str, limit: int = 0) -> str:
    """设备回显**给人看**的清理(仅报告展示层):剥每行行首 ``YYYY-MM-DD HH:MM:SS <ip> -``
    时间戳前缀、折叠连续空行。limit>0 截断。

    **只清报告**——喂 LLM 归因的原始 device_context 一个字不动(时间戳是 causality 照妖镜/
    stale-log 判据,给 LLM 原始事实红线)。仅 delivery_report.md / unsuccessful_cases.md 用。
    """
    import re
    ts = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} +[\d.]+ +- +")
    lines: list[str] = []
    blank = False
    for ln in str(text or "").splitlines():
        ln = ts.sub("", ln).rstrip()
        if not ln:
            if blank:
                continue   # 折叠连续空行
            blank = True
        else:
            blank = False
        lines.append(ln)
    out = "\n".join(lines).strip()
    return out[:limit] if limit > 0 else out


def _write_unsuccessful_md(led, state, rep: dict, out_name: str) -> str | None:
    """逐非 pass case 全量报告(删 temp 前生成、自足)。数据源:manifest(脑图原始 title+
    step_intents)/ provenance(自动化 steps)/ user_decision(ask_user 改动)/ rep 的
    fail_evidence(逐轮 device 原文)+ attribution(main 判断/bug)。"""
    aids = _nonpass_autoids(led)
    if not aids:
        return None
    base = sh.outputs_root() / out_name
    manifest = sh.read_json(base / "manifest.json", {})
    mcases = {str(c.get("autoid")): c for c in (manifest.get("cases") or [])}
    rcases = rep.get("cases", {})
    from collections import Counter
    cats = Counter(_fail_category((rcases.get(a, {}).get("attribution") or {}),
                                  led.case(a).get("state")) for a in aids)
    out = [f"# 未成功用例报告 — {out_name}",
           f"> 脑图: {manifest.get('source', '')}",
           f"> 生成: {time.strftime('%Y-%m-%d %H:%M', time.localtime())} · 共 {len(aids)} 个未成功",
           "> 分类: " + " · ".join(f"{k} {v}" for k, v in cats.items()),
           ""]
    for aid in aids:
        c = led.case(aid)
        rc = rcases.get(aid, {})
        attr = rc.get("attribution") or {}
        mc = mcases.get(aid, {})
        out.append(f"## …{aid[-6:]} · 【{_fail_category(attr, c.get('state'))}】{mc.get('title', '')}")
        out.append(f"- autoid `{aid}` · state `{c.get('state')}` · 轮次 {c.get('rounds_used')} "
                   f"· verdicts {rc.get('verdicts', [])}")
        out.append("\n### 脑图原始用例")
        out.append(f"- 描述: {mc.get('title', '') or '(无)'}")
        for si in (mc.get("step_intents") or []):
            out.append(f"  - 过程: {si.get('desc', '')} → 预期: {si.get('expected', '') or '(未写)'}")
        prov = sh.read_json(sh.outputs_root() / aid / "case.provenance.json", {})
        out.append("\n### 自动化用例(编译产物)")
        for stp in (prov.get("steps") or []):
            src = stp.get("source") or {}
            ref = (":" + src.get("ref")) if src.get("ref") else ""
            out.append(f"  - `{stp.get('E', '')}`/`{stp.get('F', '')}`: {stp.get('G', '')} "
                       f"[{stp.get('layer', '')}·{src.get('kind', '')}{ref}]")
        ud = sh.read_json(sh.outputs_root() / aid / "user_decision.json", {})
        if ud:
            out.append(f"\n### ⚙ ask_user 改动: **{ud.get('decision', '')}** · 断言形态="
                       f"{ud.get('expected_assertion_form', '') or '—'}"
                       + (f" · 备注: {ud.get('note')}" if ud.get("note") else ""))
        out.append("\n### 逐轮 CUT 原因 + 设备实际输出")
        fe = rc.get("fail_evidence") or []
        if not fe:
            out.append("  (无逐轮证据)")
        for e in fe:
            out.append(f"\n**Round {e.get('round')}** — verdict={e.get('verdict')}")
            out.append("```\n" + _clean_device_echo(e.get("device_context") or "") + "\n```")
        out.append("\n### main 归因判断")
        _judged = _readable_attr(attr) or _readable_reason(
            str(rc.get("escalation_reason") or rc.get("detail") or ""))
        if _judged:
            out.append(f"- 判定: {_judged}")
        if attr.get("fix_direction"):
            out.append(f"- 说明: {attr.get('fix_direction')}")
        if not _judged and not attr.get("fix_direction"):
            out.append(f"- 状态: {c.get('state')}")
        dc = attr.get("defect_candidate")
        if isinstance(dc, dict) and dc:
            out.append("\n### 🐞 缺陷描述")
            for k in ("repro", "expected_with_source", "actual", "version", "ticket_id"):
                if dc.get(k):
                    out.append(f"- {k}: {dc.get(k)}")
        out.append("\n---\n")
    md_path = base / "unsuccessful_cases.md"
    md_path.write_text("\n".join(out), encoding="utf-8")
    return str(md_path.relative_to(sh.project_root()))


def _write_delivery_md(led, state, rep: dict, out_name: str) -> str | None:
    """整批交付报告(human-readable,抗截断):落盘、不依赖 main agent 的可截断转述——
    main 收尾只需指路"见 delivery_report.md"。数据源全在 rep(已构好)。汇总 pass/fail +
    交付件路径 + 需人工处置用例的原因与末轮设备回显。"""
    base = sh.outputs_root() / out_name
    t = rep.get("totals", {})
    n_total = t.get("cases", 0)
    n_pass = t.get("passed", 0)
    cases = rep.get("cases", {})
    refs = rep.get("refs", {})
    nonpass = {a: c for a, c in cases.items() if str(c.get("state")) != L.S_PASSED}
    _rel = lambda p: str(Path(p).relative_to(sh.project_root())) if p and Path(p).is_absolute() else (p or "")  # noqa: E731
    out = [
        f"# 交付报告 — {out_name}",
        f"> 生成: {time.strftime('%Y-%m-%d %H:%M', time.localtime())} · 结果 **{rep.get('outcome')}** · 轮次 {rep.get('rounds')}",
        "",
        "## 汇总",
        f"- 用例 {n_total} 个：**上机通过 {n_pass}** · 需人工处置 {len(nonpass)}",
    ]
    from collections import Counter
    stc = Counter(str(c.get("state")) for c in nonpass.values())
    if stc:
        out.append("- 未成功分布：" + " · ".join(f"{k} {v}" for k, v in stc.items()))
    out += ["", "## 交付件",
            f"- 主交付卷（{n_pass} 个通过 case）：`{refs.get('merged_xlsx') or _rel(base / 'case.xlsx')}`"]
    if refs.get("archive_xlsx"):
        out.append(f"- 未成功归档卷：`{refs['archive_xlsx']}`")
    if refs.get("unsuccessful_md"):
        out.append(f"- 未成功逐例报告：`{refs['unsuccessful_md']}`")
    out.append(f"- 机读全量：`{_rel(base / 'engine_report.json')}`"
               + (f" · 台账：`{refs.get('ledger')}`" if refs.get("ledger") else ""))
    if nonpass:
        out += ["", "## 需人工处置的用例"]
        for aid, c in sorted(nonpass.items()):
            reason = c.get("escalation_reason") or c.get("detail") or c.get("state")
            out.append(f"- **…{aid[-6:]}** `{c.get('state')}` — {reason}")
            fe = c.get("fail_evidence") or []
            last = fe[-1] if fe and isinstance(fe[-1], dict) else {}
            ctx = str(last.get("device_context") or "").strip()
            if ctx:
                clean = _clean_device_echo(ctx, limit=800)
                out.append("  - 末轮设备回显（节选，已去时间戳前缀）：\n\n```\n"
                           + clean + "\n```" + ("\n  …（完整见 unsuccessful_cases.md）" if len(ctx) > 800 else ""))
        out.append(f"\n> 逐例完整证据（脑图原始/自动化/逐轮设备原文/归因）见 "
                   f"`{refs.get('unsuccessful_md') or 'unsuccessful_cases.md'}`。")
    md_path = base / "delivery_report.md"
    md_path.write_text("\n".join(out), encoding="utf-8")
    return str(md_path.relative_to(sh.project_root()))


def _cleanup_temp(led, out_name: str) -> int:
    """交付后清 temp:per-autoid dir + 子集卷(``<批名>_fails_r*``)+ 批目录中间 JSON
    (manifest/last_run)。**保留**交付物:主卷 case.xlsx + engine_report.json +
    unsuccessful_cases.md + engine_ledger.json(审计)+ 归档卷。``IST_ENGINE_KEEP_TEMP=1``
    保留全部供 debug。返回删除项数。"""
    # 默认删(交付后清 temp);IST_ENGINE_KEEP_TEMP=1 保留供 debug。此闸是「默认关」——
    # 不用 sh.env_flag(它是「默认开」语义,会把未设也当保留),直接判显式开关值。
    if (os.environ.get("IST_ENGINE_KEEP_TEMP") or "").strip().lower() in ("1", "true", "yes", "on"):
        return 0
    import shutil
    root = sh.outputs_root()
    n = 0
    for aid in list(led.data["cases"].keys()):
        d = root / aid
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    for d in root.glob(f"{out_name}_fails_r*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    base = root / out_name
    for f in ("manifest.json", "last_run.json"):
        p = base / f
        if p.is_file():
            try:
                p.unlink()
                n += 1
            except Exception:  # noqa: BLE001
                pass
    # runtime/logs 的 fork 步骤 fastlog(compile_evidence.<pid>.{live.log,events.jsonl}):
    # 只在 live 监控期(tail -f)有用,交付后是纯累积——实测无人清、已残留一堆。删三类:
    # 本进程当次的(交付后不再需要)、进程已死的(那 TUI 早退了、日志成孤儿)、过期的
    # (默认 >24h;env IST_ENGINE_LOG_RETAIN_HOURS 调)。活着的别的 TUI 会话的日志保留。
    try:
        import time as _t
        logs = sh.project_root() / "runtime" / "logs"
        if logs.is_dir():
            cutoff = _t.time() - float(os.environ.get("IST_ENGINE_LOG_RETAIN_HOURS") or 24) * 3600
            my_pid = os.getpid()
            for p in logs.glob("compile_evidence.*"):
                try:
                    parts = p.name.split(".")
                    fpid = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else -1
                    dead = False
                    if fpid > 0 and fpid != my_pid:
                        try:
                            os.kill(fpid, 0)          # 存活探测(不发信号)
                        except ProcessLookupError:
                            dead = True               # 进程已死 → 孤儿日志
                        except PermissionError:
                            dead = False              # 活着(别的会话)→ 保留
                    if fpid == my_pid or dead or p.stat().st_mtime < cutoff:
                        p.unlink()
                        n += 1
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    return n
