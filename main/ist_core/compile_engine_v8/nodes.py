"""V8 节点(十个;类型见 state.NODE_TYPES)。真理=事实流,节点=事实的搬运工。

依赖注入(测试面):run/probe/fork 经模块级 hook(_digest_fn/_probe_fn/_fork_fn)可替——
生产默认绑定真实工具;yzg 场景包用假设备回放。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from langgraph.types import interrupt

from main.ist_core.compile_engine_v8 import _shared as sh
from main.ist_core.compile_engine_v8 import bed as B
from main.ist_core.compile_engine_v8 import briefs as BR
from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import persistence as P
from main.ist_core.compile_engine_v8 import views as V

logger = logging.getLogger(__name__)

_TAIL_RE = re.compile(r"^STATUS:\s*(produced|needs_user_decision|failed)", re.MULTILINE)
_MAX_ASK_ROUNDS = 8      # ask 分批上限(每批 ≤4 题;面板硬限)


# ── 注入点(生产默认真实实现;测试替换) ───────────────────────────────────────

def _probe_fn(cmd: str) -> str:
    from main.ist_core.tools.device.run_case import _do_probe
    return _do_probe(cmd)


_FORK_OVERRIDE = None   # 测试注入:fn(skill, brief, tag=…, effort=…) -> str


def _call_fork(executor, skill: str, brief: str, *, tag: str, effort: str = "") -> str:
    if _FORK_OVERRIDE is not None:
        return _FORK_OVERRIDE(skill, brief, tag=tag, effort=effort)
    return executor.call(skill, brief, tag=tag, effort=effort)


def _digest_fn(xlsx_path: str, autoids: list[str]) -> str:
    from main.ist_core.tools.device.batch_tools import dev_run_batch_digest
    return dev_run_batch_digest.func(xlsx_path, autoids)


# --------------------------------------------------------------- [mech] prep
def prep(state: dict) -> dict:
    out_name = str(state.get("out_name") or Path(str(state.get("mindmap_path"))).stem)
    mdir = sh.outputs_root() / out_name
    manifest = mdir / "manifest.json"
    if not manifest.is_file():
        from main.ist_core.tools.device.compile_prep import compile_prep
        res = compile_prep.invoke({"mindmap_path": str(state.get("mindmap_path")),
                                   "out_name": out_name})
        if not manifest.is_file():
            return {"phase_status": "error", "out_name": out_name,
                    "error": f"prep produced no manifest: {str(res)[:200]}"}
    st = {**state, "out_name": out_name,
          "manifest_ref": str(manifest.relative_to(sh.project_root())),
          "facts_ref": str((mdir / "facts.jsonl").relative_to(sh.project_root()))}
    fs = sh.load_facts(st)
    sh.emit(f"prep:{len(sh.manifest(st).get('cases') or [])} 个用例")
    sh.emit_tick(st, "prep", fs)
    return {"phase_status": "ok", **{k: st[k] for k in ("out_name", "manifest_ref", "facts_ref")},
            "vol_seq": int(state.get("vol_seq") or 0), **sh.counts_update(st, fs)}


# --------------------------------------------------- [mech+user] bed_gate
def bed_gate(state: dict) -> dict:
    """床态体检(ctx=(π,B) 的 B 维):版本锚+通道残留+床账。失配/异物 → interrupt。"""
    try:
        from main.case_compiler.config import get_config
        cfg = get_config()
        host = str(getattr(cfg.jumphost, "host", "") or "")
        cfg_build = str(cfg.build or "")
    except Exception:  # noqa: BLE001
        host, cfg_build = "", ""
    rep = B.bed_check(_probe_fn, cfg_build, root=sh.project_root(), host=host)
    device_build = str((rep.get("anchor") or {}).get("device") or "")
    updates = {"bed_host": host, "device_build": device_build}
    sh.append(state, [{"ev": "bed_checked", "aid": "", "host": host,
                       "anchor": rep.get("anchor"), "findings": rep.get("findings"),
                       "run_id": f"bed:{int(time.time())}"}])
    # 初始化清理(2026-07-10 用户裁决:开工必净):有文法清理引用的残留先清后复检;
    # 清不掉/无引用的仍走 ask。R1 12/26 崩盘(¥96)最大嫌疑=两天床残留,此门止损。
    residue = [f for f in (rep.get("findings") or []) if f.get("kind") != "build_anchor"]
    if residue:
        clean = B.bed_cleanup(_probe_fn, residue, root=sh.project_root(), host=host,
                              batch=str(state.get("out_name") or ""))
        sh.append(state, [{"ev": "bed_cleaned", "aid": "", "host": host,
                           "cleaned": clean["cleaned"], "skipped": clean["skipped"],
                           "run_id": f"bedclean:{int(time.time())}"}])
        if clean["cleaned"]:
            sh.emit(f"床态初始化清理:{len(clean['cleaned'])} 项残留已清"
                    + (f",{len(clean['skipped'])} 项无清理引用待问" if clean["skipped"] else "")
                    + " → 复检")
            rep = B.bed_check(_probe_fn, cfg_build, root=sh.project_root(), host=host)
            sh.append(state, [{"ev": "bed_checked", "aid": "", "host": host,
                               "anchor": rep.get("anchor"), "findings": rep.get("findings"),
                               "run_id": f"bed:recheck:{int(time.time())}"}])
    if rep.get("needs_ask"):
        ans = interrupt({"kind": "bed_gate", "report": {
            "anchor": rep.get("anchor"), "findings": rep.get("findings"),
            "ours_unrestored": rep.get("ours_unrestored")}})
        decision = str((ans or {}).get("decision") or "")
        sh.append(state, [{"ev": "decision", "aid": "", "question_id": "bed_gate",
                           "answer": decision}])
        if decision not in ("proceed", "继续"):
            sh.emit(f"床态体检未放行(用户裁决:{decision or '停止'})")
            return {"phase_status": "bed_blocked", **updates}
    sh.emit(f"床态体检通过:build={device_build or '?'} host={host}")
    return {"phase_status": "ok", **updates, **sh.counts_update(state)}


# --------------------------------------------------------------- [llm] author
def author(state: dict) -> dict:
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    pending = [a for a, c in vw["cases"].items()
               if c["status"] in (V.S_PENDING, V.S_FAILED, V.S_CONTRADICTED)]
    # fail/矛盾案只重编 reflow/frozen 处置且未封顶的(归因定向;rerun_isolated/
    # transient 不重编——由 merge 收进待验集直接复跑);矛盾≥2 的不在此处理(ask 边)
    max_rounds = int(state.get("max_rounds") or 3)
    todo: list[str] = []
    for aid in pending:
        mine = [f for f in fs if f.get("aid") == aid]
        if vw["cases"][aid]["status"] in (V.S_FAILED, V.S_CONTRADICTED):
            if F.contradictions(mine, aid) >= 2:
                continue                      # 归 ask_contradiction 边
            att = [f for f in mine if f.get("ev") == "attribution"]
            disp = str(att[-1].get("disposition")) if att else "reflow"
            if disp not in ("reflow", "frozen", "defect_candidate"):
                continue   # rerun_isolated/transient 由 merge 复跑;env_blocked 已终态
            if F.rounds_used(mine, aid) >= max_rounds:
                sh.append(state, [{"ev": "escalated", "aid": aid,
                                   "reason": "max_rounds_exhausted"}])
                sh.signal("escalated", aid, reason="max_rounds_exhausted")
                continue
        todo.append(aid)
    if not todo:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state)}

    sh.emit(f"派发 {len(todo)} 个编写")
    executor, limiter, _ = sh.fork_executor(len(todo))
    t0 = time.time()
    results: dict[str, tuple[str, str]] = {}

    def _one(aid: str) -> None:
        mine = [f for f in fs if f.get("aid") == aid]
        rn = F.rounds_used(mine, aid)
        eff = "max" if rn >= 1 else ""   # 首败即升
        if rn >= 1:   # 重编前存档旧卷(briefs 的 prior_config_rolls 数据源;V6 存档职责迁入)
            try:
                import shutil
                old = sh.outputs_root() / aid / "case.xlsx"
                if old.is_file():
                    hd = sh.outputs_root() / aid / "history"
                    hd.mkdir(exist_ok=True)
                    dst = hd / f"case.r{rn}.xlsx"
                    if not dst.exists():
                        shutil.copyfile(old, dst)
            except Exception:  # noqa: BLE001
                logger.debug("旧卷存档失败 %s", aid, exc_info=True)
        out = _call_fork(executor, "compile-worker", BR.build_brief(aid, state, fs),
                         tag=f"engine:{aid[-6:]}", effort=eff)
        xlsx = sh.outputs_root() / aid / "case.xlsx"
        fresh = xlsx.is_file() and xlsx.stat().st_mtime >= t0 - 1
        m = _TAIL_RE.search(out or "")
        tailv = m.group(1) if m else ""
        if fresh:
            results[aid] = ("authored", "")
        elif tailv == "needs_user_decision" and (sh.outputs_root() / aid / "needs_decision.json").is_file():
            results[aid] = ("needs_decision", "")
        else:
            results[aid] = ("escalated", f"no output (tail={tailv or 'none'})")

    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=max(2, min(8, len(todo)))) as ex:
        list(ex.map(_one, todo))

    new_facts: list[dict] = []
    for aid, (kind, detail) in results.items():
        mine = [f for f in fs if f.get("aid") == aid]
        rnd = F.rounds_used(mine, aid) + 1
        if kind == "authored":
            art = sh.artifact_fingerprint(aid)
            new_facts.append({"ev": "authored", "aid": aid, "round": rnd,
                              "artifact": art})
        elif kind == "needs_decision":
            new_facts.append({"ev": "needs_decision", "aid": aid,
                              "question_id": f"nd:{aid}:{rnd}"})
        else:
            new_facts.append({"ev": "escalated", "aid": aid, "reason": detail[:200]})
    sh.append(state, new_facts)
    fs2 = sh.load_facts(state)
    sh.emit_tick(state, "author", fs2)
    return {"phase_status": "ok", **sh.counts_update(state, fs2)}


# -------------------------------------------------------- [user] ask_decision
def ask_decision(state: dict) -> dict:
    """欠定问询(先问后落代码):needs_decision 事实 → 面板 → decision 事实 + user_decision.json。"""
    fs = sh.load_facts(state)
    pending = [f for f in fs if f.get("ev") == "needs_decision"
               and not any(d.get("ev") == "decision"
                           and d.get("question_id") == f.get("question_id") for d in fs)]
    if not pending:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    from main.ist_core.compile_engine_v8.questions import load_ledgers, build_questions
    aids = [str(f.get("aid")) for f in pending]
    qs = build_questions(load_ledgers(sh.outputs_root(), aids))
    answers: dict[str, str] = {}
    for i in range(0, len(qs), 4):
        if i // 4 >= _MAX_ASK_ROUNDS:
            break
        ans = interrupt({"kind": "ask_decision", "questions": qs[i:i + 4]})
        if isinstance(ans, dict):
            answers.update({str(k): str(v) for k, v in ans.items()})
    new_facts = []
    for f in pending:
        aid = str(f.get("aid"))
        a = answers.get(aid, "")
        if not a:
            continue
        decision = next((d for d in ("改过程", "改预期", "改描述") if d in a), "")
        if not decision:
            continue
        new_facts.append({"ev": "decision", "aid": aid,
                          "question_id": f.get("question_id"), "answer": decision})
        try:  # emit 门的 user_decision 契约(工具层不变;先问后落由本节点次序保证)
            from main.ist_core.tools.device.verifiability_tool import compile_user_decision
            compile_user_decision.func(autoid=aid, decision=decision)
        except Exception:  # noqa: BLE001
            logger.debug("user_decision 落盘失败 %s", aid, exc_info=True)
        sh.signal("user_decided", aid)
    sh.append(state, new_facts)
    fs2 = sh.load_facts(state)
    return {"phase_status": "ok", **sh.counts_update(state, fs2)}


# --------------------------------------------------------------- [mech] merge
def merge(state: dict) -> dict:
    """组卷:确定语境(全部非终态案就绪=delivery,否则 subset)+ 通道①排序 + ④共存检查
    + 卷组成指纹 + merged 事实。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    m = sh.manifest(state)
    ready = [a for a, c in vw["cases"].items()
             if c["status"] in (V.S_AUTHORED, V.S_SUBSET_VERIFIED, V.S_DELIVERABLE,
                                V.S_CONTRADICTED, V.S_FAILED)]
    live = [a for a, c in vw["cases"].items()
            if c["status"] not in (V.S_ESCALATED, V.S_TERMINAL)]
    def _rerun_disposed(aid: str) -> bool:
        att = [f for f in fs if f.get("aid") == aid and f.get("ev") == "attribution"]
        return bool(att) and str(att[-1].get("disposition")) in ("rerun_isolated", "transient")

    need_verify = [a for a in ready
                   if vw["cases"][a]["status"] in (V.S_AUTHORED, V.S_CONTRADICTED)
                   or (vw["cases"][a]["status"] == V.S_FAILED and _rerun_disposed(a))]
    if not ready:
        return {"phase_status": "nothing_to_merge", **sh.counts_update(state, fs)}
    # 语境判定:终验(无待验)或首跑/全量重编(待验=全体)= delivery;增量重编=subset
    # (先子集验证再终验——节流纪律 + 矛盾谓词 pass@subset→fail@delivery 的语义前提)
    if not need_verify:
        comp, is_delivery = ready, True
    elif set(need_verify) == set(live):
        comp, is_delivery = live, True
    else:
        comp, is_delivery = need_verify, False

    # 通道①排序(交付报告须声明)+ 通道④共存检查
    cases_steps = []
    for aid in comp:
        rows = _load_case_rows(aid)
        cases_steps.append({"autoid": aid, "steps": rows})
    ordered, moved = P.order_volume(cases_steps)
    comp_ordered = [c["autoid"] for c in ordered]
    coexist = P.coexist_violations(cases_steps)

    seq = int(state.get("vol_seq") or 0) + 1
    out_name = str(state.get("out_name"))
    vol_name = out_name if is_delivery else f"{out_name}__sub{seq}"
    from main.ist_core.tools.device import compile_emit_merged
    res = compile_emit_merged.invoke({"autoids": comp_ordered, "out_name": vol_name})
    if str(res).startswith("error"):
        return {"phase_status": "error", "error": str(res)[:300],
                **sh.counts_update(state, fs)}
    pairs = [(a, sh.artifact_fingerprint(a)) for a in comp_ordered]
    volume = sh.volume_fingerprint(pairs)
    merged = sh.outputs_root() / vol_name / "case.xlsx"
    sh.append(state, [{"ev": "merged", "aid": "", "volume": volume,
                       "ctx": F.CTX_DELIVERY if is_delivery else F.CTX_SUBSET,
                       "composition": comp_ordered, "moved_tail": moved,
                       "coexist_violations": coexist,
                       "path": str(merged.relative_to(sh.project_root())),
                       "run_id": f"merge:{volume}"}])
    if moved:
        sh.emit(f"持久化家族 {len(moved)} 案排卷尾(交付报告将声明)")
    if coexist:
        sh.emit(f"⚠ 通道④共存违例 {len(coexist)} 组(详情入报告)")
    sh.emit(f"合并[{'整卷' if is_delivery else '子集'}] {len(comp_ordered)} 案 → {vol_name}/case.xlsx")
    return {"phase_status": "ok", "vol_seq": seq,
            "merged_ref": str(merged.relative_to(sh.project_root())),
            "run_ctx": F.CTX_DELIVERY if is_delivery else F.CTX_SUBSET,
            **sh.counts_update(state, fs)}


