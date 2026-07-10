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


def _exec_fn(cmd: str) -> str:
    """配置模式执行(床态清理专用;clear 族在 show 通道被设备拒,2026-07-10 实证)。"""
    from main.ist_core.tools.device.run_case import _do_probe
    return _do_probe(cmd, mode="config")


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
    # 批次锚:每次图从 START 重入记一条(seq 单调;interrupt-resume 不经此处)。
    # 挂起案的「新批恢复问询」以「最后 suspended 之后有 run_start」为触发——
    # 同批内挂起后不再打扰,同参数重跑才问一次恢复。
    sh.append(st, [{"ev": "run_start", "aid": "",
                    "seq": sum(1 for f in fs if f.get("ev") == "run_start") + 1}])
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
    clean: dict = {"cleaned": [], "failed": [], "skipped": []}
    if residue:
        clean = B.bed_cleanup(_exec_fn, residue, root=sh.project_root(), host=host,
                              batch=str(state.get("out_name") or ""))
        sh.append(state, [{"ev": "bed_cleaned", "aid": "", "host": host,
                           "cleaned": clean["cleaned"], "failed": clean.get("failed", []),
                           "skipped": clean["skipped"],
                           "run_id": f"bedclean:{int(time.time())}"}])
        sh.emit("床态初始化清理:"
                + f"清成 {len(clean['cleaned'])} 项"
                + (f",失败 {len(clean.get('failed', []))} 项" if clean.get("failed") else "")
                + (f",无清理引用 {len(clean['skipped'])} 项" if clean["skipped"] else "")
                + " → 复检")
        if clean["cleaned"]:
            rep = B.bed_check(_probe_fn, cfg_build, root=sh.project_root(), host=host)
            sh.append(state, [{"ev": "bed_checked", "aid": "", "host": host,
                               "anchor": rep.get("anchor"), "findings": rep.get("findings"),
                               "run_id": f"bed:recheck:{int(time.time())}"}])
    if rep.get("needs_ask"):
        ans = interrupt({"kind": "bed_gate", "report": {
            "anchor": rep.get("anchor"), "findings": rep.get("findings"),
            "cleanup": {"cleaned": [c.get("kind") for c in clean["cleaned"]],
                        "failed": [c.get("kind") for c in clean.get("failed", [])],
                        "skipped": clean["skipped"]},
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
    panel_wait = set(sh.panel_waiting(fs, vw))
    todo: list[str] = []
    for aid in pending:
        if aid in panel_wait:
            continue   # ought-欠定呈报未获答案:重编等用户确认(路由先经 ask 边,此为保险)
        mine = [f for f in fs if f.get("aid") == aid]
        if vw["cases"][aid]["status"] in (V.S_FAILED, V.S_CONTRADICTED):
            if F.contradictions(mine, aid) >= 2:
                continue                      # 归 ask_contradiction 边
            att = [f for f in mine if f.get("ev") == "attribution"]
            disp = str(att[-1].get("disposition")) if att else "reflow"
            if disp not in ("reflow", "frozen", "defect_candidate"):
                continue   # rerun_isolated/transient 由 merge 复跑;env_blocked 走确认问询
            # 轮次封顶 ≠ 终态(§11.7 三权分立:资源权归用户):记 cap_reached 进资源问询,
            # 用户授权(granted_rounds)后封顶上移继续;引擎无单方终结权
            if F.rounds_used(mine, aid) >= max_rounds + sh.granted_rounds(fs, aid):
                sh.append(state, [{"ev": "cap_reached", "aid": aid,
                                   "round": F.rounds_used(mine, aid)}])
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
    comp = set(mf[-1].get("composition") or []) if mf else set()
    ctx = str(state.get("run_ctx") or F.CTX_SUBSET)
    lr_ref = str(state.get("last_run_ref") or "")
    data = sh.read_json(sh.project_root() / lr_ref, []) or []
    run_id = f"run:{volume}:{ctx}:{len([f for f in fs if f.get('ev') == 'verdict'])}"
    verdicts = []
    for rec in data:
        aid = str(rec.get("autoid") or "")
        if not aid:
            continue
        if comp and aid not in comp:
            # last_run.json 按 autoid 跨轮 merge——卷外案的陈腐记录不得入本卷裁决
            # (语境锚:2026-07-10 第5轮实证,终态案 655173 的上轮记录被记成终验卷裁决)
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


_ADJ_QUOTE_RE = re.compile(
    r"- \[(?:device|device_context|causality|detail_tail|framework_traceback)[^\]]*\] 『(.*?)』",
    re.DOTALL)


def _try_adopt(panel: dict, device_corpus: str) -> dict | None:
    """机械采信(§11.11 构件五;run5 漂移数据裁定不交孔):同键判例命中 ∧ 命中间
    无互斥 ∧ 实机行为仍与判例记载匹配(判例 device 引文是本轮回显子串;比不出=
    按未知→不采,进 ask)→ 返回判例;任一不满足 → None。"""
    try:
        from main.ist_core.tools.knowledge.adjudication_store import find_adjudications
        hits = find_adjudications(
            intent_signature=str(panel.get("intent_signature") or ""),
            conflict_shape=str(panel.get("conflict_shape") or ""),
            version_family=str(panel.get("version_family") or ""))
    except Exception:  # noqa: BLE001
        logger.debug("adjudication lookup failed", exc_info=True)
        return None
    if not hits:
        return None
    tokens = {str(h.get("token") or "") for h in hits}
    if len(tokens) > 1 or next(iter(tokens)) not in ("confirm", "correct"):
        return None   # 互斥或不可复用的裁决形态(defect/stop 不跨批采信)
    h = hits[0]
    from main.ist_core.tools.device.ask_panel import _norm
    dev_quotes = _ADJ_QUOTE_RE.findall(str(h.get("body") or ""))
    if not dev_quotes or not device_corpus:
        return None   # 判例无实机记载可比 → 未知 → ask
    corpus_n = _norm(device_corpus)
    if not all(_norm(q) in corpus_n for q in dev_quotes):
        return None   # 设备行为已与判例时不同 → 判例不背书,重新呈报
    return h


# --------------------------------------------------------------- [llm] attribute
def attribute(state: dict) -> dict:
    """归因(fail/矛盾案):机械预判(digest 已附 ^→G/dev_help)→ fork 填 undetermined
    → attribution 事实(submit_attribution 落盘为证)。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    todo = []
    for aid, c in vw["cases"].items():
        if c["status"] not in (V.S_FAILED, V.S_CONTRADICTED):
            continue
        mine = [f for f in fs if f.get("aid") == aid]
        last = F.latest_verdict(mine, aid)
        if last and any(f.get("ev") == "attribution"
                        and f.get("run_id") == last.get("run_id") for f in mine):
            continue   # 该 fail 裁决已归因过(每裁决一次;防 env 确认等待期反复烧孔)
        todo.append(aid)
    if not todo:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    lr_ref = str(state.get("last_run_ref") or "")
    data = sh.read_json(sh.project_root() / lr_ref, []) or []
    recs = {str(r.get("autoid")): r for r in data if isinstance(r, dict)}

    t0 = time.time()   # panel 收割新鲜度基线:早于本轮派发的 ask_panel.json 是陈旧遗留
    executor, limiter, _ = sh.fork_executor(len(todo))
    for aid in todo:
        rec = recs.get(aid, {})
        mine = [f for f in fs if f.get("aid") == aid]
        contra = F.contradictions(mine, aid)
        env = {
            "autoid": aid, "last_run_path": lr_ref,
            "device_build": state.get("device_build", ""),
            "batch_pass_examples": [a for a, c in vw["cases"].items()
                                    if c["status"] in (V.S_DELIVERABLE, V.S_SUBSET_VERIFIED)][:6],
            "contradiction": bool(contra),
        }
        # 已答 panel 裁决随 brief 下发:同一差异用户已裁,不再重复呈报(§2.6 收敛律
        # 的批内面;跨批由 B 片判例检索承接)
        pf = [f for f in mine if f.get("ev") == "ask_panel"]
        if pf:
            prnd = int(pf[-1].get("round") or 0)
            dec = next((d for d in reversed(mine) if d.get("ev") == "decision"
                        and str(d.get("question_id")) == f"panel:{aid}:{prnd}"), None)
            if dec:
                env["prior_adjudication"] = {
                    "shape": str(pf[-1].get("shape") or ""),
                    "answer": str(dec.get("answer") or "")[:300],
                    "token": str(dec.get("token") or ""),
                    "note": "already adjudicated by the user — do not re-file the same discrepancy"}
        brief = json.dumps(env, ensure_ascii=False) + "\n" + (
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
    # 收账:submit_ask_panel 落盘的呈报面板 → ask_panel 事实(§11.11 构件四;
    # 按引用流:facts 只记形态+盘上路径,面板全文渲染时现读)。
    # 收割即尝试机械采信(构件五):同键判例背书且实机行为未变 → adopted 事实,
    # 该 panel 不进 ask 边(收敛律:同键至多问一次);adopted 永不写回判例库(A5)。
    for aid in todo:
        pp = sh.outputs_root() / aid / "ask_panel.json"
        if not pp.is_file():
            continue
        panel = sh.read_json(pp, {}) or {}
        if float(panel.get("ts") or 0) < t0 - 1:
            continue   # 上一轮遗留(用户可能已答过);只收本轮孔新产的
        mine = [f for f in fs if f.get("aid") == aid]
        rnd = F.rounds_used(mine, aid)
        already = any(f.get("ev") == "ask_panel" and str(f.get("aid")) == aid
                      and int(f.get("round") or 0) == rnd for f in fs)
        if already:
            continue
        new_facts.append({"ev": "ask_panel", "aid": aid, "round": rnd,
                          "shape": str(panel.get("conflict_shape") or ""),
                          "intent_signature": str(panel.get("intent_signature") or ""),
                          "ref": str(pp.relative_to(sh.project_root()))})
        rec = recs.get(aid, {})
        corpus = "\n".join(str(rec.get(k) or "") for k in
                           ("device_context", "causality", "detail_tail",
                            "framework_traceback"))
        adj = _try_adopt(panel, corpus)
        if adj:
            new_facts.append({"ev": "adopted", "aid": aid, "round": rnd,
                              "slug": str(adj.get("slug") or ""),
                              "token": str(adj.get("token") or ""),
                              "ruling": str(adj.get("body") or "")[:400]})
            sh.emit(f"…{aid[-6:]} 同键判例背书,免问采用({adj.get('slug')})")
    sh.append(state, new_facts)
    fs2 = sh.load_facts(state)
    sh.emit_tick(state, "attribute", fs2)
    return {"phase_status": "ok", **sh.counts_update(state, fs2)}


# ---------------------------------------------------- [user] ask_contradiction
def _case_story(mine: list[dict]) -> str:
    """极简人话时间线(A 片内联版;C 片渲染层落地后由其接管)。"""
    ctx_cn = {"delivery": "整卷复验", "subset": "单独验证"}
    out = []
    for f in mine:
        if f.get("ev") == "authored":
            out.append(f"第{int(f.get('round') or 0)}次编写")
        elif f.get("ev") == "verdict":
            out.append(f"{ctx_cn.get(str(f.get('ctx')), f.get('ctx'))}"
                       f"{'通过' if f.get('result') == 'pass' else '未通过'}")
    return "→".join(out[-8:])


def _case_diag(mine: list[dict]) -> str:
    atts = [f for f in mine if f.get("ev") == "attribution"]
    if not atts:
        return ""
    a = atts[-1]
    note = str(a.get("user_note") or "").strip()
    return note or str(a.get("fix_direction") or "")[:160]


def _latest_panel(mine: list[dict], aid: str) -> tuple[dict, int]:
    """最新 ask_panel 事实的(盘上面板全文, round);无则 ({}, -1)。"""
    pf = [f for f in mine if f.get("ev") == "ask_panel"]
    if not pf:
        return {}, -1
    last = pf[-1]
    panel = sh.read_json(sh.project_root() / str(last.get("ref") or ""), {}) or {}
    return panel, int(last.get("round") or 0)


def _answer_token(kind: str, a: str) -> str:
    """用户答案 → 小写决策 token(机械映射;挂起/停止是跨题面常驻特权)。
    自由输入(Other)按题面语义归并:panel→correct(纠正反馈)、cap→continue(带
    反馈继续)、env→retry、contra→reorder、suspended→keep(不明确不动)。
    特权词只在短指令里生效(≤8 字):长句里的「挂起/停止」多为叙述
    (「不要挂起,按手册来」),按题面默认走、原文全程保留在 decision 里。"""
    short = len(a) <= 8
    if kind == "suspended":
        # 先于特权判定:「保持挂起」是本题面的常规选项,不是特权触发
        if "恢复" in a:
            return "resume"
        return "stop" if ("停止" in a and short) else "keep"
    if "挂起" in a and (short or a.startswith("挂起")):
        return "suspend"
    if "停止" in a and (short or a.startswith("停止")):
        return "stop"
    if kind == "panel":
        if "缺陷" in a:
            return "defect"
        if "确认" in a or "按此" in a:
            return "confirm"
        return "correct"
    if kind == "cap":
        return "continue"
    if kind == "env":
        return "stop" if "确认环境" in a else "retry"
    if kind == "contra":
        if "降级" in a or "接受单跑" in a:
            return "downgrade"
        return "reorder"
    return "correct"


def ask_contradiction(state: dict) -> dict:
    """用户问询边终形(§11.11 构件六):目标 = 未答 ask_panel ∪ cap 二分 ∪ contra≥2
    ∪ env 待确认 ∪ 挂起案新批恢复。题面渲染自 panel(差异呈报+已检索+理解 Z);
    决策存小写 token(confirm|correct|defect|…);挂起/停止=常驻特权(自由输入兜底,
    不占选项);未获答案(非交互/面板取消)→ 自动挂起带可行动反馈,永不空转。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    t = sh.ask_targets(state, fs, vw)
    cap_set = set(t["cap"])
    # 优先序 panel>contra>cap>env>suspended;panel∩cap 合并一题(cap 语境附注)
    ordered = ([(a, "panel") for a in t["panel"]] + [(a, "contra") for a in t["contra"]]
               + [(a, "cap") for a in t["cap"]] + [(a, "env") for a in t["env"]]
               + [(a, "suspended") for a in t["suspended"]])
    seen: set = set()
    targets = [(a, k) for a, k in ordered if not (a in seen or seen.add(a))]
    if not targets:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    m = sh.manifest(state)
    titles = {str(c.get("autoid")): str(c.get("title") or "") for c in (m.get("cases") or [])}
    payload = []
    qids: dict[str, str] = {}
    for aid, kind in targets:
        mine = [f for f in fs if f.get("aid") == aid]
        item = {"autoid": aid, "kind": kind,
                "title": titles.get(aid, ""),
                "rounds": vw["cases"][aid]["rounds"],
                "contradictions": vw["cases"][aid]["contradictions"],
                "timeline": _case_story(mine),
                "diagnosis": _case_diag(mine)[:300],
                "prior_choices": [f.get("answer") for f in mine if f.get("ev") == "decision"]}
        if kind == "panel":
            panel, prnd = _latest_panel(mine, aid)
            item["panel"] = {k: panel.get(k) for k in
                             ("conflict_shape", "sides", "retrieval_receipt",
                              "hypothesis", "ask", "intent_signature")}
            item["cap_reached"] = aid in cap_set
            qids[aid] = f"panel:{aid}:{prnd}"
        elif kind == "cap":
            atts = [f for f in mine if f.get("ev") == "attribution"]
            item["evidence"] = str((atts[-1] if atts else {}).get("fix_direction") or "")[:300]
            qids[aid] = f"cap:{aid}:{vw['cases'][aid]['rounds']}"
        elif kind == "env":
            atts = [f for f in mine if f.get("ev") == "attribution"]
            item["evidence"] = str((atts[-1] if atts else {}).get("evidence") or "")[:300]
            qids[aid] = f"env:{aid}:{int((atts[-1] if atts else {}).get('round') or 0)}"
        elif kind == "suspended":
            n_runs = sum(1 for f in fs if f.get("ev") == "run_start")
            qids[aid] = f"resume:{aid}:{n_runs}"
        else:
            qids[aid] = f"contra:{aid}:{vw['cases'][aid]['contradictions']}"
        payload.append(item)
    ans = interrupt({"kind": "ask_contradiction", "cases": payload})
    new_facts = []
    for item in payload:
        aid, kind, qid = item["autoid"], item["kind"], qids[item["autoid"]]
        mine = [f for f in fs if f.get("aid") == aid]
        a = str((ans or {}).get(aid) or "")
        if not a:
            # 安全件(§11.11):未获答案不悬置不空转——自动挂起,报告给出恢复路径;
            # 本就挂起的案保持原状(不落重复事实)
            if kind != "suspended":
                new_facts.append({"ev": "decision", "aid": aid, "question_id": qid,
                                  "answer": "", "token": "suspend",
                                  "note": "auto-suspended: no answer (non-interactive or panel cancelled)"})
                new_facts.append({"ev": "suspended", "aid": aid, "reason": f"auto:{qid}"})
                sh.emit(f"…{aid[-6:]} 未获答案,自动挂起(重跑同参数会再次呈报)")
            continue
        tok = _answer_token(kind, a)
        new_facts.append({"ev": "decision", "aid": aid, "question_id": qid,
                          "answer": a, "token": tok})
        if tok == "suspend":
            new_facts.append({"ev": "suspended", "aid": aid, "reason": qid})
        elif tok in ("stop", "downgrade"):
            # 止损=用户显式裁决(evidence=user → 终态;不符交付预期,记未通过卷)
            new_facts.append({"ev": "attribution", "aid": aid, "round": 99,
                              "layer": "E", "disposition": "env_blocked",
                              "fix_direction": f"user decision: {a}", "evidence": "user"})
        elif tok == "defect":
            # 用户确认产品缺陷=唯一合法非 excel 结果(§11.7 telos);走缺陷候选单
            new_facts.append({"ev": "attribution", "aid": aid, "round": 99,
                              "layer": "product_defect", "disposition": "defect_candidate",
                              "fix_direction": f"user confirmed product defect: {a}",
                              "evidence": "user"})
        elif tok == "retry":
            # 用户不接受环境阻塞判断 → 开隔离复跑处方(用户来源,merge 收进待验集)
            new_facts.append({"ev": "attribution", "aid": aid,
                              "round": F.rounds_used(mine, aid),
                              "run_id": f"user:env_retry:{qid}",
                              "layer": "E", "disposition": "rerun_isolated",
                              "fix_direction": f"user overrode env_blocked: {a}",
                              "evidence": "user"})
        elif tok == "resume":
            new_facts.append({"ev": "resumed", "aid": aid, "of": qid})
        elif tok == "keep":
            new_facts.append({"ev": "suspended", "aid": aid, "reason": f"keep:{qid}"})
        # confirm/correct:decision(含用户原文)即全部所需——briefs 把 panel 理解 Z
        # 与用户答案注入重编 brief;cap 的 continue 经 granted_rounds 上移封顶;
        # contra 的 reorder 回既有复验环。
        # 收敛律写回(§2.6 (20);A5 人源专属:唯一写入口,拿到用户 decision 才走):
        # panel 的 confirm/correct → knowledge/adjudications/,下批同键免问(采信面)。
        if kind == "panel" and tok in ("confirm", "correct"):
            try:
                from main.ist_core.tools.knowledge.adjudication_store import write_adjudication
                panel_full, _ = _latest_panel(mine, aid)
                ruling = (a if tok == "correct"
                          else f"{panel_full.get('hypothesis', '')}\n(用户确认:{a})")
                write_adjudication(
                    key={k: panel_full.get(k) for k in
                         ("intent_signature", "conflict_shape", "version_family")},
                    ruling=ruling,
                    anchor={"version": str(state.get("device_build") or ""),
                            "lineage": "user_proxy"},
                    sides=panel_full.get("sides") or [],
                    meta={"autoid": aid, "batch": str(state.get("out_name") or ""),
                          "token": tok})
            except Exception:  # noqa: BLE001
                logger.warning("判例写回失败(问询流不受影响)%s", aid, exc_info=True)
        sh.signal("user_decided", aid, kind=kind)
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
