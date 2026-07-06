"""验证段节点:merge([mech])→ run_digest([mech])→ attribute([mech]+[llm]孔③)。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from main.ist_core.compile_engine import ledger as L
from main.ist_core.compile_engine.nodes import _shared as sh


# ---------------------------------------------------------------- [mech] merge
def merge(state: dict) -> dict:
    """合并本轮目标集(首轮=全部 produced;修复轮=fail 子集;终验=整卷)。

    pass 卷面锁复核在前(E3 机器门):任何 LOCKED_PASS 卷 mtime 变了 → tampered,拒合并。
    """
    led = sh.load_ledger(state)
    tampered = led.verify_pass_locks(sh.outputs_root())
    if tampered:
        led.data["audit"]["notes"].append({"event": "tampered", "autoids": tampered})
        led.save()
        return {"phase_status": "error",
                "error": f"pass 卷面被改动: {[a[-6:] for a in tampered]}——拒绝合并交付",
                **sh.counts_update(led)}

    out_name = str(state.get("out_name"))
    round_no = int(state.get("round") or 0)
    fails = led.in_state(L.S_FAILED_ACTIVE)
    produced = led.in_state(L.S_PRODUCED)

    if round_no == 0:
        target, scope, name = sorted(produced), "full", out_name
    elif fails or produced:
        # 修复轮:fail(transient 复跑)+重编后的 produced 都只跑**子集**——
        # 2026-07-06 dongkl 轮实证:旧分支在重编后 fails 清空时误走整卷,
        # round2/3 把 21 个已 pass 卷重复上机(浪费设备轮+暴露 6/21 翻转)。
        target = sorted(set(fails) | set(produced))
        scope, name = "subset", f"{out_name}_fails_r{round_no}"
    else:
        # 子集全过 → 终验整卷(passed 全量,一遍上机交付证据)
        target = sorted(led.in_state(L.S_PASSED))
        scope, name = "full", out_name
    if not target:
        return {"phase_status": "nothing_to_do", **sh.counts_update(led)}

    from main.ist_core.tools.device.emit_xlsx_tool import compile_emit_merged
    res = compile_emit_merged.func(autoids=target, out_name=name)
    xlsx = sh.outputs_root() / name / "case.xlsx"
    if not xlsx.is_file():
        return {"phase_status": "error",
                "error": f"合并失败: {str(res)[-400:]}", **sh.counts_update(led)}
    sh.emit(f"merge[{scope}] {len(target)} case → {name}/case.xlsx")
    sh.emit_tick(led, state, "merge")
    return {"phase_status": "ok", "run_scope": scope,
            "merged_xlsx_ref": str(xlsx.relative_to(sh.project_root())),
            **sh.counts_update(led)}


# ------------------------------------------------------------ [mech] run_digest
def run_digest(state: dict) -> dict:
    """整卷上机(dev_run_batch_digest 进程内直调)→ 按 last_run.json 晋升/降级。

    幂等(resume 契约):run_marker{round, xlsx_mtime} 已跑过且卷面未变 → 直接消费
    现有 last_run,不重复烧设备轮。device_busy 退避 3×120s。
    """
    led = sh.load_ledger(state)
    xlsx = sh.project_root() / str(state.get("merged_xlsx_ref") or "")
    if not xlsx.is_file():
        return {"phase_status": "error", "error": "无合并卷可上机", **sh.counts_update(led)}
    mtime = xlsx.stat().st_mtime
    round_no = int(state.get("round") or 0) + 1
    last_run = xlsx.parent / "last_run.json"

    marker = led.data.get("run_marker") or {}
    already = (marker.get("round") == round_no
               and abs(float(marker.get("xlsx_mtime", -1)) - mtime) < 1e-6
               and last_run.is_file())
    if not already:
        from main.ist_core.tools.device.batch_tools import dev_run_batch_digest
        sh.emit(f"上机 round{round_no}({state.get('run_scope')}): {xlsx.parent.name}")
        sh.emit_tick(led, {**state, "round": round_no}, "run_digest")
        for attempt in range(4):
            out = dev_run_batch_digest.func(str(xlsx))
            if "run_in_progress" in str(out) or "device_busy" in str(out):
                if attempt == 3:
                    return {"phase_status": "device_busy",
                            "error": "设备持续占用,稍后重调引擎续跑(checkpoint 已存)",
                            **sh.counts_update(led)}
                time.sleep(120)
                continue
            break
        if not last_run.is_file():
            return {"phase_status": "error",
                    "error": f"digest 未产出 last_run: {str(out)[-300:]}",
                    **sh.counts_update(led)}
        led.data["run_marker"] = {"round": round_no, "xlsx_mtime": mtime}

    data = sh.read_json(last_run, [])
    items = data if isinstance(data, list) else data.get("results", [])
    cur = {str(it.get("autoid")): it for it in items
           if isinstance(it, dict) and it.get("autoid")}
    for aid, it in cur.items():
        st = led.case(aid).get("state")
        if st not in (L.S_PRODUCED, L.S_FAILED_ACTIVE, L.S_PASSED):
            continue
        v = str(it.get("verdict"))
        led.case(aid).setdefault("verdict_history", []).append(v)
        if v == "pass":
            if st != L.S_PASSED:
                xp = sh.outputs_root() / aid / "case.xlsx"
                led.lock_pass(aid, xp.stat().st_mtime if xp.is_file() else 0.0)
        elif st == L.S_PASSED:
            # LOCKED_PASS 在后续轮被判 fail:卷面没动(锁复核过)→ **运行时欠定**
            # (E6 双跑实证 778041 同卷两跑翻转)。标注独立分层:不回炉、不算编译失败,
            # 报告单列交人工判读(接入判定=E6 flips≥1,docs/PLAN 支柱4)。
            led.case(aid)["runtime_underdetermined"] = True
            led.data["audit"]["notes"].append(
                {"autoid": aid, "event": "verdict_flip_on_locked_pass"})
        else:
            led.transition(aid, L.S_FAILED_ACTIVE)
    led.save()
    sh.emit_tick(led, {**state, "round": round_no}, "run_digest")
    return {"phase_status": "ok", "round": round_no,
            "last_run_ref": str(last_run.relative_to(sh.project_root())),
            **sh.counts_update(led)}


# ------------------------------------------------- [mech]+[llm]孔③ attribute
def attribute(state: dict) -> dict:
    """fail 归因:known_defects 短路 → 机械预判(^→G/文件级崩溃) → 孔③ fork 填
    undetermined → 机读 disposition 路由(reflow/frozen/product_defect/env_blocked)。
    引擎只认 last_run.json 落盘的 _attribution 字段(散文不算数)。
    """
    led = sh.load_ledger(state)
    fails = led.in_state(L.S_FAILED_ACTIVE)
    if not fails:
        return {"phase_status": "nothing_to_do", **sh.counts_update(led)}
    last_run = sh.project_root() / str(state.get("last_run_ref") or "")
    data = sh.read_json(last_run, [])
    items = {str(it.get("autoid")): it for it in (data if isinstance(data, list) else [])
             if isinstance(it, dict)}
    max_rounds = int(state.get("max_rounds") or 3)
    round_no = int(state.get("round") or 0)

    # 已知缺陷短路(机械,不进 LLM 孔)
    known = sh.read_json(sh.project_root() / "knowledge" / "data" / "auto_env"
                         / "env_capabilities.json", {}) or {}
    # 匹配增强(2026-07-06):feature 是长描述文本,原样 in ctx 几乎不命中(572672
    # 的 DC-2a 实证漏过)——按 feature 的命令 token 组匹配(全部 ≥4 字符 token 都在
    # ctx 即命中),仍是机械判定。
    defect_feats = []
    for d in (known.get("known_defects") or []):
        toks = [w for w in str(d.get("feature", "")).replace("<", " ").replace(">", " ").split()
                if len(w) >= 4 and w.isascii()]
        if toks:
            defect_feats.append(toks)

    need_fork: list[str] = []
    for aid in fails:
        it = items.get(aid, {})
        ctx = str(it.get("device_context") or "")
        attr = it.get("_attribution") if isinstance(it.get("_attribution"), dict) else {}
        c = led.case(aid)
        # 逐轮 fail 证据(升级/报告用):main 复述曾凭上下文记忆重构设备回显并伪造
        # 配置会话(CNAME 570 LangSmith 实证)——真原文按轮存进台账,复述才有据可引。
        # 按 round 幂等(checkpoint 续跑重入 attribute 不重复追加)。
        ev = c.setdefault("fail_evidence", [])
        if not any(e.get("round") == round_no for e in ev if isinstance(e, dict)):
            ev.append({"round": round_no, "verdict": "fail",
                       # 20000(2026-07-07):unsuccessful_cases.md 从 fail_evidence 读逐轮设备
                       # 原文,清 temp 后自足(不押 LangSmith)——旧 800 会截掉配置会话/回显。
                       "device_context": ctx[:20000]})
        # 冻结(digest 已判连续同签名)→ 终态
        frozen = (sh.outputs_root() / aid / ".frozen.json").is_file()
        if attr:
            c["attribution"] = attr
        disp = str((attr or {}).get("disposition") or "")
        layer = str((attr or {}).get("layer") or "")
        if not attr:
            from main.ist_core.tools.device.fail_attribution import attribute_fail
            try:
                mech = attribute_fail(str(it.get("detail_tail") or ctx)[:4000],
                                      failing_assertion_layer="")
                layer = getattr(mech, "layer", "") or (mech.get("layer") if isinstance(mech, dict) else "")
            except Exception:  # noqa: BLE001
                layer = ""
        if any(toks and all(w in ctx for w in toks) for toks in defect_feats):
            led.transition(aid, L.S_FAILED_TERMINAL, last_detail="known_defect(DC)")
        elif frozen and int(c.get("rounds_used") or 0) >= max_rounds:
            # frozen≠终态:.frozen.json 是「同法已证无效,重编必须换法」标记——轮次未
            # 封顶时 fall through 到 reflow,emit 的 override_frozen_reason 门强制换法
            # 声明(588691 round3 插 dig 正是走这条通道)。曾误改成「frozen 即终态」:
            # override 换法重编后文件不删,会把刚换法的 case 直接误判终态,机会通道全死。
            led.transition(aid, L.S_FAILED_TERMINAL, last_detail="frozen")
        elif disp in ("frozen", "product_defect", "env_blocked", "defect_candidate"):
            led.transition(aid, L.S_FAILED_TERMINAL, last_detail=disp)
        elif (disp == "reflow" or layer == "G") and round_no < max_rounds:
            c["evidence_excerpt"] = ctx[:4000]
            c["redispatch_reason"] = "verify_fail"
            led.transition(aid, L.S_PENDING)
        elif round_no >= max_rounds:
            # 轮次耗尽仍 fail 且无定性结论(上面的 known_defect/frozen/disposition
            # 终态都没接住)→ 升级人工,不再静默判 failed_terminal:CNAME 570 实证
            # 种子理解错的 case 烧满 3 轮后被吞成"编译失败",用户无从拍板。
            # reflow/G 封顶也走这里(转 pending 后已无派发轮,是死滞留态)。
            led.transition(aid, L.S_ESCALATED,
                           last_detail="max_rounds_exhausted",
                           escalation_reason="max_rounds_exhausted")
        else:
            need_fork.append(aid)

    if need_fork:
        # 孔③:compile-attributor fork,义务=submit_attribution 落盘;引擎只读回落盘字段
        from main.ist_core.tools.device.batch_tools import compile_fanout
        briefs = [{"key": aid, "brief": json.dumps({
            "autoid": aid, "last_run_path": str(state.get("last_run_ref")),
            "xlsx_path": str(state.get("merged_xlsx_ref")),   # submit_attribution 按它定位落盘文件,别让 fork 推断
            "provenance_path": f"workspace/outputs/{aid}/case.provenance.json",
        }, ensure_ascii=False)} for aid in need_fork]
        sh.emit(f"归因 fork: {len(need_fork)} case")
        compile_fanout.func(skill="compile-attributor", briefs_json=briefs,
                            evidence_from_xlsx=str(sh.project_root()
                                                   / str(state.get("merged_xlsx_ref") or "")))
        data2 = sh.read_json(last_run, [])
        items2 = {str(it.get("autoid")): it for it in (data2 if isinstance(data2, list) else [])
                  if isinstance(it, dict)}
        # 落盘兜底(2026-07-06 dongkl 实证):fork 曾把归因写进整卷 last_run(按
        # xlsx_path 定位)而引擎读本轮子集 last_run——两处按引用合并读,主目录兜底。
        main_lr = sh.outputs_root() / str(state.get("out_name")) / "last_run.json"
        if main_lr != last_run and main_lr.is_file():
            for it in (sh.read_json(main_lr, []) or []):
                aid2 = str(it.get("autoid", "")) if isinstance(it, dict) else ""
                if aid2 and (aid2 not in items2 or not items2[aid2].get("_attribution")) \
                        and isinstance(it.get("_attribution"), dict):
                    items2.setdefault(aid2, {})["_attribution"] = it["_attribution"]
        for aid in need_fork:
            attr = items2.get(aid, {}).get("_attribution")
            attr = attr if isinstance(attr, dict) else {}
            c = led.case(aid)
            c["attribution"] = attr
            disp = str(attr.get("disposition") or "")
            if disp in ("frozen", "product_defect", "env_blocked", "defect_candidate"):
                led.transition(aid, L.S_FAILED_TERMINAL, last_detail=disp)
            elif disp in ("reflow", "fixed"):
                c["evidence_excerpt"] = str(items2.get(aid, {}).get("device_context") or "")[:4000]
                c["redispatch_reason"] = "verify_fail"
                led.transition(aid, L.S_PENDING)
            elif disp == "transient":
                pass   # 保持 failed_active:不重编直接随下轮复跑
            else:
                # fork 跑了但没落回可路由的 disposition——引擎不知道怎么办,这不是
                # 定性结论,升级人工而非吞成 failed_terminal。
                led.transition(aid, L.S_ESCALATED,
                               last_detail="attribution_missing",
                               escalation_reason="attribution_missing")
    led.save()
    sh.emit_tick(led, state, "attribute")
    return {"phase_status": "ok", **sh.counts_update(led)}