def _load_case_rows(aid: str) -> list[dict]:
    from main.ist_core.tools.device.precedent_tools import _load_case_rows as _l
    p = sh.outputs_root() / aid / "case.xlsx"
    try:
        return _l(str(p)) if p.is_file() else []
    except Exception:  # noqa: BLE001
        return []


# ----------------------------------------------------------------- [mech] run
def run(state: dict) -> dict:
    merged = sh.project_root() / str(state.get("merged_ref") or "")
    if not merged.is_file():
        return {"phase_status": "error", "error": "merged volume missing"}
    fs = sh.load_facts(state)
    mf = [f for f in fs if f.get("ev") == "merged"]
    comp = list(mf[-1].get("composition") or []) if mf else []
    sh.emit(f"上机[{state.get('run_ctx')}]:{len(comp)} 案 @ {state.get('bed_host')}")
    out = _digest_fn(str(merged), comp)
    if isinstance(out, str) and ("device_busy" in out or "run_in_progress" in out):
        return {"phase_status": "device_busy", **sh.counts_update(state, fs)}
    lr = merged.parent / "last_run.json"
    if not lr.is_file():
        return {"phase_status": "error", "error": "digest produced no last_run"}
    return {"phase_status": "ok",
            "last_run_ref": str(lr.relative_to(sh.project_root())),
            **sh.counts_update(state, fs)}


