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
def writeback(state: dict) -> dict:
    """真 PASS 双写回:先例库(compile_writeback)+ footprint G 段(device_verified
    第二权威源自动挂,支柱2a)。失败只记不阻断。"""
    led = sh.load_ledger(state)
    passed = led.in_state(L.S_PASSED)
    if not passed:
        return {"phase_status": "nothing_to_do", **sh.counts_update(led)}
    lr_ref = str(state.get("last_run_ref") or "")
    wrote = 0
    for aid in passed:
        try:
            from main.ist_core.tools.device.precedent_tools import compile_writeback
            compile_writeback.func(autoid=aid, last_run_path=lr_ref)
        except Exception:  # noqa: BLE001
            led.data["audit"]["notes"].append({"autoid": aid, "event": "precedent_writeback_fail"})
        try:
            from main.ist_core.tools.knowledge.footprint_writeback import compile_footprint_writeback
            pv = f"workspace/outputs/{aid}/case.provenance.json"
            compile_footprint_writeback.func(autoid=aid, provenance_path=pv,
                                             on_device_passed=True)
            wrote += 1
        except Exception:  # noqa: BLE001
            led.data["audit"]["notes"].append({"autoid": aid, "event": "footprint_writeback_fail"})
        try:
            _promote_behavior_candidates(aid, led)
        except Exception:  # noqa: BLE001
            led.data["audit"]["notes"].append({"autoid": aid, "event": "behavior_promote_fail"})
    led.save()
    sh.emit(f"写回: {wrote}/{len(passed)} PASS case")
    sh.emit_tick(led, state, "writeback")
    return {"phase_status": "ok", **sh.counts_update(led)}


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
        # (2026-07-06 种子实证)。参数值 token(数字/IP/含点)剥掉,只留命令词。
        head = [t for t in cmd.split()
                if t.lower() not in ("no", "show", "clear")
                and t.isalpha()] or cmd.split()[:1]
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
    """机读交付判定 + engine_report.json;人话摘要作为薄工具返回值素材。

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
            n_np = len(_nonpass_autoids(led))
            fin_summary = (f"归档非pass {n_np}" + (f"→{Path(arch).parent.name}" if arch else "")
                           + (" · md✓" if md else ""))
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
            fin_summary += (f" · 清{n_rm}项" if n_rm else " · 留temp")
        except Exception:  # noqa: BLE001
            logger.debug("交付收尾:清 temp 失败", exc_info=True)
    sh.emit(f"report: {outcome} pass={n_pass}/{n_total}"
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


def _archive_unsuccessful(led, out_name: str) -> str | None:
    """全部非 pass case 合并成独立归档卷 ``<批名>_unsuccessful/case.xlsx``。

    走 ``compile_emit_merged`` 的 ``cases_json`` 通道——**gate-free**:交付门(grade 凭证/
    lint/CUT 拒)是给主交付卷的,归档的本就是过不了门的失败卷,自己 ``_load_case_rows`` 抽行
    绕过。返回相对路径或 None(无非 pass / 全部回读失败)。"""
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
    xlsx = sh.outputs_root() / arch_name / "case.xlsx"
    return str(xlsx.relative_to(sh.project_root())) if xlsx.is_file() else None


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
            out.append("```\n" + str(e.get("device_context") or "").rstrip() + "\n```")
        out.append("\n### main 归因判断")
        out.append(f"- layer `{attr.get('layer', '') or '—'}` · disposition "
                   f"`{attr.get('disposition', '') or '—'}`")
        if attr.get("fix_direction"):
            out.append(f"- 判断/修法: {attr.get('fix_direction')}")
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
    return n