# ------------------------------------------------------------ [mech] reconcile
def reconcile(state: dict) -> dict:
    """全射对账(oracle 残差公理执行体):last_run → verdict 事实,全部入账+显式结局;
    即时写回(provisional)/终验确认/矛盾回滚。"""
    fs = sh.load_facts(state)
    mf = [f for f in fs if f.get("ev") == "merged"]
    volume = str(mf[-1].get("volume")) if mf else ""
    ctx = str(state.get("run_ctx") or F.CTX_SUBSET)
    lr_ref = str(state.get("last_run_ref") or "")
    data = sh.read_json(sh.project_root() / lr_ref, []) or []
    run_id = f"run:{volume}:{ctx}:{len([f for f in fs if f.get('ev') == 'verdict'])}"
    verdicts = []
    for rec in data:
        aid = str(rec.get("autoid") or "")
        if not aid:
            continue
        verdicts.append({
            "aid": aid, "run_id": f"{run_id}:{aid}", "ctx": ctx,
            "result": "pass" if rec.get("verdict") == "pass" else "fail",
            "artifact": sh.artifact_fingerprint(aid), "volume": volume,
            "signatures": list(rec.get("_fail_signatures") or []),
            "bed": str(state.get("bed_host") or ""),
            "build": str(state.get("device_build") or ""),
            "evidence_ref": lr_ref,
        })
    r = F.reconcile(fs, verdicts)
    sh.append(state, r["append"])
    fs2 = sh.load_facts(state)

    # 结局审计:每条裁决有显式结局(结构保证);写回/回滚随视图变化执行
    wb_facts: list[dict] = []
    for aid in set(r["transition"] + r["confirm"]):
        mine = [f for f in fs2 if f.get("aid") == aid]
        last = F.latest_verdict(mine, aid)
        if not last:
            continue
        if last.get("result") == "pass":
            done = any(f.get("ev") == "writeback" and f.get("voucher_run") == last.get("run_id")
                       for f in fs2)
            if not done:
                _writeback_one(aid, lr_ref)
                wb_facts.append({"ev": "writeback", "aid": aid,
                                 "targets": ["precedent", "footprint"],
                                 "voucher_run": last.get("run_id"),
                                 "provisional": ctx != F.CTX_DELIVERY})
                sh.signal("writeback_done", aid, precedent=True)
        elif ctx == F.CTX_DELIVERY:
            # 终验 fail:若此前有 writeback → 回滚(半毒先例撤销)
            had = [f for f in fs2 if f.get("ev") == "writeback" and f.get("aid") == aid]
            rolled = [f for f in fs2 if f.get("ev") == "rollback" and f.get("aid") == aid]
            if had and len(rolled) < len(had):
                _rollback_one(aid)
                wb_facts.append({"ev": "rollback", "aid": aid, "of": "writeback",
                                 "reason": "contradicted_at_delivery",
                                 "voucher_run": last.get("run_id")})
            had_pass = any(f.get("ev") == "verdict" and f.get("aid") == aid
                           and f.get("result") == "pass" for f in fs2)
            if had_pass:
                sh.signal("final_verify_failed", aid, volume=volume)
    if wb_facts:
        sh.append(state, wb_facts)
    fs3 = sh.load_facts(state)
    vw = sh.view(state, fs3)
    npass = sum(1 for v in verdicts if v["result"] == "pass")
    sh.emit(f"对账:{len(verdicts)} 裁决入流(pass {npass}) → "
            f"{json.dumps(vw['counts'], ensure_ascii=False)}")
    sh.emit_tick(state, "reconcile", fs3)
    return {"phase_status": "ok", **sh.counts_update(state, fs3)}


def _writeback_one(aid: str, lr_ref: str) -> None:
    try:
        from main.ist_core.tools.device.precedent_tools import compile_writeback
        compile_writeback.func(autoid=aid, last_run_path=lr_ref)
    except Exception:  # noqa: BLE001
        logger.debug("先例写回失败 %s", aid, exc_info=True)
    try:
        from main.ist_core.tools.knowledge.footprint_writeback import compile_footprint_writeback
        compile_footprint_writeback.func(
            autoid=aid, provenance_path=f"workspace/outputs/{aid}/case.provenance.json",
            on_device_passed=True)
    except Exception:  # noqa: BLE001
        logger.debug("footprint 写回失败 %s", aid, exc_info=True)
    try:  # 行为知识晋升(V6 writeback 三连的第三件,验收后补齐)
        from main.ist_core.compile_engine_v8.uncertain import _promote_behavior_candidates
        class _NoLed:
            data = {"audit": {"notes": []}}
        _promote_behavior_candidates(aid, _NoLed())
    except Exception:  # noqa: BLE001
        logger.debug("行为晋升失败 %s", aid, exc_info=True)


def _rollback_one(aid: str) -> None:
    """写回回滚(清污脚本机制化):mirror 卷删除 + 意图索引摘键 + footprint 按 device_run 锚摘条。"""
    try:
        from main.ist_core.tools.device import precedent_tools as PT
        fn = f"verified_{aid}.xlsx"
        p = PT._MIRROR / fn
        if p.is_file():
            p.unlink()
        with PT._INTENT_INDEX_LOCK:
            idx = PT._read_intent_index_file()
            if fn in idx:
                idx.pop(fn)
                PT._write_intent_index_atomic(idx)
        PT._INTENT_INDEX_CACHE = None
        PT._MIRROR_CORPUS_CACHE = None
    except Exception:  # noqa: BLE001
        logger.debug("mirror 回滚失败 %s", aid, exc_info=True)
    try:
        from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS
        nodes = Path(KNOWLEDGE_FOOTPRINTS) / "nodes"
        for np in nodes.glob("*.json"):
            d = json.loads(np.read_text(encoding="utf-8"))
            ch = False
            for key in ("behaviors", "decision_rules"):
                arr = d.get(key) or []
                keep = [e for e in arr if str(((e.get("evidence") or {}).get("device_run")
                                               or {}).get("autoid")) != aid]
                if len(keep) != len(arr):
                    d[key] = keep
                    ch = True
            cli = (d.get("cli") or {}).get("commands") or []
            keep = [e for e in cli if str(((e.get("evidence") or {}).get("device_run")
                                           or {}).get("autoid")) != aid]
            if len(keep) != len(cli):
                d["cli"]["commands"] = keep
                ch = True
            if ch:
                np.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("footprint 回滚失败 %s", aid, exc_info=True)


# --------------------------------------------------------------- [llm] attribute
def attribute(state: dict) -> dict:
    """归因(fail/矛盾案):机械预判(digest 已附 ^→G/dev_help)→ fork 填 undetermined
    → attribution 事实(submit_attribution 落盘为证)。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    todo = [a for a, c in vw["cases"].items()
            if c["status"] in (V.S_FAILED, V.S_CONTRADICTED)]
    if not todo:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    lr_ref = str(state.get("last_run_ref") or "")
    data = sh.read_json(sh.project_root() / lr_ref, []) or []
    recs = {str(r.get("autoid")): r for r in data if isinstance(r, dict)}

    executor, limiter, _ = sh.fork_executor(len(todo))
    for aid in todo:
        rec = recs.get(aid, {})
        mine = [f for f in fs if f.get("aid") == aid]
        contra = F.contradictions(mine, aid)
        brief = json.dumps({
            "autoid": aid, "last_run_path": lr_ref,
            "device_build": state.get("device_build", ""),
            "batch_pass_examples": [a for a, c in vw["cases"].items()
                                    if c["status"] in (V.S_DELIVERABLE, V.S_SUBSET_VERIFIED)][:6],
            "contradiction": bool(contra),
        }, ensure_ascii=False) + "\n" + (
            "<device_help>\n" + str(rec.get("_device_help"))[:1500] + "\n</device_help>\n"
            if rec.get("_device_help") else "")
        with limiter:
            _call_fork(executor, "compile-attributor", brief, tag=f"attr:{aid[-6:]}")

    # 收账:submit_attribution 落盘的 _attribution → attribution 事实
    data2 = sh.read_json(sh.project_root() / lr_ref, []) or []
    new_facts = []
    for rec in data2:
        aid = str(rec.get("autoid") or "")
        att = rec.get("_attribution")
        if aid in todo and isinstance(att, dict):
            mine = [f for f in fs if f.get("aid") == aid]
            last = F.latest_verdict(mine, aid)
            new_facts.append({"ev": "attribution", "aid": aid,
                              "round": F.rounds_used(mine, aid),
                              "run_id": (last or {}).get("run_id", ""),
                              "layer": att.get("layer"), "disposition": att.get("disposition"),
                              "fix_direction": str(att.get("fix_direction") or "")[:800],
                              "evidence": str(att.get("evidence") or "")[:500]})
            if att.get("disposition") == "env_blocked":
                sh.signal("escalated", aid, reason="env_blocked")
    sh.append(state, new_facts)
    fs2 = sh.load_facts(state)
    sh.emit_tick(state, "attribute", fs2)
    return {"phase_status": "ok", **sh.counts_update(state, fs2)}


# ---------------------------------------------------- [user] ask_contradiction
def ask_contradiction(state: dict) -> dict:
    """矛盾即问(第三条 ask 边):矛盾≥2 的案,携累计历史问用户;每次矛盾都回到这里。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    targets = [a for a, c in vw["cases"].items()
               if c["status"] == V.S_CONTRADICTED and c["contradictions"] >= 2]
    if not targets:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    payload = []
    for aid in targets:
        mine = [f for f in fs if f.get("aid") == aid]
        prior = [f.get("answer") for f in mine if f.get("ev") == "decision"
                 and str(f.get("question_id", "")).startswith("contra:")]
        payload.append({"autoid": aid,
                        "contradictions": vw["cases"][aid]["contradictions"],
                        "prior_choices": prior})
    ans = interrupt({"kind": "ask_contradiction", "cases": payload})
    new_facts = []
    for aid in targets:
        a = str((ans or {}).get(aid) or (ans or {}).get("decision") or "")
        if not a:
            continue
        n = vw["cases"][aid]["contradictions"]
        new_facts.append({"ev": "decision", "aid": aid,
                          "question_id": f"contra:{aid}:{n}", "answer": a})
        if a in ("接受单跑", "accept_subset", "降级", "downgrade"):
            new_facts.append({"ev": "attribution", "aid": aid, "round": 99,
                              "layer": "E", "disposition": "env_blocked",
                              "fix_direction": f"user decision: {a}", "evidence": "user"})
        sh.signal("user_decided", aid, kind="contradiction")
    sh.append(state, new_facts)
    fs2 = sh.load_facts(state)
    return {"phase_status": "ok", **sh.counts_update(state, fs2)}


# --------------------------------------------------------------- [mech] closing
def closing(state: dict) -> dict:
    """收口:uncertain 观察入库(自愈环)+报告(视图即真相)+子集卷清理+床账收尾。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    out_name = str(state.get("out_name"))
    mdir = sh.outputs_root() / out_name
    # 自愈环:fail 终态/升级案观察 uncertain 入库(复用 V6 已验收的入库器)
    try:
        from main.ist_core.compile_engine_v8.uncertain import _ingest_uncertain_observations

        class _Led:  # 适配器:入库器只用 in_state
            def in_state(self, *states):
                want = set()
                if "failed_terminal" in states:
                    want.add(V.S_TERMINAL)
                if "escalated" in states:
                    want.add(V.S_ESCALATED)
                return [a for a, c in vw["cases"].items() if c["status"] in want]
            data = {"audit": {"notes": []}}
        _ingest_uncertain_observations(_Led())
    except Exception:  # noqa: BLE001
        logger.debug("uncertain 入库失败", exc_info=True)

    deliverable = [a for a, c in vw["cases"].items() if c["status"] == V.S_DELIVERABLE]
    others = {a: c for a, c in vw["cases"].items() if c["status"] != V.S_DELIVERABLE}
    mf = [f for f in fs if f.get("ev") == "merged"]
    moved = list(mf[-1].get("moved_tail") or []) if mf else []
    coexist = list(mf[-1].get("coexist_violations") or []) if mf else []
    report = {
        "engine": "v8",
        "outcome": ("delivered_all_pass" if not others else "delivered_with_labels"),
        "totals": {"cases": len(vw["cases"]), "deliverable": len(deliverable),
                   **vw["counts"]},
        "volume": vw.get("volume"),
        "moved_tail": moved, "coexist_violations": coexist,
        "bed": {"host": state.get("bed_host"), "device_build": state.get("device_build")},
        "cases": vw["cases"],
        "refs": {"facts": state.get("facts_ref"), "merged": state.get("merged_ref")},
    }
    (mdir / "engine_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _delivery_md(mdir, report)
    # 子集卷清理(交付物之外的运行中间目录)
    import shutil
    for d in sh.outputs_root().glob(f"{out_name}__sub*"):
        shutil.rmtree(d, ignore_errors=True)
    sh.emit(f"交付:{len(deliverable)}/{len(vw['cases'])} 可交付"
            + (f",{len(others)} 案带标注" if others else ""))
    sh.emit_tick(state, "closing", fs)
    return {"phase_status": "done", **sh.counts_update(state, fs)}


def _delivery_md(mdir: Path, report: dict) -> None:
    lines = [f"# 交付报告 — {mdir.name}(V8)",
             f"> 结果 **{report['outcome']}** · 可交付 {report['totals']['deliverable']}"
             f"/{report['totals']['cases']} · volume={report.get('volume')}",
             ""]
    if report.get("moved_tail"):
        lines.append(f"- 持久化家族排卷尾(通道①声明):{', '.join(report['moved_tail'])}")
    if report.get("coexist_violations"):
        lines.append(f"- ⚠ 通道④共存违例:{json.dumps(report['coexist_violations'], ensure_ascii=False)[:400]}")
    bad = {a: c for a, c in report["cases"].items() if c["status"] != "deliverable"}
    if bad:
        lines.append("\n## 需人工处置")
        for a, c in sorted(bad.items()):
            lines.append(f"- …{a[-6:]} `{c['status']}` 轮次{c['rounds']} 矛盾{c['contradictions']}")
    (mdir / "delivery_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
