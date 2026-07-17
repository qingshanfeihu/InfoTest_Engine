"""V8 节点(十个;类型见 state.NODE_TYPES)。真理=事实流,节点=事实的搬运工。

依赖注入(测试面):run/probe/fork 经模块级 hook(_digest_fn/_probe_fn/_fork_fn)可替——
生产默认绑定真实工具;yzg 场景包用假设备回放。
"""

from __future__ import annotations

import functools
import json
import logging
import os
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
# ask 面板语义单一事实源在 questions.py;import-as 绑定模块属性,
# test_ask_panel/test_tau 直调 `N._answer_token` 路径依赖此别名
from main.ist_core.compile_engine_v8.questions import answer_token as _answer_token

logger = logging.getLogger(__name__)

_TAIL_RE = re.compile(r"^STATUS:\s*(produced|needs_user_decision|failed)", re.MULTILINE)
# G4 echo-back 的 token 人话表(user-facing 中文;引擎动作词表的展示映射,非新枚举)
_TOKEN_CN = {"confirm": "按呈报理解继续", "correct": "按你的纠正重编", "defect": "确认产品缺陷",
             "continue": "追加轮次继续", "suspend": "挂起", "stop": "停止该案",
             "retry": "复跑验证", "resume": "恢复处理", "keep": "保持挂起",
             "reorder": "重排复验", "downgrade": "如实降级(不入交付卷)",
             "reflow_tau": "重编并补案尾清理"}
_MAX_ASK_ROUNDS = 8      # ask 分批上限(每批 ≤4 题;面板硬限)


# ── 注入点(生产默认真实实现;测试替换) ───────────────────────────────────────

def _probe_fn(cmd: str) -> str:
    # bed 残留探针专用:annotate=False 取**原始设备事实**——dev_probe 对空回显附的时机语义
    # note 是给 worker 的便利提示、非床内容,注进来会被 bed_check 误当"分区配置残留"
    # (回归#3 yzg 实证;修法A 分离关注点:worker 拿带 note 的,bed 拿原始的)。
    from main.ist_core.tools.device.run_case import _do_probe
    return _do_probe(cmd, annotate=False)


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


def _jh_exec_fn(cmd: str) -> str:
    """跳板机 shell(mirror 锚对账用;15s 超时,失败返回 error: 前缀)。"""
    try:
        import os
        import paramiko
        from main.case_compiler.config import get_config
        cfg = get_config()
        host = str(getattr(cfg.jumphost, "host", "") or "")
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(host, username=getattr(cfg.jumphost, "user", None) or "test",
                  password=getattr(cfg.jumphost, "password", None)
                  or os.environ.get("IST_JUMPHOST_PASS", ""), timeout=15)
        try:
            _i, o, _e = c.exec_command(cmd, timeout=20)
            return o.read().decode("utf-8", "replace")
        finally:
            c.close()
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def _bed_llm_fn(system_prompt: str, user_prompt: str) -> str:
    """床态恢复命令生成的轻 LLM 直调(flash 档,单次 completion,思考关——数据变换级
    微调用,与 fork 孔区分;kms_classifier/dream 同类先例)。测试经模块 hook 替换。
    思考关走 extra_body.thinking 按族注入(裸 thinking kwarg 会被转 model_kwargs
    以字面字段进请求体——回归审查 R-4 抓获,不赌端点容忍)。"""
    from main.ist_core.agents._llm import build_explore_model, ist_core_flash_model
    from main.common.llm_helpers import thinking_param_for_model
    param = thinking_param_for_model(ist_core_flash_model(), False)
    kw = {"extra_body": {"thinking": param}} if param is not None else {}
    m = build_explore_model(**kw)
    # lc_agent_name 打标(P1-2):本调用经 contextvar 继承主 run 的 callbacks——不打标会
    # 被 _MainAgentProgressHandler 判成主 agent 事件(reasoning 驱动主相位「思考中」、
    # usage 灌主 token 计数、文本冒充主 agent 发言)。打标后走 parent_subagent 通道
    # (graph._subagent_tags):不进主 transcript、usage 不发 usage_only;Langfuse 观测保留。
    out = m.invoke([("system", system_prompt), ("human", user_prompt)],
                   config={"metadata": {"lc_agent_name": "engine-bed"}})
    return str(getattr(out, "content", out) or "")


# --------------------------------------------------------------- [mech] prep
def prep(state: dict) -> dict:
    out_name = str(state.get("out_name") or Path(str(state.get("mindmap_path"))).stem)
    mdir = sh.outputs_root() / out_name
    manifest = mdir / "manifest.json"
    if not manifest.is_file():
        from main.ist_core.tools.device.compile_prep import compile_prep
        # .func 直调(引擎直调工具纪律;P1-2:.invoke 走 LangChain 通道,callbacks 经
        # contextvar 传播会把本调用以「主 agent 工具行」形态刷进 TUI 主 transcript)
        res = compile_prep.func(mindmap_path=str(state.get("mindmap_path")),
                                out_name=out_name)
        if not manifest.is_file():
            return {"phase_status": "error", "out_name": out_name,
                    "error": f"prep produced no manifest: {str(res)[:200]}"}
    st = {**state, "out_name": out_name,
          "manifest_ref": str(manifest.relative_to(sh.project_root())),
          "facts_ref": str((mdir / "facts.jsonl").relative_to(sh.project_root()))}
    # §11.9 续跑还原:上批 closing 把 per-case 目录收进 delivered/(通过)与
    # unfinished/(未决),新批开工全部挪回原路径——panel ref/旧卷 history/凭证/
    # 通过案 xlsx(挂起恢复后终验重组全卷要用)的读路径全部恢复;不还原=断链。
    import shutil
    restored = 0
    for sub in ("unfinished", "delivered"):
        box = mdir / sub
        if not box.is_dir():
            continue
        for src in sorted(box.iterdir()):
            if not src.is_dir():
                continue
            dst = sh.outputs_root() / src.name
            if dst.exists():
                continue   # 原路径已有新产物(不覆盖,新的为准)
            try:
                shutil.move(str(src), str(dst))
                restored += 1
            except Exception:  # noqa: BLE001
                logger.debug("%s 还原失败 %s", sub, src.name, exc_info=True)
        try:
            box.rmdir()   # 空了才删得掉
        except OSError:
            pass
    if restored:
        sh.emit(f"续跑还原:{restored} 个案目录从存档取回")
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
    # 床账接力(X11/(26):账内己方未复原 → 恢复,零问询;INV-9 既定授权)。
    # 有命令账项=上批已验证记录,机械回放(R4-G3 本义);无命令账项=上批生成失败的
    # 残余,LLM 现生成+实体门(判断开放,门闭合)——失败则留账,由 bed_check 残留
    # 判定自然进问询(合法 ask:尝试已穷尽)
    stuck_ledger: list[dict] = []
    _so_channels = B.snapshot_only_channels()
    try:
        for item in B.bed_unrestored(sh.project_root(), host):
            pl = item.get("payload") or {}
            cmds = list(pl.get("commands") or [])
            # 无预存命令、需现生成时:基线面(snapshot_only)纯 added 无 removed 的账项=
            # 截断嫌疑假漂移(run18 前的历史账),不生成删除命令,只留账不动手(与
            # restorable_diff 同判据);有预存 commands 的(已验证)照常回放
            if (not cmds and str(item.get("kind")) in _so_channels
                    and pl.get("added") and not pl.get("removed")):
                sh.emit(f"床账接力:跳过基线面纯新增账项(不自动删接口地址),"
                        f"{item.get('kind')}:{item.get('id')} 留账")
                continue
            if not cmds and (pl.get("added") or pl.get("removed")):
                d = {str(item.get("kind")): {"added": pl.get("added") or [],
                                             "removed": pl.get("removed") or []}}
                cmds, _rej = B.entity_gate(B.restore_via_llm(d, _bed_llm_fn), d)
            ok = bool(cmds) and all(not B._probe_failed(_exec_fn(c)) for c in cmds)
            if ok:
                B.bed_record(sh.project_root(), host, "restored",
                             str(item.get("kind")), str(item.get("id")),
                             batch=str(state.get("out_name") or ""),
                             payload={"commands": cmds})
                sh.emit(f"床账接力:上批未复原产物已恢复({item.get('kind')}:{item.get('id')})")
            else:
                # 尝试穷尽(生成失败/执行被拒)→进呈报——interface 类漂移不在
                # bed_check 残留判定内,静默留账=账永不清也永不问(回归审查 R-9)
                stuck_ledger.append({"kind": str(item.get("kind")),
                                     "id": str(item.get("id")),
                                     "probe_failed": False, "ledger_stuck": True,
                                     "detail": json.dumps(pl, ensure_ascii=False)[:300]})
                sh.emit(f"床账接力:恢复未成({item.get('kind')}:{item.get('id')}),进问询")
    except Exception:  # noqa: BLE001
        logger.debug("床账接力失败", exc_info=True)

    rep = B.bed_check(_probe_fn, cfg_build, root=sh.project_root(), host=host)
    # mirror 同步锚(§18.3,公式审计 D 级最危险项):恒真门/found 语义门/τ 责任集
    # 全族从盘上 mirror 推导——与真机框架失配=整族门前提静默失效。mismatch=呈报;
    # unknown(SSH 抖动/远端无文件)=告警+入 findings 不拦批(锚未验证入账可见)
    try:
        from main.ist_core.compile_engine_v8 import mirror_anchor as MA
        _sync = MA.check_sync(_jh_exec_fn)
        if _sync.get("status") == "mismatch":
            rep["needs_ask"] = True
            rep["findings"] = list(rep.get("findings") or []) + [{
                "kind": "mirror_sync", "probe_failed": False,
                "detail": ("盘上框架镜像与真机框架不一致(文件:"
                           + ", ".join(_sync.get("diffs") or []) + ")——恒真断言门/"
                           "窗口语义门/τ 责任集的推导前提失效,请确认框架是否升级"
                           "并更新镜像")}]
            sh.emit("⚠ mirror 同步锚失配:" + ", ".join(_sync.get("diffs") or []))
        elif _sync.get("status") == "unknown":
            sh.emit(f"mirror 锚未验证({str(_sync.get('reason'))[:60]})——门前提本轮未对账")
    except Exception:  # noqa: BLE001
        logger.warning("mirror 锚对账异常", exc_info=True)
        sh.emit("mirror 锚对账异常——门前提本轮未验证(详见日志)")
    if stuck_ledger:
        rep["findings"] = list(rep.get("findings") or []) + stuck_ledger
        rep["needs_ask"] = True
    # 上批床态收敛失败(bed_closure_failed,INV-11 式② 坑#12)=床离场态未知——
    # 本批体检即使探针干净也要向用户呈报一次(残留可能在探针投影集外)
    _fs_boot = sh.load_facts(state)
    _closure_fails = [f for f in _fs_boot if f.get("ev") == "bed_closure_failed"
                      and not any(g.get("ev") == "decision"
                                  and str(g.get("question_id")) == f"bedclosure:{f.get('run_id') or ''}"
                                  for g in _fs_boot)]
    if _closure_fails:
        rep["findings"] = list(rep.get("findings") or []) + [{
            "kind": "bed_closure_failed", "probe_failed": False,
            "detail": "上批批后床态收敛中途失败,床离场状态未知(残留可能在探针投影集之外)"}]
        rep["needs_ask"] = True
    device_build = str((rep.get("anchor") or {}).get("device") or "")
    updates = {"bed_host": host, "device_build": device_build}
    # 批前床态快照(X11:批后 diff 的基线;观测不解析意图)
    try:
        snap = B.bed_snapshot(_probe_fn)
        mdir = sh.outputs_root() / str(state.get("out_name") or "")
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "bed_before.json").write_text(
            json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("批前快照失败", exc_info=True)
    sh.append(state, [{"ev": "bed_checked", "aid": "", "host": host,
                       "anchor": rep.get("anchor"), "findings": rep.get("findings"),
                       "run_id": f"bed:{int(time.time())}"}])
    # 初始化清理(2026-07-10 用户裁决:开工必净):有文法清理引用的残留先清后复检;
    # 清不掉/无引用的仍走 ask。R1 12/26 崩盘(¥96)最大嫌疑=两天床残留,此门止损。
    # probe_failed 项不进清理(床态未知,没有清理对象;题面单独如实呈报)
    # maintenance_explained(C1):维护写是合法床基线——决不能被清理引用误清
    # mirror_sync/bed_closure_failed 是引擎内部发现、ledger_stuck 接力已试穷——
    # 都不是设备残留,进清理只会虚占"引擎不认识"计数(2026-07-13 题面取证)
    residue = [f for f in (rep.get("findings") or [])
               if f.get("kind") not in ("build_anchor", "mirror_sync",
                                        "bed_closure_failed")
               and not f.get("probe_failed") and not f.get("ledger_stuck")
               and not f.get("maintenance_explained")]
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
def _stamp_intent(aid: str, state: dict) -> None:
    """派发前把 manifest 意图原文盖章到 outputs/<aid>/intent.json(引擎侧,数据按引用)。

    P1c 意图变体门的证据源修正(2026-07-14 run20 实弹):expected_save_variant 此前仅由
    worker 自我申报——漂移的 worker 恰恰不会申报,668030 把 write all 静默换成 write
    memory,门 no-op 放行、与 668000 撞题;若非床污染挡下将交付假覆盖并写回投毒先例。
    盖章文件只放原文(title/step_intents),保存族推导在消费端(emit 闭集词表)——
    产者不解释、消费者不转述,两侧都无发挥空间。"""
    try:
        m = sh.manifest(state)
        c = next((x for x in (m.get("cases") or [])
                  if str(x.get("autoid")) == aid), None)
        if not isinstance(c, dict):
            return
        d = sh.outputs_root() / aid
        d.mkdir(parents=True, exist_ok=True)
        payload = {"autoid": aid, "title": str(c.get("title") or ""),
                   "step_intents": c.get("step_intents") or [],
                   "group_path": c.get("group_path") or [],
                   "source": "manifest", "stamped_by": "engine.author"}
        # F6 意图侧禁令机制扫描(§18.11;A 层强制点):意图原文命中文法词表(重启/断电/
        # 恢复出厂族)即 stamp 标记——brief 据此下发要点先行指令,emit 硬门以
        # user_decision.json 存在为放行凭据(先问后落)。误报=一次可廉价放行的呈报。
        try:
            from main.case_compiler.domain_grammar import forbidden_mechanism_intents
            text = " ".join([payload["title"]]
                            + [f"{si.get('desc') or ''} {si.get('expected') or ''}"
                               for si in payload["step_intents"] if isinstance(si, dict)]).lower()
            hits = [{"family": fam, "matched": pat}
                    for fam, pats in forbidden_mechanism_intents()
                    for pat in pats if re.search(pat, text)]
            if hits:
                payload["forbidden_mechanism"] = hits[:3]
        except Exception:  # noqa: BLE001
            logger.debug("禁令机制意图扫描失败(不拦盖章)", exc_info=True)
        (d / "intent.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("intent 盖章失败 %s", aid, exc_info=True)


def author(state: dict) -> dict:
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    pending = [a for a, c in vw["cases"].items()
               if c["status"] in (V.S_PENDING, V.S_FAILED, V.S_CONTRADICTED,
                                   V.S_BROKEN_ERRORED)]   # §④:Errored 子类走 reflow 重写
    # fail/矛盾案只重编 reflow/frozen 处置且未封顶的(归因定向;rerun_isolated/
    # transient 不重编——由 merge 收进待验集直接复跑);矛盾≥2 的不在此处理(ask 边)
    max_rounds = int(state.get("max_rounds") or 3)
    panel_wait = set(sh.panel_waiting(fs, vw))
    todo: list[str] = []
    for aid in pending:
        if aid in panel_wait:
            continue   # ought-欠定呈报未获答案:重编等用户确认(路由先经 ask 边,此为保险)
        mine = [f for f in fs if f.get("aid") == aid]
        if vw["cases"][aid]["status"] in (V.S_FAILED, V.S_CONTRADICTED,
                                          V.S_BROKEN_ERRORED):
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
        _stamp_intent(aid, state)        # 意图盖章(P1c 证据源,worker 不可影响)
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
        elif tailv == "needs_user_decision":
            # worker 声称欠定但台账缺失(run18 实证 655173):A 层不许散文冒充结构化
            # 事实(先问后落),故仍升级——但 reason 必须说真话。真因两类:①worker 没走
            # compile_check_verifiability(该工具判定欠定时自落台账)②**本类欠定无落账
            # 通道**——worker md 声明「意图的验证路径在本床不存在」也是欠定,而该工具
            # 入参只表达分布类断言可验性(algo/n_requests/n_pools),承载不了它(设计
            # 缺口,DESIGN §19.5 登记)。呈报保留 worker 原文供人判读。
            results[aid] = ("escalated",
                            f"worker declared underdetermined but no needs_decision.json ledger "
                            f"(no landing channel for this claim kind, or the falsify tool was "
                            f"not called); worker said: {(out or '').strip()[-400:]}")
        else:
            results[aid] = ("escalated", f"no output from fork (tail={tailv or 'none'}); "
                                         f"fork may have hit the wallclock watchdog — a late "
                                         f"artifact, if any, is reclaimed at merge")
        # P1-1(TUI 实弹:fanout 11min+ footer 停「准备」零进度):每 fork 结算发一次
        # tick——相位/时间戳随结算刷新(counts 仍是 fanout 前快照,收账后节点尾 tick 归真)
        sh.emit_tick(state, "author", fs)

    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=_fanout_pool_size(len(todo))) as ex:
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
    ledgers = load_ledgers(sh.outputs_root(), aids)
    _qid_by_aid = {str(f.get("aid")): f.get("question_id") for f in pending}
    version = str(state.get("product_version") or "")
    new_facts: list[dict] = []

    def _fm_meta(aid: str) -> dict | None:
        """欠定题的折叠/采信键(§18.13 P1 re-key)。三元组题(有 test_point)按
        (group_path, has_equivalent) 折叠——不再 key on claim_kind==forbidden_mechanism
        (真实路径 claim_kind=verification_path_absent,旧键致 reboot 案永不折叠=run22
        病理);旧禁令台账保留兼容。group_path 读 intent.json 盖章(缺→不折叠,各自一题)。"""
        nd = ledgers.get(aid) or {}
        claims = [c for c in (nd.get("claims") or []) if isinstance(c, dict)]
        if not claims:
            return None
        is_triple = all(c.get("test_point") for c in claims)
        is_fm = all(str(c.get("claim_kind")) == "forbidden_mechanism" for c in claims)
        if not (is_triple or is_fm):
            return None
        it = sh.read_json(sh.outputs_root() / aid / "intent.json", {}) or {}
        gp = tuple(str(x) for x in (it.get("group_path") or []))
        leaf = gp[-1] if gp else str(it.get("title") or aid)[:40]
        if is_triple:
            has_eq = all(c.get("equivalent") for c in claims)
            return {"group": gp or (aid,),
                    "sig": (leaf + "|" + ("eq" if has_eq else "noeq")).lower()}
        fams = sorted({str(h.get("family") or "")
                       for h in (it.get("forbidden_mechanism") or []) if isinstance(h, dict)})
        return {"group": gp or (aid,), "sig": (leaf + "|" + "+".join(fams)).lower()}

    def _land(aid: str, decision: str, answer_text: str, provenance: str = "",
              form: str = "") -> bool:
        """user_decision 落盘+decision 事实(改描述另落 suspended)。INV-11 式②:先落盘
        后落账,失败=本案本轮不落 decision(留在 needs_decision 下轮重问),如实告警。
        H1:答案原文随 note 落盘——机制类裁决(等价实现文本/用户自给方案)语义都在
        原文里,user_decision.json 是 worker brief 的既有引用点。§18.14 D1:形态类 claim
        (distribution/position)的改过程/改预期须带 assertion_form(从 q['_form'] 派生),
        否则 compile_user_decision 的 form 门拒落→活锁;机制类免 form 由工具侧判。"""
        try:
            from main.ist_core.tools.device.verifiability_tool import compile_user_decision
            out = compile_user_decision.func(autoid=aid, decision=decision, note=answer_text,
                                             assertion_form=form)
            if str(out).startswith("error"):
                raise RuntimeError(str(out)[:200])
        except Exception:  # noqa: BLE001
            logger.warning("user_decision 落盘失败 %s——decision 不落账,下轮重问",
                           aid, exc_info=True)
            sh.emit(f"⚠ …{aid[-6:]} 裁决落盘失败,本轮不生效(下轮会重新询问)")
            return False
        rec = {"ev": "decision", "aid": aid, "question_id": _qid_by_aid.get(aid),
               "answer": decision}
        if provenance:
            rec["provenance"] = provenance
        new_facts.append(rec)
        if decision == "改描述":
            # 改描述=本轮不产出——落 suspended 进挂起态(非终态,跨批恢复通道既有);
            # 不落则案回 S_PENDING 被无限重派(V8.5 片2 实测堵洞)
            new_facts.append({"ev": "suspended", "aid": aid,
                              "reason": "user_decision:改描述",
                              "question_id": _qid_by_aid.get(aid)})
        sh.signal("user_decided", aid)
        return True

    # ── F6 同键采信豁免(§18.11,评审 T12;(20) 收敛律在本 ask 类的兑现):既有裁决
    # 键=(意图签名×forbidden_mechanism×版本族)精确命中 ∧ token 唯一(互斥→照常问,
    # (45)/(21) 合成规则:人源记载互斥时不静态判赢)→ 机械采信免问。编译期无回显,
    # 不用 B 片的回显子串条件——键精确匹配即采信变体。
    fm_meta = {aid: _fm_meta(aid) for aid in aids}
    adopted: set[str] = set()
    for aid in aids:
        m = fm_meta.get(aid)
        if not m:
            continue
        try:
            from main.ist_core.tools.knowledge.adjudication_store import find_adjudications
            hits = find_adjudications(intent_signature=m["sig"],
                                      conflict_shape="forbidden_mechanism",
                                      version_family=version)
        except Exception:  # noqa: BLE001
            hits = []
        toks = {str(h.get("token") or "") for h in hits}
        if len(toks) == 1 and next(iter(toks)) in ("改过程", "改预期", "改描述"):
            tok = next(iter(toks))
            ruling = str(hits[0].get("ruling") or hits[0].get("body") or "")[:500]
            if _land(aid, tok, ruling or tok,
                     provenance=f"adopted:{hits[0].get('slug', '')}"):
                new_facts.append({"ev": "adopted", "aid": aid, "round": 0,
                                  "slug": str(hits[0].get("slug") or ""),
                                  "token": tok, "ruling": ruling})
                adopted.add(aid)
                sh.emit(f"…{aid[-6:]} 同键禁令机制判例命中,免问采用")

    # ── F8c 组一题折叠(§18.11;共因合题机构的编写期前移):同(组,签名)的
    # forbidden_mechanism 案取代表提问,答案扇出、逐案落盘(emit 门按案读)。
    fold: dict[str, list[str]] = {}
    _rep_of: dict[tuple, str] = {}
    for aid in aids:
        if aid in adopted:
            continue
        m = fm_meta.get(aid)
        key = (m["group"], m["sig"]) if m else ("solo", aid)
        rep = _rep_of.setdefault(key, aid)
        fold.setdefault(rep, []).append(aid)

    qs = build_questions({aid: ledgers[aid] for aid in sorted(fold) if aid in ledgers})
    # P3:三元组题的 label→token 显式映射(长 label「采纳「…」」不含"改过程",
    # substring 兜底匹配不到——run22 会掉 Other 兜底致 re-ask)。
    _tok_by_rep = {str(q.get("_autoid")): (q.get("_token_by_label") or {}) for q in qs}
    # §18.14 D1:形态类 claim(distribution/position)的改过程/改预期须带 assertion_form
    # (=q['_form'],FORM_BY_KIND 派生∈dist/member/captured_relation);机制类免 form
    # 由工具侧判,传空无害。缺此→compile_user_decision form 门拒落→活锁。
    _form_by_rep = {str(q.get("_autoid")): str(q.get("_form") or "") for q in qs}
    for q in qs:
        mem = fold.get(str(q.get("_autoid")), [])
        if len(mem) > 1:
            tails = "、".join(a[-6:] for a in mem)
            # 折叠后缀机械确定(§18.13 P4:不引入 LLM 组稿——广播的是决策 token,
            # 每案 fanout 按各自台账 equivalent 重编,代表案的等价只作示例;机械后缀
            # 确定性+永不空,天然满足 P4 的 resume 一致与非空要求,无需 memoize/fallback)。
            q["question"] = (str(q.get("question", ""))
                             + f"(本题代表同组 {len(mem)} 案:尾号 {tails}——采纳即认可各案"
                             "各自的等价方案,答案广播全组、逐案落盘)")
            q["header"] = f"欠定·组{len(mem)}案"
    # 题面入账(run11 体检#6:问了什么必须入账;oracle 残差 (16) 对称应用到问询侧)。
    # 折叠组:每成员一条 ask_shown,非代表标 folded_into(账目完整,答案可回放归属)
    shown: list[dict] = []
    for q in qs:
        rep = str(q.get("_autoid", ""))
        for member in fold.get(rep, [rep]):
            rec = {"ev": "ask_shown", "aid": member,
                   "question_id": _qid_by_aid.get(member, ""),
                   "question": str(q.get("question", ""))[:300],
                   "options": [o.get("label") for o in q.get("options", [])],
                   "gather": True}
            if member != rep:
                rec["folded_into"] = rep
            shown.append(rec)
    if shown:
        sh.append(state, shown)
    answers: dict[str, str] = {}
    for i in range(0, len(qs), 4):
        if i // 4 >= _MAX_ASK_ROUNDS:
            break
        ans = interrupt({"kind": "ask_decision", "questions": qs[i:i + 4]})
        if isinstance(ans, dict):
            answers.update({str(k): str(v) for k, v in ans.items()})
    for rep in sorted(fold):
        a = answers.get(rep, "")
        if not a:
            continue
        m = fm_meta.get(rep)
        tbl = _tok_by_rep.get(rep) or {}
        # P3:三元组题先按显式 label→token 映射(label 与 answer 互为子串即命中,
        # 容 TUI 序号/换行加工);失败再走既有 substring 兜底。
        decision = next((t for lbl, t in tbl.items() if lbl and (lbl in a or a in lbl)), "")
        if not decision:
            decision = next((d for d in ("改过程", "改预期", "改描述") if d in a), "")
        if not decision and (m or tbl):
            # kind-aware Other 兜底(评审 D9;三元组同理):自由文本=用户自给等价方案,
            # 语义即「按此改过程」,原文随 note 直达 worker。其他类维持保守(重问)。
            decision = "改过程"
        if not decision:
            continue
        landed_members = [aid for aid in fold[rep]
                          if _land(aid, decision, a, form=_form_by_rep.get(rep, ""))]
        if m and landed_members and version:
            # 判例写回(同键采信的供给侧;anchor=应然锚 A2,lineage=用户代理)
            try:
                from main.ist_core.tools.knowledge.adjudication_store import write_adjudication
                write_adjudication(
                    key={"intent_signature": m["sig"],
                         "conflict_shape": "forbidden_mechanism",
                         "version_family": version},
                    ruling=a, anchor={"version": version, "lineage": "user_proxy"},
                    meta={"autoid": rep, "token": decision,
                          "batch": str(state.get("out_name") or "")})
            except Exception:  # noqa: BLE001
                logger.debug("禁令机制判例写回失败(不拦裁决生效)", exc_info=True)
    sh.append(state, new_facts)
    fs2 = sh.load_facts(state)
    return {"phase_status": "ok", **sh.counts_update(state, fs2)}


def _user_retry_after_s0(fs: list[dict], aid: str) -> bool:
    """用户 retry 裁决(床已处理/不认可,复跑)是否晚于该案最新 h_s0 诊断。

    (36) 写权律的执行体(run12 实弹修复):用户对床状态的声明权威高于机械诊断——
    subset 复跑 fail 后 diagnose 会重新判 h_s0(当时判得对),但其后用户答 retry
    即为对「床现已治理」的新声明;停车位/复跑闸若仍按旧诊断挡,用户复跑指令被
    静默吞(run12 实测:8 案 retry 后零复跑直接收口)。按 fold 哲学改派生逻辑,
    历史事实流在新代码下自动解释正确(续跑即生效,无需补事实)。"""
    diag_idx = max((i for i, f in enumerate(fs)
                    if f.get("ev") == "diagnosis" and str(f.get("aid")) == aid
                    and str(f.get("h_position", "")).startswith("h_s0")), default=-1)
    if diag_idx < 0:
        return False
    # retry 或 resumed(run15 实弹修:用户恢复挂起案=对「该案应继续」的声明,
    # 与 retry 同权威——resume 后被停车位静默挡死曾致零复跑直接收口)
    return any(i > diag_idx for i, f in enumerate(fs)
               if (f.get("ev") == "decision" and str(f.get("aid")) == aid
                   and str(f.get("token")) == "retry")
               or (f.get("ev") == "resumed" and str(f.get("aid")) == aid))


def _reclaim_late_artifacts(state: dict, fs: list[dict]) -> list[dict]:
    """迟到产出回收(run18 实弹):fork 墙钟超时 ≠ worker 无产出。

    看门狗超时只是**引擎放弃等待**——fork 线程在 Python 里杀不掉,worker 继续跑完
    并落盘。run18 实录:655233 派发后 600s 墙钟超时判 escalated("no output"),
    worker 在 935s 时 compile_emit 成功,合格卷+lint 凭证静静躺在盘上,案却已被
    标成 escalated 永不再看——烧掉 15 分钟与整案 token,产出被丢弃。

    回收判据全部机械:xlsx 在 ∧ lint 凭证在且签名匹配当前卷面(emit 全门已过的
    物理证据)∧ 产出晚于本批开工——满足即落 authored 事实(escalated 语义随之
    解除:视图按「最后 escalated 之后有无 authored」判,与 suspended/resumed 同型)。
    不满足的 escalated 案原样保留(真·无产出仍升级人工)。"""
    esc = [a for a, c in sh.view(state, fs)["cases"].items()
           if c["status"] == V.S_ESCALATED]
    if not esc:
        return []
    # 本批开工锚:最近一次 run_start 的时刻(facts 无 ts 字段时回落 0=不卡时间)
    out: list[dict] = []
    for aid in esc:
        try:
            xlsx = sh.outputs_root() / aid / "case.xlsx"
            if not xlsx.is_file():
                continue
            art = sh.artifact_fingerprint(aid)   # 凭证内的 xlsx_mtime 签名(无凭证=空)
            if not art:
                continue                          # 无 lint 凭证:未过 emit 门,不收
            mine = [f for f in fs if str(f.get("aid")) == aid]
            if any(f.get("ev") == "authored" and str(f.get("artifact")) == art
                   for f in mine):
                continue                          # 该卷面已入账,不重复
            rnd = F.rounds_used(mine, aid) + 1
            out.append({"ev": "authored", "aid": aid, "round": rnd, "artifact": art,
                        "note": "late artifact reclaimed after fork wallclock timeout"})
            sh.emit(f"迟到产出回收:…{aid[-6:]} 超时后 worker 仍产出合格卷(凭证有效),收回本卷")
        except Exception:  # noqa: BLE001
            logger.debug("迟到产出回收失败 %s", aid, exc_info=True)
    return out


def _delivery_verify_skippable(vw: dict, comp: list[str], volume: str,
                               fs: list[dict]) -> bool:
    """终验幂等闸(纯判定,DESIGN §16.4 片3-④):同卷组成指纹的 delivery 裁决已在
    事实流=零信息重跑,跳过(无此闸 s₀ 停车案会驱动兄弟案无限重复终验,实测 livelock)。
    两个不可吸收例外(重跑有信息):待升格案(subset_verified 须拿 delivery-pass)/
    组成内有 broken 三态案(那次终验是断批快照,重跑非零信息——否则真通过案被断批
    marker 钉死到 delivery_incomplete,zhaiyq 实证,详见设计锚)。"""
    st = {a: vw["cases"][a]["status"] for a in comp}
    if any(s == V.S_SUBSET_VERIFIED for s in st.values()):
        return False
    if any(s in (V.S_BROKEN, V.S_BROKEN_ERRORED, V.S_BROKEN_BLOCKED)
           for s in st.values()):
        return False
    return any(f.get("ev") == "verdict" and f.get("ctx") == F.CTX_DELIVERY
               and str(f.get("volume")) == volume for f in fs)


# --------------------------------------------------------------- [mech] merge
def merge(state: dict) -> dict:
    """组卷:确定语境(全部非终态案就绪=delivery,否则 subset)+ 通道①排序 + ④共存检查
    + 卷组成指纹 + merged 事实。开工先回收 fork 超时后迟到落盘的合格卷(run18)。"""
    fs = sh.load_facts(state)
    _late = _reclaim_late_artifacts(state, fs)
    if _late:
        sh.append(state, _late)
        fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    m = sh.manifest(state)

    def _s0_parked(aid: str) -> bool:
        """s₀ 停车位(V8.5 片3):复跑处方 ∧ 批级诊断判床态残留——复跑不可救、重编
        无对象(卷面没错),入卷只会无限重跑同一失败(实测 livelock)。停在未通过卷,
        叙事说清「床治理后下批续跑」;L3 落地后此位自动清空。
        用户 retry 晚于最新 h_s0 诊断 → 不停车((36) 写权律,run12 实弹修复)。"""
        att = [f for f in fs if f.get("aid") == aid and f.get("ev") == "attribution"]
        if not (att and str(att[-1].get("disposition")) in ("rerun_isolated", "transient")):
            return False
        if _user_retry_after_s0(fs, aid):
            return False
        diag = [f for f in fs if f.get("aid") == aid and f.get("ev") == "diagnosis"]
        if not (diag and str(diag[-1].get("h_position", "")).startswith("h_s0")):
            return False
        # 床锚(run15 实弹修):s₀ 是床状态属性——诊断锚定的床≠当前床(换床)时
        # 诊断失效不停车;旧账无 bed 字段=保守视为同床(停车照旧)
        d_bed = str(diag[-1].get("bed") or "")
        cur_bed = str(state.get("bed_host") or "")
        if d_bed and cur_bed and d_bed != cur_bed:
            return False
        return True

    # F1(§18.11):expectation_suspect 案带 ask_panel 在等人源裁决——与 author 的
    # panel_wait 排除对称,不得被 merge 当「就绪案」误纳进 delivery 卷(它 case_status
    # 仍是 S_FAILED,但唯一出口是面板,非复跑/交付)。裁决折叠既有 token 后正常流恢复。
    panel_wait = set(sh.panel_waiting(fs, vw))
    ready = [a for a, c in vw["cases"].items()
             if c["status"] in (V.S_AUTHORED, V.S_SUBSET_VERIFIED, V.S_DELIVERABLE,
                                V.S_CONTRADICTED, V.S_FAILED, V.S_BROKEN)
             and a not in panel_wait
             and not (c["status"] in (V.S_FAILED, V.S_CONTRADICTED) and _s0_parked(a))]
    # V8.5 片2:挂起/待决案不得扣押其余案的 delivery 语境(§14-R4)——它们无卷可入,
    # 留在 live 里会让「待验=全体」永不成立、终验被结构性扣押。复活后经新 merge 换
    # 卷组成指纹,composition 锚自动强制整卷重新终验(INV-8 不破,答题→子集重跑→终验)。
    live = [a for a, c in vw["cases"].items()
            if c["status"] not in (V.S_ESCALATED, V.S_TERMINAL,
                                   V.S_AWAITING_USER, V.S_SUSPENDED)
            and a not in panel_wait]
    def _rerun_disposed(aid: str) -> bool:
        att = [f for f in fs if f.get("aid") == aid and f.get("ev") == "attribution"]
        if not (att and str(att[-1].get("disposition")) in ("rerun_isolated", "transient")):
            return False
        # V8.5 片3 复跑闸:批级诊断判 s₀(床态残留)的案,隔离复跑不可救——
        # 复跑=h 重采样只救 π 噪声;s₀ 的 h 冻结在脏床上(run11 668030 实证:
        # 重排复验×3 全部再翻挂)。s₀ 案不进复跑集,走排尾/床治理/矛盾呈报。
        # 例外(run12 实弹修复,(36) 写权律:用户裁决权威>机械闸):最新 h_s0 诊断
        # **之后**用户答过 retry(床已处理/不认可,复跑)→ 放行——用户对床状态的
        # 声明覆盖机械诊断;否决它=用户复跑指令被闸静默吞(run12 实测 8 案零复跑收口)。
        if _user_retry_after_s0(fs, aid):
            return True
        diag = [f for f in fs if f.get("aid") == aid and f.get("ev") == "diagnosis"]
        if diag and str(diag[-1].get("h_position", "")).startswith("h_s0"):
            d_bed = str(diag[-1].get("bed") or "")
            cur_bed = str(state.get("bed_host") or "")
            if not (d_bed and cur_bed and d_bed != cur_bed):
                return False   # 同床(或旧账无锚):s₀ 复跑不可救照旧挡
        return True

    need_verify = [a for a in ready
                   if vw["cases"][a]["status"] in (V.S_AUTHORED, V.S_CONTRADICTED,
                                                   V.S_BROKEN)
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

    # 合并预检单案化(#74-②,run13 二次实证):凭证过期/lint 违例的案落 emit_invalid
    # 事实打回重编(fold:最新 authored 之后的 emit_invalid → 回待编写),其余照常
    # 合并——单案违例不再拖死全批(曾 error→closing,26 案零上机收口)。被踢案
    # 重编后经新 merge 换组成指纹,INV-8 自动强制重新终验。
    from main.ist_core.tools.device.emit_xlsx_tool import precheck_merge_case
    comp = list(comp)
    _invalid: dict[str, str] = {}
    for a in list(comp):
        try:
            reason = precheck_merge_case(a)
        except Exception as e:  # noqa: BLE001
            # INV-11 式②(坑#11):预检自身异常=该案 emit_invalid,不杀全批——
            # 防「单案杀批」的门不得在上一层复活同型坑
            logger.warning("合并预检异常 %s", a, exc_info=True)
            reason = f"precheck_error: {e}"[:200]
        if reason:
            _invalid[a] = reason
            comp.remove(a)
    if _invalid:
        sh.append(state, [{"ev": "emit_invalid", "aid": a, "reason": r[:300],
                           "artifact": vw["cases"][a]["artifact"]}
                          for a, r in _invalid.items()])
        fs = sh.load_facts(state)
        sh.emit(f"合并预检:{len(_invalid)} 案卷面未过门"
                f"({'; '.join(f'…{a[-6:]} {r[:40]}' for a, r in list(_invalid.items())[:3])})"
                f"——已踢出本卷打回重编,{len(comp)} 案照常合并")
        if not comp:
            return {"phase_status": "nothing_to_merge", **sh.counts_update(state, fs)}

    # 通道①排序(交付报告须声明)+ 通道④共存检查
    cases_steps = []
    for aid in comp:
        rows = _load_case_rows(aid)
        cases_steps.append({"autoid": aid, "steps": rows})
    ordered, moved = P.order_volume(cases_steps)
    comp_ordered = [c["autoid"] for c in ordered]
    coexist = P.coexist_violations(cases_steps)

    pairs = [(a, sh.artifact_fingerprint(a)) for a in comp_ordered]
    volume = sh.volume_fingerprint(pairs)
    if is_delivery and _delivery_verify_skippable(vw, comp_ordered, volume, fs):
        return {"phase_status": "nothing_to_merge", **sh.counts_update(state, fs)}

    seq = int(state.get("vol_seq") or 0) + 1
    out_name = str(state.get("out_name"))
    vol_name = out_name if is_delivery else f"{out_name}__sub{seq}"
    from main.ist_core.tools.device import compile_emit_merged
    # .func 直调(同 prep 处 P1-2:防 LangChain 通道把合并冒充成主 agent 工具行)
    res = compile_emit_merged.func(autoids=comp_ordered, out_name=vol_name)
    if str(res).startswith("error"):
        return {"phase_status": "error", "error": str(res)[:300],
                **sh.counts_update(state, fs)}
    merged = sh.outputs_root() / vol_name / "case.xlsx"
    # run_id 带 seq:同 volume 重合并防内容幂等键跨轮误去重(DESIGN §16.4 片3-⑤;
    # seq 来自 state——崩溃重放同 seq 仍去重,真新合并不误并)。
    sh.append(state, [{"ev": "merged", "aid": "", "volume": volume,
                       "ctx": F.CTX_DELIVERY if is_delivery else F.CTX_SUBSET,
                       "composition": comp_ordered, "moved_tail": moved,
                       "coexist_violations": coexist,
                       "path": str(merged.relative_to(sh.project_root())),
                       "run_id": f"merge:{volume}:{seq}"}])
    if moved:
        sh.emit(f"持久化家族 {len(moved)} 案排卷尾(交付报告将声明)")
    if coexist:
        sh.emit(f"⚠ 通道④共存违例 {len(coexist)} 组(详情入报告)")
    try:  # F8d 兄弟碰撞呈报(§18.11;D5 型不硬拒,详情入事实流/报告)
        _coll = _sibling_collisions(state, comp_ordered)
        if _coll:
            sh.append(state, _coll)
            sh.emit(f"⚠ 同组变体撞题嫌疑 {len(_coll)} 起(尾号 "
                    + "、".join(str(c.get('aid'))[-6:] for c in _coll[:4]) + ")")
    except Exception:  # noqa: BLE001
        logger.debug("兄弟碰撞扫描失败(呈报级,不拦合并)", exc_info=True)
    sh.emit(f"合并[{'整卷' if is_delivery else '子集'}] {len(comp_ordered)} 案 → {vol_name}/case.xlsx")
    return {"phase_status": "ok", "vol_seq": seq,
            "merged_ref": str(merged.relative_to(sh.project_root())),
            "run_ctx": F.CTX_DELIVERY if is_delivery else F.CTX_SUBSET,
            **sh.counts_update(state, fs)}


def _sibling_collisions(state: dict, comp: list[str]) -> list[dict]:
    """F8d 兄弟碰撞呈报(§18.11;评审 T14 附:D5 型呈报不硬拒)。

    同组两案卷面**保存变体**相同=撞题嫌疑(668030 漂移≡668000 型)。P1c 已按案硬拦
    「意图 vs 卷面」漂移,本扫描兜的是意图本身撞车/非引擎路径卷;保存族之外的变体轴
    无机械数据不扫(组变体轴非机制轴的组会假阳——硬拒姿势仅保存族闭集已证成)。"""
    from main.ist_core.tools.device.emit_xlsx_tool import _save_family
    m = sh.manifest(state)
    by_group: dict[tuple, list[str]] = {}
    for c in (m.get("cases") or []):
        a = str(c.get("autoid"))
        if a in comp:
            by_group.setdefault(tuple(c.get("group_path") or ()), []).append(a)
    out: list[dict] = []
    for gp, members in by_group.items():
        if not gp or len(members) < 2:
            continue
        owner: dict[str, str] = {}
        for a in sorted(members):
            fam = next((f for f in (_save_family(str(r.get("G") or ""))
                                    for r in _load_case_rows(a)) if f), "")
            if not fam:
                continue
            if fam in owner and owner[fam] != a:
                out.append({"ev": "sibling_collision", "aid": a,
                            "with": owner[fam], "axis": f"write {fam}",
                            "group": "/".join(gp)})
            else:
                owner[fam] = a
    return out


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
    # P1-7:语境词用户面翻译,对齐 merge 侧「合并[整卷/子集]」(run_ctx 原值是英文枚举)
    _ctx_cn = "整卷" if str(state.get("run_ctx")) == F.CTX_DELIVERY else "子集"
    sh.emit(f"上机[{_ctx_cn}]:{len(comp)} 案 @ {state.get('bed_host')}")
    out = _digest_fn(str(merged), comp)
    if isinstance(out, str) and ("device_busy" in out or "run_in_progress" in out
                                 or "stale_run_on_device" in out):
        # stale 残留=「床被占」非「引擎错」,归 busy 走上机互斥处置(DESIGN §4 run 失败语义②)
        return {"phase_status": "device_busy", **sh.counts_update(state, fs)}
    lr = merged.parent / "last_run.json"
    if not lr.is_file():
        # 失败必须带 digest 原话(DESIGN §4 run 失败语义①:诊断依赖一手证据,不带=盲修)
        head = str(out)[:300] if out is not None else "(digest returned None)"
        sh.emit(f"⚠ 上机未产出结果——digest 返回:{head}")
        return {"phase_status": "error",
                "error": f"digest produced no last_run; digest said: {head}"}
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
    # INV-11 式①(坑#3):输入解析失败=error 硬停,禁 default-空——read_json 的
    # fail-open 曾使 last_run 损坏/半写等价于整轮裁决静默蒸发,「吞裁决不可能」
    # 的声称被输入端击穿
    lr_path = sh.project_root() / lr_ref
    try:
        data = json.loads(lr_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"last_run not a list: {type(data).__name__}")
    except Exception as e:  # noqa: BLE001
        return {"phase_status": "error",
                "error": f"last_run unreadable ({lr_ref}): {e}"[:300],
                **sh.counts_update(state, fs)}
    # INV-2 残差门(坑#2,真实计算——此前仅结构论证无执行体):本卷组成内每个 autoid
    # 必须在本轮 last_run 有记录(digest 对未执行案也产 unknown 兜底记录,正常恒满射);
    # 缺失=采集断裂/裁决蒸发,error 硬停不是 warning
    seen_aids = {str(r.get("autoid")) for r in data if isinstance(r, dict)}
    unconsumed = sorted(a for a in comp if a not in seen_aids)
    if unconsumed:
        return {"phase_status": "error",
                "error": ("verdict_unconsumed non-empty (INV-2): "
                          + ", ".join(a[-6:] for a in unconsumed[:8]))[:300],
                **sh.counts_update(state, fs)}
    run_id = f"run:{volume}:{ctx}:{len([f for f in fs if f.get('ev') == 'verdict'])}"
    # (43)(44) 三值透传(坑#1):digest 的 unknown(stale/级联/未执行)=not_run——案没
    # 跑成,结论无效,禁折叠成 fail(假签名→误 frozen→假归因;审计三路共振第一洞)
    _RESULT_MAP = {"pass": "pass", "fail": "fail", "broken": "broken"}
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
            "result": _RESULT_MAP.get(str(rec.get("verdict")), "not_run"),
            "artifact": sh.artifact_fingerprint(aid), "volume": volume,
            "signatures": list(rec.get("_fail_signatures") or []),
            # pyATS 七码子分类透传(§④):digest(batch_tools)按协议级硬事实打的
            # broken_subtype(errored/blocked;未打=None→视图落 S_BROKEN 复跑,安全默认)
            "broken_subtype": rec.get("broken_subtype"),
            "bed": str(state.get("bed_host") or ""),
            "build": str(state.get("device_build") or ""),
            "evidence_ref": lr_ref,
        })
    r = F.reconcile(fs, verdicts)
    sh.append(state, r["append"])
    fs2 = sh.load_facts(state)
    # broken 连击护栏:同 case 连续≥2 轮没跑成(broken/not_run,pass/fail 重置)=复跑
    # 救不了,升级人工;单次 not_run 照常入复跑集(级联受害者复跑常能过)。计数
    # **per-case 非 per-artifact**——reflow 每轮换 artifact 会把计数重置成 1,非收敛
    # broken 恒占 live 饿死 gather(DESIGN_dongkl_finalization §⑥ 回归#2 修 C,
    # 主文档回指 DESIGN_v8 §16.5b)。
    esc_facts = []
    for v in verdicts:
        if v["result"] not in ("broken", "not_run"):
            continue
        streak = 0
        for f in reversed([f for f in fs2 if f.get("ev") == "verdict"
                           and str(f.get("aid")) == v["aid"]]):
            if f.get("result") in ("broken", "not_run"):
                streak += 1
            else:
                break        # pass/fail=有推进,重置连击(跨 artifact 只被真进展打断)
        if streak >= 2 and not any(f.get("ev") == "escalated"
                                   and str(f.get("aid")) == v["aid"] for f in fs2):
            esc_facts.append({"ev": "escalated", "aid": v["aid"],
                              "reason": f"case did not execute for {streak} consecutive "
                                        "runs (broken/not_run) across reruns/reflows — "
                                        "rerun cannot help, needs human attention"})
    if esc_facts:
        sh.append(state, esc_facts)
        fs2 = sh.load_facts(state)
        sh.emit(f"⚠ {len(esc_facts)} 案连续多轮未跑成——复跑无效,升级人工")

    # pyATS 七码子分类机械归因(§18.1 broken 全链 / DESIGN_dongkl_finalization §④):
    # 按裁决携带的协议级硬码 broken_subtype 给 errored/blocked 落**机械**归因——不调
    # LLM(守 (44):broken 不深归因;细分基于协议物理码非语义猜测)。errored 据此经
    # diagnose→author 重写(不空跑同一确定性缺陷),blocked 据此进 env_confirm_waiting
    # 呈报(死设备复跑无益)。undetermined(not_run/stale/协议级分不清)不落此归因→
    # 维持 S_BROKEN 复跑+streak 升级(安全默认)。run_id 绑 verdict run,与 attribute
    # 幂等键同构(每裁决一次,不重复写)。
    sub_att: list[dict] = []
    for v in verdicts:
        if v.get("result") not in ("broken", "not_run"):
            continue
        sub = str(v.get("broken_subtype") or "")
        if sub not in ("errored", "blocked"):
            continue
        if any(f.get("ev") == "attribution" and f.get("run_id") == v["run_id"]
               for f in fs2):
            continue
        rec2 = next((rr for rr in data
                     if str(rr.get("autoid")) == v["aid"]), {}) or {}
        reason = str(rec2.get("broken_reason") or "")[:400]
        mine_v = [f for f in fs2 if f.get("aid") == v["aid"]]
        if sub == "errored":
            disp = "reflow"
            fixd = (f"pyATS Errored (protocol-hard signal: "
                    f"{reason or 'assertion contradicted by aligned device evidence / execution failure'}). "
                    "Re-running the same volume re-hits the same deterministic defect — "
                    "rewrite the assertion/step (reflow), do not burn device rounds.")
        else:  # blocked
            disp = "env_blocked"
            fixd = (f"pyATS Blocked (protocol-hard signal: "
                    f"{reason or 'device unreachable'}). Re-running cannot revive a "
                    "downed device — surface for environment restore, then resume.")
        sub_att.append({
            "ev": "attribution", "aid": v["aid"],
            "round": F.rounds_used(mine_v, v["aid"]),
            "run_id": v["run_id"], "layer": "E", "disposition": disp,
            "h_position": "none", "fix_direction": fixd,
            "evidence": reason or sub, "mechanical": True,
            "broken_subtype": sub})
    if sub_att:
        sh.append(state, sub_att)
        fs2 = sh.load_facts(state)
        _n_err = sum(1 for a in sub_att if a["disposition"] == "reflow")
        _n_blk = len(sub_att) - _n_err
        if _n_err:
            sh.emit(f"⚙ {_n_err} 案协议级 Errored(断言被对齐证据反证/执行失败)——机械判 reflow 重写")
        if _n_blk:
            sh.emit(f"⚙ {_n_blk} 案协议级 Blocked(设备不可达)——机械判 env 呈报")

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
                wb_failed = _writeback_one(aid, lr_ref, provisional=(ctx != F.CTX_DELIVERY)) or []
                ok_targets = [t for t in ("precedent", "footprint") if t not in wb_failed]
                if ok_targets:
                    wb_facts.append({"ev": "writeback", "aid": aid,
                                     "targets": ok_targets,
                                     "voucher_run": last.get("run_id"),
                                     "provisional": ctx != F.CTX_DELIVERY})
                if wb_failed:
                    # INV-11 式②(坑#4):失败不落成功事实——台账只为真发生的动作背书
                    wb_facts.append({"ev": "writeback_failed", "aid": aid,
                                     "targets": wb_failed,
                                     "voucher_run": last.get("run_id")})
                    sh.emit(f"⚠ …{aid[-6:]} 写回失败({','.join(wb_failed)}),已入账待补")
                if ok_targets:
                    sh.signal("writeback_done", aid, precedent="precedent" in ok_targets)
        elif last.get("result") == "fail" and ctx == F.CTX_DELIVERY:
            # 终验 fail:若此前有 writeback → 回滚(半毒先例撤销)。
            # broken/not_run 不触发回滚——案没跑成不构成对 pass 的反证((44))
            had = [f for f in fs2 if f.get("ev") == "writeback" and f.get("aid") == aid]
            rolled = [f for f in fs2 if f.get("ev") == "rollback" and f.get("aid") == aid]
            if had and len(rolled) < len(had):
                rb_failed = _rollback_one(aid) or []
                if rb_failed:
                    # INV-11 式②:回滚失败=半毒残留仍在库,显式入账(禁伪成功背书)
                    wb_facts.append({"ev": "rollback_failed", "aid": aid,
                                     "targets": rb_failed,
                                     "reason": "contradicted_at_delivery",
                                     "voucher_run": last.get("run_id")})
                    sh.emit(f"⚠ …{aid[-6:]} 先例回滚失败({','.join(rb_failed)}),"
                            f"半毒残留在库——需人工清污")
                else:
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
    # P1-8(实弹:counts 裸 JSON+英文枚举拍进用户面):evidence 行留人话简句,分状态
    # 明细走 debug 日志与同点 emit_tick(footer 九态计数是其用户面载体)
    logger.debug("reconcile counts %s", json.dumps(vw["counts"], ensure_ascii=False))
    sh.emit(f"对账:{len(verdicts)} 条裁决入流,通过 {npass} 条")
    sh.emit_tick(state, "reconcile", fs3)
    return {"phase_status": "ok", **sh.counts_update(state, fs3)}


def _writeback_one(aid: str, lr_ref: str, provisional: bool = False) -> list[str]:
    """真 PASS 双写回。返回失败目标清单(INV-11 式②,坑#4):失败不再静默——
    调用方据此落 writeback_failed 事实,台账只为真发生的动作背书。

    provisional(写回像记忆,§18.15-A / K (45)):True=子集轮过、未经整卷终验确认——旁挂进
    先例存储供检索期「用前先核」。footprint G 段语法是真上机跑通的(子集轮也在设备上跑过),
    device_verified 不因子集/终验而降级,故 on_device_passed 恒 True——provisional 只标先例
    案级可信度,不改单命令语法的已验证事实。"""
    failed: list[str] = []
    try:
        from main.ist_core.tools.device.precedent_tools import compile_writeback
        out = compile_writeback.func(autoid=aid, last_run_path=lr_ref, provisional=provisional)
        if str(out).startswith("error"):
            failed.append("precedent")
    except Exception:  # noqa: BLE001
        logger.warning("先例写回失败 %s", aid, exc_info=True)
        failed.append("precedent")
    try:
        from main.ist_core.tools.knowledge.footprint_writeback import compile_footprint_writeback
        out = compile_footprint_writeback.func(
            autoid=aid, provenance_path=f"workspace/outputs/{aid}/case.provenance.json",
            on_device_passed=True)
        if str(out).startswith("error"):
            failed.append("footprint")
    except Exception:  # noqa: BLE001
        logger.warning("footprint 写回失败 %s", aid, exc_info=True)
        failed.append("footprint")
    try:  # 行为知识晋升(V6 writeback 三连的第三件,验收后补齐)
        from main.ist_core.compile_engine_v8.uncertain import _promote_behavior_candidates
        class _NoLed:
            data = {"audit": {"notes": []}}
        _promote_behavior_candidates(aid, _NoLed())
    except Exception:  # noqa: BLE001
        logger.debug("行为晋升失败 %s", aid, exc_info=True)
    return failed


def _rollback_one(aid: str) -> list[str]:
    """写回回滚(清污脚本机制化):mirror 卷删除 + 意图索引摘键 + footprint 按 device_run 锚摘条。
    返回失败目标清单(INV-11 式②):失败=半毒残留仍在库,必须显式入账。"""
    failed: list[str] = []
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
        logger.warning("mirror 回滚失败 %s", aid, exc_info=True)
        failed.append("precedent")
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
        logger.warning("footprint 回滚失败 %s", aid, exc_info=True)
        failed.append("footprint")
    return failed


_DIG_HEAD_RE = re.compile(r"<<>> DiG [^\n]*?@(\S+)")
_SHEET_DIG_RE = re.compile(r"dig\s+@(\S+)")


def _evidence_suspect(rec: dict, aid: str) -> dict | None:
    """归属一致性门(I2/(27) 域内展开,机械):取证附件中的执行目标 vs 卷面对应步
    ——框架触发端会话按 case 切文件存在延迟输出跨界竞态(#67 实证:dig 超时 10s
    的输出落进邻案文件,归因孔拿邻案证据讲灵异故事)。两侧都非空且不相交=证据
    疑似错位;引擎自己发现自己的证据坏了,如实声明而非让孔猜。"""
    try:
        ctx = str(rec.get("device_context") or "")
        ev_targets = set(_DIG_HEAD_RE.findall(ctx))
        rows = _load_case_rows(aid)
        sheet_targets = set()
        for r in rows:
            sheet_targets.update(_SHEET_DIG_RE.findall(str(r.get("G") or "")))
        if ev_targets and sheet_targets and not (ev_targets & sheet_targets):
            return {"evidence_targets": sorted(ev_targets),
                    "sheet_targets": sorted(sheet_targets)}
    except Exception:  # noqa: BLE001
        logger.debug("归属一致性门检查失败 %s", aid, exc_info=True)
    return None


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


def _pass_is_vacuous(fs: list[dict], aid: str) -> bool:
    """对照 PASS 的 (44) 断言级非空真前置:PASS 案的 last_run 记录含执行失败/窗口失真
    形态 → 该 PASS 是空真嫌疑,没资格当对照证据(778012 三连假过实证——拿可能空真的
    兄弟 PASS 机械"证伪"本案前提=拿假证据翻真案,GA-CUT 重演)。
    digest 层 2026-07-14 起已把 anomaly-pass 降 broken(此门对新批幂等冗余);
    历史批/旧 client 无 window-audit 的记录靠本门兜底。记录读不到=不可判,保守判 True
    (无凭据的 PASS 不作对照——宁少一条对照,不给假证据)。"""
    mine = [f for f in fs if str(f.get("aid")) == aid]
    passes = [f for f in mine if f.get("ev") == "verdict" and f.get("result") == "pass"]
    if not passes:
        return True
    last = passes[-1]
    ref = str(last.get("evidence_ref") or "")
    if not ref:
        return True
    data = sh.read_json(sh.project_root() / ref, []) or []
    rec = next((r for r in data if isinstance(r, dict)
                and str(r.get("autoid")) == aid), None)
    if rec is None:
        return True
    return bool(rec.get("anomaly_lines") or rec.get("window_distortion"))


def _sibling_contrast(aid: str, state: dict, fs: list[dict], vw: dict) -> dict | None:
    """同组兄弟对照差分(F11′ advisory 证据注入;`sibling_contrast` 键名冻结——
    questions 侧读同键)。机械只到**证据装配**:分裂 {passed, failed},"同断言/同前提
    /证伪了哪条"的判断留给归因孔——机械改 disposition 是内容依赖判断,(47) 路由红线。

    - 对照集=manifest 同 group_path 兄弟(脑图组=语义单元,briefs F8a 同源);
    - passed 兄弟必须过 (44) 非空真前置(_pass_is_vacuous 剔除);
    - 2 轮同签名复现(frozen 谓词)∧ 非空真对照 PASS 在场 → 附 advisory 陈述
      (禁第三轮同向重编的建议,由 attributor 判,不机械执行)。
    ``IST_SIBLING_CONTRAST_INJECT=0`` 关。"""
    if not sh.env_flag("IST_SIBLING_CONTRAST_INJECT"):
        return None
    m = sh.manifest(state)
    cases = m.get("cases") or []
    me = next((c for c in cases if str(c.get("autoid")) == aid), None)
    gp = tuple((me or {}).get("group_path") or ())
    if not gp:
        return None
    passed, failed = [], []
    for c in cases:
        said = str(c.get("autoid"))
        if c is me or tuple(c.get("group_path") or ()) != gp:
            continue
        st = str((vw["cases"].get(said) or {}).get("status") or "")
        title = str(c.get("title") or "").splitlines()[0][:80] if c.get("title") else ""
        entry = {"aid_tail": said[-6:], "title": title}
        if st in (V.S_DELIVERABLE, V.S_SUBSET_VERIFIED):
            if _pass_is_vacuous(fs, said):
                continue
            passed.append(entry)
        elif st in (V.S_FAILED, V.S_CONTRADICTED, V.S_TERMINAL):
            failed.append(entry)
    if not passed and not failed:
        return None
    out: dict = {"passed": passed[:12], "failed": failed[:12],
                 "note": ("same mindmap group siblings' on-device outcomes (PASS entries "
                          "passed the vacuous-truth screen). A sibling PASS with the same "
                          "assertion form is mechanical evidence the shared premise CAN be "
                          "realized — but which premise differs (record type / address "
                          "family / client) is your judgement, not a mechanical verdict.")}
    if bool((vw["cases"].get(aid) or {}).get("frozen")) and passed:
        out["advisory"] = (
            "this case failed 2 rounds with the same signature while non-vacuous sibling "
            "PASS evidence exists — do NOT open a third same-direction reflow; prefer "
            "expectation_suspect (panel with the contrast cited) or defect_candidate "
            "(form with sibling citation), or change the evidence plane "
            "(different observation target / assertion pivot).")
    return out


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

    # G6 域分诊前筛(§17,判定树第零层 Ω⑥):s₀ 配对命中的案机械证据已足——不派
    # 深归因 fork(run12 实测 22 个归因 fork 大半烧在床污染案上,单案视野还判不出
    # 批级污染),直接落 h_s0 诊断+轻量归因事实;停车位/bed 面板/G2 出口消费链与
    # diagnose 同构。非 s₀ 案照旧深归因(前筛只筛派发,不动 LLM 孔本身)。复跑后
    # 再 fail 会产新裁决重新进 todo——彼时新诊断晚于用户 retry,写权律语义自洽
    # (每轮新 fail 都要新声明,非一次 retry 永久免检)。
    merges = [f for f in fs if f.get("ev") == "merged"]
    comp = [str(a) for a in (merges[-1].get("composition") or [])] if merges else []
    volume = str(merges[-1].get("volume") or "") if merges else ""
    if comp:
        profiles: dict[str, dict] = {}

        def _prof(aid: str) -> dict:
            if aid not in profiles:
                try:
                    profiles[aid] = _case_touch_profile(aid)
                except Exception:  # noqa: BLE001
                    profiles[aid] = {"persist": [], "l23": [], "entities": set()}
            return profiles[aid]

        pre_facts: list[dict] = []
        prescreened: list[str] = []
        recs_pre = {str(r.get("autoid")): r for r in
                    (sh.read_json(sh.project_root() / str(state.get("last_run_ref") or ""),
                                  []) or []) if isinstance(r, dict)}
        for aid in list(todo):
            mine = [f for f in fs if f.get("aid") == aid]
            last = F.latest_verdict(mine, aid) or {}
            sig = " ".join(str(s) for s in (last.get("signatures") or []))[:400]
            h_pos, polluters, basis = _s0_pair(aid, comp, _prof, sig)
            if h_pos != "h_s0":
                continue
            if _cross_bed_refuted(mine, last):
                sh.emit(f"…{aid[-6:]} 同签名 fail 跨床复现——s₀ 假设被反驳,保留深归因")
                continue
            # 多因保护(§18.6,坑#9 双故障遮蔽——668030 实证:s₀ 命中之外还有 TFTP
            # 独立故障被叙事淹没):日志有独立执行失败行(anomaly_lines)时不免派,
            # 深归因照常(diagnosis 照落,fork 能看到 s₀ 判定+异常行两份证据)
            if (recs_pre.get(aid) or {}).get("anomaly_lines"):
                sh.emit(f"…{aid[-6:]} s₀ 配对命中但日志含独立异常行——保留深归因(多因)")
                continue
            todo.remove(aid)
            prescreened.append(aid)
            # echo-grounding 正证(2026-07-13):s₀ 判定落回显佐证强度——受害者回显有占用
            # 语义=echo_confirmed(必要条件+回显直接佐证),无=necessity_only(仅必要条件推断)。
            # 题面据此校准语气;负门(自身执行失败)已由上方 anomaly_lines 保留深归因兜住。
            _es = _echo_support(recs_pre.get(aid) or {})
            # run_id 带 verdict run(#74-⑤,run13 实证):曾用 diag:pre:{volume}:{aid},
            # 同 volume 二次 fail 的新诊断被幂等键静默去重 → 复跑闸读到旧
            # user_cleared 多放行一圈复跑
            pre_facts += [
                {"ev": "diagnosis", "aid": aid, "h_position": "h_s0",
                 "polluters": polluters[:5], "basis": basis, "echo_support": _es,
                 "bed": str(state.get("bed_host") or ""),
                 "run_id": _g6_diag_key(last, volume, aid)},
                {"ev": "attribution", "aid": aid,
                 "round": F.rounds_used(mine, aid),
                 "run_id": str(last.get("run_id") or ""),
                 "layer": "E", "disposition": "rerun_isolated",
                 "h_position": "h_s0",
                 "fix_direction": _g6_fix_direction(_es, polluters),
                 "evidence": basis}]
        if pre_facts:
            sh.append(state, pre_facts)
            fs = sh.load_facts(state)
            sh.emit(f"域分诊前筛:{len(prescreened)} 案批级 s₀ 配对命中(床态污染),"
                    f"免深归因派发;{len(todo)} 案照常归因")
    if not todo:
        return {"phase_status": "ok", **sh.counts_update(state, fs)}
    lr_ref = str(state.get("last_run_ref") or "")
    data = sh.read_json(sh.project_root() / lr_ref, []) or []
    recs = {str(r.get("autoid")): r for r in data if isinstance(r, dict)}

    t0 = time.time()   # panel 收割新鲜度基线:早于本轮派发的 ask_panel.json 是陈旧遗留
    executor, limiter, _ = sh.fork_executor(len(todo))
    # K1 归因并发化(2026-07-16 perf 审计:归因裸 for 串行,36 fork 全程并发=1,
    # zhaiyq 128min/dongkl 120min 同病;与编写 fanout 对称——两孔同为 fork 派发,
    # 无理由一个并行一个串行):prepare 段保持串行(事实 append/attr_evidence 落盘/
    # env 组装全在主线程,零共享写),线程池只跑 _call_fork(结果落盘由 fork 侧
    # submit_attribution 写,其 last_run.json 读改写段已加进程内锁互斥)。
    _briefs_by_aid: dict[str, str] = {}
    for aid in todo:
        rec = recs.get(aid, {})
        mine = [f for f in fs if f.get("aid") == aid]
        contra = F.contradictions(mine, aid)
        # 单案证据文件(X8 效率债,2026-07-11 实测:fork 主读整批 last_run 把 26 案
        # 回显全吸进上下文,均价 849k↑=run5 的 3.3 倍)——主读单案,跨案对账仍可
        # fs_grep last_run(不整读)
        suspect = _evidence_suspect(rec, aid)
        if suspect:
            sh.append(state, [{"ev": "evidence_suspect", "aid": aid,
                               "round": F.rounds_used(mine, aid), **suspect}])
            sh.emit(f"…{aid[-6:]} 取证归属可疑(附件目标 {suspect['evidence_targets']}"
                    f" ≠ 卷面 {suspect['sheet_targets']}),已声明")
        ev_ref = ""
        try:
            evp = sh.outputs_root() / aid / "attr_evidence.json"
            evp.parent.mkdir(parents=True, exist_ok=True)
            rec_out = {**rec, "_evidence_suspect": suspect} if suspect else rec
            evp.write_text(json.dumps(rec_out, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            ev_ref = str(evp.relative_to(sh.project_root()))
        except Exception:  # noqa: BLE001
            logger.debug("单案证据落盘失败 %s", aid, exc_info=True)
        env = {
            "autoid": aid, "last_run_path": lr_ref,
            "evidence_path": ev_ref,
            "device_build": state.get("device_build", ""),
            "batch_pass_examples": [a for a, c in vw["cases"].items()
                                    if c["status"] in (V.S_DELIVERABLE, V.S_SUBSET_VERIFIED)][:6],
            "contradiction": bool(contra),
        }
        # N1b claim 级证据粘性:历史强处置 claim([主张,证据] 对)注入为必须消费事实
        # ——517027 型 r2 真缺陷主张不再因 r3 改判从归因视野消失;"另一条 claim 的
        # 修复"不构成对本条的反驳,须逐条显式处理
        _claims = F.strong_claims(mine, aid)
        if _claims:
            env["strong_claims"] = {
                "note": ("prior strong-disposition claims with device evidence — address "
                         "EACH explicitly this round: adopt it, refute it against this "
                         "round's echo, or state why it no longer applies. A claim must "
                         "not silently vanish; fixing a DIFFERENT claim in the same case "
                         "does not refute this one."),
                "claims": _claims}
        # F11′ 对照差分(advisory 证据注入;键名 sibling_contrast 冻结):机械装配同组
        # 兄弟 PASS/FAIL 分裂((44) 非空真前置已筛),判断留给孔;同步落事实供报告/审计
        _contrast = _sibling_contrast(aid, state, fs, vw)
        if _contrast:
            env["sibling_contrast"] = _contrast
            sh.append(state, [{"ev": "sibling_contrast", "aid": aid,
                               "run_id": str((F.latest_verdict(mine, aid) or {}).get("run_id") or ""),
                               "passed": _contrast["passed"], "failed": _contrast["failed"],
                               "advisory": bool(_contrast.get("advisory"))}])
        if suspect:
            env["evidence_note"] = (
                "trigger-side capture in this case's evidence is suspected MISATTRIBUTED "
                f"(capture dig targets {suspect['evidence_targets']} vs sheet targets "
                f"{suspect['sheet_targets']} — framework per-case session split race). "
                "Do NOT trust the RouterA/RouterB attachment; judge from the framework "
                "step log and device config session instead.")
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
        _briefs_by_aid[aid] = brief

    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(max_workers=_fanout_pool_size(len(_briefs_by_aid))) as ex:
        list(ex.map(
            lambda kv: _call_fork(executor, "compile-attributor", kv[1],
                                  tag=f"attr:{kv[0][-6:]}"),
            _briefs_by_aid.items()))

    # 收账:submit_attribution 落盘的 _attribution → attribution 事实
    data2 = sh.read_json(sh.project_root() / lr_ref, []) or []
    new_facts = []
    for rec in data2:
        aid = str(rec.get("autoid") or "")
        att = rec.get("_attribution")
        if aid in todo and isinstance(att, dict):
            mine = [f for f in fs if f.get("aid") == aid]
            last = F.latest_verdict(mine, aid)
            fact = {"ev": "attribution", "aid": aid,
                    "round": F.rounds_used(mine, aid),
                    "run_id": (last or {}).get("run_id", ""),
                    "layer": att.get("layer"), "disposition": att.get("disposition"),
                    "h_position": str(att.get("h_position") or ""),
                    "fix_direction": str(att.get("fix_direction") or "")[:800],
                    "evidence": str(att.get("evidence") or "")[:500]}
            # P0 C20:结构化缺陷表单透传进事实流——此前收账只抄 5 字段,表单唯一落点
            # last_run.json 被 closing 删除,全链湮灭(零消费者);现随事实永久保留,
            # closing 的缺陷候选单由此投影
            if isinstance(att.get("defect_candidate"), dict) and att["defect_candidate"]:
                fact["defect_candidate"] = att["defect_candidate"]
            new_facts.append(fact)
            # N1b 粘性审计(摆事实不替判,dongkl 定稿 §0):历史强 claim 在场而本轮
            # 走弱处置——落审计事实供报告/下批复盘,不硬拒(换形态检验轮属 dc 处置的
            # 组成部分,硬单调会把推翻误判所需的实验一并封锁,044572 实证)
            _prior = F.strong_claims(mine, aid)
            if (_prior and str(att.get("disposition")) not in F.STRONG_DISPOSITIONS
                    and str(att.get("evidence") or "") != "user"):
                new_facts.append({
                    "ev": "strong_claim_unaddressed", "aid": aid,
                    "run_id": (last or {}).get("run_id", ""),
                    "prior": [f"{c['disposition']}@r{c['round']}" for c in _prior],
                    "to": str(att.get("disposition") or "")})
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


def _fanout_pool_size(n_items: int) -> int:
    """fork fanout 线程池尺寸(K2,2026-07-16):IST_FANOUT_CONCURRENCY 真接到池——
    此前该 env 只喂了 limiter 没喂池(编写池硬编码 min(8,n)),配置不生效;
    默认值 8 不变,默认行为零变化。编写孔与归因孔共用(K1 对称)。"""
    try:
        cap = int(os.environ.get("IST_FANOUT_CONCURRENCY") or 8)
    except (TypeError, ValueError):
        cap = 8
    return max(2, min(cap, max(1, n_items)))


# --------------------------------------------------------------- [mech] diagnose
# 判定形态全部来自文法数据(redline 建议③④:persistence_channels 既有,synconfig 等
# 跨设备通道随数据生效;新通道/新形态=加 JSON 条目零代码,防三份手抄副本漂移)。
# 实体正则属形态级(IPv4/IPv6 压缩形/接口名——IPv6 全写形暂不识别,如实标注)。
_DIAG_ENTITY_RE = re.compile(
    r"(?:\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F:]*::[0-9a-fA-F:]+|(?:port|vlan|bond|eth)\d+")


def _diag_grammar():
    """文法数据 → 编译后的判定器(进程内随 grammar 缓存;数据缺失 fail-open 空判定)。"""
    try:
        from main.case_compiler.domain_grammar import (l23_write_patterns,
                                                       occupancy_semantics,
                                                       persistence_patterns)
        pers = [re.compile(p, re.IGNORECASE) for p in persistence_patterns()]
        l23 = [re.compile(p, re.IGNORECASE) for p in l23_write_patterns()]
        occ_p, occ_n = occupancy_semantics()
        occ = ([re.compile(p, re.IGNORECASE) for p in occ_p],
               [re.compile(p, re.IGNORECASE) for p in occ_n])
        return pers, l23, occ
    except Exception:  # noqa: BLE001
        # INV-11 式③(坑#18):门数据面缺席=门静默消失——必须留声。s₀ 污染诊断/
        # 自扰判定/触碰画像全族依赖本数据;缺席时诊断层整体失效
        logger.warning("diagnose 文法加载失败——s₀ 污染诊断门本次禁用(gate_disabled)",
                       exc_info=True)
        return [], [], ([], [])


@functools.lru_cache(maxsize=1)
def _clear_prefixes() -> tuple:
    """从 mirror clear.py::get_clear_list 机械解析框架逐命令清理覆盖(§18.12 三稿)。

    s₀ 判据修正的核心事实源:框架每 autoid 前对上一案 cmd_list 做逐命令逆操作清理
    (test_xlsx.py:239-256),覆盖集=CMD_RULES 的 startswith 前缀(源码闭集,clear.py
    变了这里自动跟随,零硬编码)。返回 (清得掉前缀集, 备份文件类前缀集)——后者的清理
    走 `clear conf file`,而其正则 `\\.cfg` 漏 `.tgz`(clear.py:178 盲区),故单列。
    解析失败=空集(fail-open:退回旧的「全持久写皆 s₀」保守行为,不误放)。"""
    try:
        from main.knowledge_paths import KNOWLEDGE_FOOTPRINTS  # 定位 knowledge/ 根
        root = KNOWLEDGE_FOOTPRINTS.parents[1]
        src = (root / "framework" / "mirror" / "lib" / "apv" / "clear.py").read_text(
            encoding="utf-8")
    except Exception:  # noqa: BLE001
        try:
            root = Path(__file__).resolve().parents[3]
            src = (root / "knowledge" / "framework" / "mirror" / "lib" / "apv"
                   / "clear.py").read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.warning("clear.py 解析失败——s₀ 框架清理过滤禁用(保守回落全持久写)",
                           exc_info=True)
            return (), ()
    cleanable, filelike = set(), set()
    for m in re.finditer(
            r"cmd\.startswith\('([^']+)'\)(?:\s+or\s+cmd\.startswith\('([^']+)'\))?"
            r"\s*,\s*\[([^\]]*)\]", src):
        prefixes = [p for p in (m.group(1), m.group(2)) if p]
        cleans = re.findall(r'"([^"]*)"', m.group(3))
        for p in prefixes:
            (filelike if "clear conf file" in cleans else cleanable).add(p.lower())
    return tuple(sorted(cleanable)), tuple(sorted(filelike))


@functools.lru_cache(maxsize=1)
def _fixed_infra_ips() -> frozenset:
    """测试床固定基础设施 IP(§18.14 S1:s₀ 脏态合取过滤料源)——从 env_facts 机械派生
    (topology JSON 登记的接口/服务 IPv4)。读失败 fail-open 回落 frozenset()(不误放
    真污染,只是退回旧的过宽行为)。"""
    try:
        from main.ist_core.tools._shared.env_facts import get_env_facts
        return get_env_facts().infra_ips()
    except Exception:  # noqa: BLE001
        logger.debug("infra_ips 读取失败——s₀ 脏态过滤回落空集(过宽但不误放)", exc_info=True)
        return frozenset()


_RESTORE_RE_S0 = re.compile(r"^\s*config\s+(memory|file|net|all|segment)\b", re.IGNORECASE)
_REMOTE_SAVE_RE = re.compile(r"^\s*write\s+(net|all\s+tftp|all\s+ftp|all\s+scp|all\s+sftp)\b",
                             re.IGNORECASE)
_SAVE_FILE_RE = re.compile(r"^\s*write\s+(?:all\s+)?file\s+(\S+)", re.IGNORECASE)
_RESTORE_FILE_RE = re.compile(r"^\s*config\s+(?:all\s+)?file\s+(\S+)", re.IGNORECASE)


def _s0_persist_class(cmd: str) -> str:
    """一条命中 persistence_channels 的命令,对 s₀ 的归类(§18.12 三稿数据驱动):
    restore=config 恢复(读磁盘,非污染源)/ cleanable=框架清得掉(不当 s₀)/
    remote=远端备份(本机不留)/ leftover_file=框架清不掉的本机备份文件(.tgz 盲区,
    真持久但需跨案撞名才有污染路径)/ uncovered=清理表外的真持久写(直接算 s₀)。"""
    c = cmd.strip().lower()
    if _RESTORE_RE_S0.match(c):
        return "restore"
    if _REMOTE_SAVE_RE.match(c):
        return "remote"
    cleanable, filelike = _clear_prefixes()
    if any(c.startswith(p) for p in filelike):
        return "leftover_file"
    if any(c.startswith(p) for p in cleanable):
        return "cleanable"
    return "uncovered"


def _g6_diag_key(last: dict, volume: str, aid: str) -> str:
    """G6 前筛 diagnosis 的幂等键(#74-⑤:带 verdict run 序,同 volume 二次 fail 的
    新诊断不再被去重;写入与去重检查共用本函数——两处手拼曾不对称,run_id 为空时
    去重失配多落同构账)。"""
    return f"diag:pre:{last.get('run_id') or volume + ':' + aid}"


def _case_touch_profile(aid: str) -> dict:
    """从成品卷机械提取:持久面写/L2-L3 写/实体 token(S10 交换子配对的 I6 近似输入)。

    persist 经 §18.12 三稿收窄:命中 persistence_channels 的行再按 `_s0_persist_class`
    过滤——只保留框架清不掉的真持久写(uncovered ∪ leftover_file);config 恢复(读)、
    框架可清(write memory 等)、远端备份不进 persist(442 次历史指认对照:这三类
    占 75%,是把读当写/把可清当污染的误判)。save_files/restore_files 供 _s0_pair 做
    leftover_file(本机备份文件)的跨案撞名裁决——同名 write→config 才有真污染路径。"""
    rows = _load_case_rows(aid) or []
    pers_res, l23_res, _ = _diag_grammar()
    persist, l23, ents = [], [], set()
    save_files, restore_files = set(), set()
    for r in rows:
        if not isinstance(r, dict):
            continue
        g = str(r.get("G") or "")
        ents.update(_DIAG_ENTITY_RE.findall(g))
        if str(r.get("E", "")).startswith("APV") and str(r.get("F", "")) in (
                "cmd_config", "cmds_config"):
            for line in g.splitlines():
                line = line.strip()
                if not line:
                    continue
                mf = _SAVE_FILE_RE.match(line)
                if mf:
                    save_files.add(mf.group(1).strip('"\''))
                mr = _RESTORE_FILE_RE.match(line)
                if mr:
                    restore_files.add(mr.group(1).strip('"\''))
                if any(p.search(line) for p in pers_res):
                    if _s0_persist_class(line) in ("uncovered", "leftover_file"):
                        persist.append(line)      # 框架清不掉的才算持久面写
                elif any(p.search(line) for p in l23_res):
                    l23.append(line)
    return {"persist": persist, "l23": l23, "entities": ents,
            "save_files": save_files, "restore_files": restore_files}


def _occupancy_hit(sig: str) -> bool:
    """占用/已存在语义(文法数据,带否定排除——'does not exist' 不得命中)。

    行级判定(2026-07-14 run20 实证):否定是行内局部现象——负向模式只否决**同一行**的
    正向命中,不做全窗一票否决。全窗否决曾被框架步骤描述横幅误伤:668030 回显含用例
    自己的意图文案「恢复后应不存在」,'不存在' 否决了另一行真实的占用 Warning,
    echo_confirmed 被错降 necessity_only(方向保守无害,但机械上是错的)。"""
    _, _, (occ_p, occ_n) = _diag_grammar()
    for line in sig.splitlines() or [sig]:
        if any(p.search(line) for p in occ_p) and not any(n.search(line) for n in occ_n):
            return True
    return False


def _cross_bed_refuted(mine: list[dict], last: dict) -> bool:
    """跨床对照(run16 实弹:9 案同签名 fail 跨 93/105 两床复现,s₀ 判定第三次
    方向错):s₀ 是床状态属性——同卷面同签名 fail 出现在 ≥2 个不同床=污染假设
    被反驳(污染不跨床),真因在 λ/V 域,必须深归因而非床面板。"""
    # 存量签名跨格式归一(A1 迁移条款消费点):facts 里旧轮签名可能是旧格式
    # (带 `` in: <file>`` 尾),与新轮纯 pattern 交集前两侧归一,防跨界轮静默失效
    sigs = F._norm_sigs(last.get("signatures"))
    if not sigs:
        return False
    beds = {str(f.get("bed")) for f in mine
            if f.get("ev") == "verdict" and f.get("result") == "fail"
            and str(f.get("artifact")) == str(last.get("artifact"))
            and sigs & F._norm_sigs(f.get("signatures"))
            and f.get("bed")}
    return len(beds) >= 2


def _s0_pair(aid: str, comp: list[str], prof, sig: str) -> tuple[str, list[dict], str]:
    """s₀ 配对机械判定(S10 交换子 I6 近似;diagnose 与 G6 前筛共用同一判定核)。

    返回 (h_position, polluters, basis);未命中返回 ("", [], "")。
    prof(aid)->触碰画像({persist, l23, entities}),调用方带缓存注入。
    """
    vict = prof(aid)
    polluters: list[dict] = []
    idx = comp.index(aid) if aid in comp else len(comp)
    for a in comp:
        if a == aid:
            continue
        p = prof(a)
        # persist 已在 touch_profile 收窄为「框架清不掉的真持久写」(§18.12 三稿);
        # 其中 leftover_file(本机备份文件,.tgz 清理盲区)只在**受害者从同名文件
        # config 恢复**时才有实际污染路径——同名 write→config 撞名(autoid 异名不撞、
        # 自存自恢复不算跨案)。uncovered(清理表外真持久写)直接算。
        if p["persist"]:
            hit_names = p.get("save_files", set()) & vict.get("restore_files", set())
            has_uncovered = any(_s0_persist_class(ln) == "uncovered"
                                for ln in p["persist"])
            if has_uncovered or hit_names:
                cmds = list(p["persist"][:2])
                if hit_names:
                    cmds.append(f"[shared save/restore file: {sorted(hit_names)[0]}]")
                polluters.append({"aid": a, "via": "persistent-plane write",
                                  "cmds": cmds[:3]})
        if not p["persist"] and comp.index(a) < idx:
            # 配置面 L2/L3 写按卷序(前驱写、后继读)——I6 近似,跨轮形态由
            # 持久面分支与床账兜
            p_ents = {e for line in p["l23"]
                      for e in _DIAG_ENTITY_RE.findall(line)}
            # §18.14 S1(脏态合取):共享实体减去固定基础设施 IP——两案共用后端服务 IP/
            # 接口 IP(topology 登记的合法共用地址)不是「前写脏、后读脏」污染,是测同一
            # 被测系统的正常共用(667986 实弹:凭常量 co-reference 172.16.32.70 误贴 s₀,
            # 掩盖自身断言缺陷)。减法必须在 [:4] 截断**前**(否则先截到基础设施 IP 会漏
            # 掉第 5 个真污染物)。只减 IP 不碰 vlan/port/bond 名(自建对象是真污染物)。
            shared = sorted((p_ents & vict["entities"]) - _fixed_infra_ips())[:4]
            if shared:
                polluters.append({"aid": a, "via": "shared L2/L3 entity",
                                  "shared": shared})
    # 自扰仅对 uncovered(框架清不掉的表外真持久写)成立——§18.12 三稿:leftover_file
    # (本机备份文件)自存自恢复是**被测行为本身**(write file 保存→config file 恢复),
    # 占用警告是配置时的例行 advisory(非占用陈述,occupancy_semantics 已负向排除);
    # 把它判自扰 s₀ 是写保存族误判的最后一环(668015/030 self_persist 假阳)。
    self_persist = (any(_s0_persist_class(ln) == "uncovered" for ln in vict["persist"])
                    and _occupancy_hit(sig))
    if polluters or self_persist:
        basis = ("self persistent-plane write + occupied/exists signature"
                 if self_persist and not polluters else
                 "upstream writer(s) in volume order touch shared bottom-layer/persistent state")
        return "h_s0", polluters, basis
    return "", [], ""


def _g6_fix_direction(es: str, polluters: list[dict]) -> str:
    """G6 免派归因的 fix_direction 文案——断言语气与证据强度匹配(§18.8 题面校准的
    facts/brief 面;2026-07-14 审计修:旧固定话术对 necessity_only 档也说 evidence
    sufficient,且对持久面毒源仍推荐 tail placement——run11 已实证排尾消不掉跨轮
    通路(_s0_pair 注释),代码自相矛盾)。此文案随 attribution 事实流入重编 brief。"""
    persist = any(str(p.get("via")) == "persistent-plane write" for p in polluters)
    routes = ("bed treatment / self-cleanup recompile" if persist
              else "bed treatment / tail placement / self-cleanup recompile")
    if es == "echo_confirmed":
        return ("batch-level s0 pairing hit, and the victim's echo shows occupancy/"
                "already-exists semantics (direct corroboration); deep attribution "
                f"fork skipped. Route: {routes}.")
    return ("batch-level s0 pairing hit — a necessary-condition inference, NOT a "
            "confirmation (a device/env anomaly presents the same symptom); deep "
            "attribution fork skipped for cost — read the victim's full echo before "
            f"adopting this direction. Route: {routes}.")


def _echo_support(rec: dict) -> str:
    """s₀ 判定的回显佐证强度(echo-grounding 正证,2026-07-13):受害者完整回显里有没有
    占用/已存在语义(run13 「occupied by SLB virtual service」型)——有=echo_confirmed(交换子
    必要条件之外还有回显直接佐证污染形态),无=necessity_only(仅必要条件推断,题面据此校准
    语气)。判据是文法 occupancy_semantics(带否定排除),不硬编码;负门(自身执行失败)另由
    anomaly_lines 走。rec 缺回显=necessity_only(不猜)。"""
    ctx = str((rec or {}).get("device_context") or (rec or {}).get("detail_tail") or "")
    if not ctx:
        return "necessity_only"
    return "echo_confirmed" if _occupancy_hit(ctx) else "necessity_only"


def diagnose(state: dict) -> dict:
    """批级诊断(V8.5 片3;X3 的机械半:LLM 观察者/common_cause 提案留片4)。

    单案归因 fork 只有本案视野——run11 实证 17 个 fork 各讲各的故事、无一触发横向
    对账(归因版本感知 2/19)。本节点吃批级事实做机械裁决:
    ① 交换子配对(S10 的 I6 近似):卷序前驱案的持久面写(全局配置存储分量=全机耦合)
      或 L2/L3 写实体 ∩ 受害案触碰实体 → h_position=h_s0 裁决+污染者点名;
    ② 自扰:本案自己有持久面写且签名呈「已占用/已存在」形态 → h_s0(668044 tftp 型);
    ③ 同签名词干聚类 ≥2 → common_cause 事实(机械前筛 (24) 的产物,片4 提案消费)。
    裁决只落 diagnosis 事实(append-only,不改归因事实);消费点=merge 复跑闸
    (复跑可救=h 重采样定理:s₀ 冻结复跑不可救——run11 668030 同签名三 run 三标签、
    重排复验×3 全部再翻挂的机理)与渲染层叙事。fork 候选(attribution.h_position)
    与本裁决并存,分工=D8(fork 只降不判死,批级裁决在此)。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    merges = [f for f in fs if f.get("ev") == "merged"]
    if not merges:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    comp = [str(a) for a in (merges[-1].get("composition") or [])]
    volume = str(merges[-1].get("volume") or "")
    failed = [a for a, c in vw["cases"].items()
              if c["status"] in (V.S_FAILED, V.S_CONTRADICTED)]
    if not failed:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    # INV-11 式③(坑#18):门数据面缺席=显式入账,禁静默 no-op——K 三个数据面
    # (①grammar 门数据 ②inventory 签名 ③case 画像)缺任一都落 gate_disabled,用户在
    # 报告 K 健康度行看得见(§18.2 第6行补齐:此前只 grammar 面有门,inventory 静默
    # 降级、画像 except 静默、报告不渲染)
    pers_chk, l23_chk, _occ = _diag_grammar()
    _gate_facts: list[dict] = []
    if not pers_chk and not l23_chk:
        _gate_facts.append({"ev": "gate_disabled", "aid": "", "gate": "diagnose_s0",
                            "reason": "domain_grammar unavailable — batch-level "
                                      "pollution diagnosis disabled this run"})
    # ② inventory 面(inverse_forms):τ 覆盖门与 bed 机械逆放依赖它,缺席=降级词表/LLM
    try:
        from main.ist_core.compile_engine_v8.bed import _inverse_pairs
        if not _inverse_pairs():
            _gate_facts.append({"ev": "gate_disabled", "aid": "", "gate": "inverse_forms",
                                "reason": "command_inventory inverse_forms unavailable — "
                                          "tau-coverage gate and mechanical bed restore degrade"})
    except Exception:  # noqa: BLE001
        logger.debug("inverse_forms 健康检查异常", exc_info=True)
    if _gate_facts:
        sh.append(state, _gate_facts)
        for gf in _gate_facts:
            sh.emit(f"⚠ K 健康度:{gf['gate']} 门本轮禁用(已入账)")

    profiles: dict[str, dict] = {}
    _profile_failures: list[str] = []

    def _prof(aid: str) -> dict:
        if aid not in profiles:
            try:
                profiles[aid] = _case_touch_profile(aid)
            except Exception:  # noqa: BLE001
                # ③ 画像面缺席:此前静默返回空 profile → s₀ 配对对该案失明。记失败,
                # 批末落 gate_disabled(不逐案落,避免刷账)
                logger.debug("触碰画像提取失败 %s", aid, exc_info=True)
                _profile_failures.append(aid)
                profiles[aid] = {"persist": [], "l23": [], "entities": set()}
        return profiles[aid]

    new_facts: list[dict] = []
    sig_by_aid: dict[str, str] = {}
    # echo-grounding:回显佐证强度需读受害者完整回显(与 G6 前筛同源)
    _recs = {str(r.get("autoid")): r for r in
             (sh.read_json(sh.project_root() / str(state.get("last_run_ref") or ""), [])
              or []) if isinstance(r, dict)}
    for aid in failed:
        mine = [f for f in fs if f.get("aid") == aid]
        last = F.latest_verdict(mine, aid) or {}
        sigs = [str(s) for s in (last.get("signatures") or [])]
        sig = " ".join(sigs)[:400]
        sig_by_aid[aid] = sigs   # 全签名集(坑#25:双签名故障只按第一签名归簇=第二故障族不可见)
        if any(f.get("ev") == "diagnosis"
               and str(f.get("run_id")) == _g6_diag_key(last, volume, aid)
               for f in mine):
            continue   # G6 前筛已判(同一 fail 裁决),结论同构——不重复落账(词干聚类照算)
        h_pos, polluters, basis = _s0_pair(aid, comp, _prof, sig)
        if h_pos == "h_s0" and _cross_bed_refuted(mine, last):
            h_pos, polluters, basis = "", [], ""   # 跨床反驳:s₀ 不成立
        # 自身执行失败证据 → 不判 s₀(问询前提校验/echo-grounding 负门,与 G6 前筛
        # 1052 的 anomaly 保护一致):失败机理在受害者自己的序列,不是床污染。此前
        # diagnose 主体只有跨床反驳、缺此门,是 G6 未覆盖案的 s₀ 误判缺口
        if h_pos == "h_s0" and (_recs.get(aid) or {}).get("anomaly_lines"):
            sh.emit(f"…{aid[-6:]} s₀ 配对命中但回显含自身执行失败——不判 s₀,保留深归因")
            h_pos, polluters, basis = "", [], ""
        if not h_pos:
            att = [f for f in mine if f.get("ev") == "attribution"]
            cand_h = str((att[-1] if att else {}).get("h_position") or "")
            # §18.14 缺口修(run24 655173):机械 _s0_pair **明确判无 s₀**(跑了配对、
            # 非失明,S1 已排除固定基础设施 IP)时,attributor 的 h_s0 候选**不升格**成批级
            # s₀ diagnosis——否则固定接口 IP 被 fork 误判污染→bed 床面板,而机械已判无
            # 污染者(D8 分工:批级裁决为准、fork 只降不判死)。仅机械**失明**(触碰画像
            # 提取失败,配对不可得)时才采信 fork 的 s₀;非 s₀ 候选(h_pi 等)照常回退。
            if cand_h.startswith("h_s0") and aid not in _profile_failures:
                sh.emit(f"…{aid[-6:]} fork 判 s₀ 但机械配对判无污染者——不升格,保留深归因")
                # N2′ 分歧记账(2026-07-16):不升格判定本身是「fork 假设 vs 机械配对」
                # 的分歧事实——落账供 contra/cap 题面呈语境(用户不再盲判),不改判定
                # (test_attributor_s0_not_upgraded… 锁住的语义不动);幂等键=run_id
                new_facts.append({"ev": "s0_dispute", "aid": aid,
                                  "run_id": f"diag:{volume}:{aid}",
                                  "fork_h": "h_s0", "mech": "no_polluter"})
                cand_h = ""
            h_pos = cand_h
            basis = "fork candidate (no batch-level counter-evidence)" if h_pos else ""
        if not h_pos:
            continue   # unknown 不落账(空裁决无信息)
        _df = {"ev": "diagnosis", "aid": aid, "h_position": h_pos,
               "polluters": polluters[:5], "basis": basis,
               "bed": str(state.get("bed_host") or ""),
               "run_id": f"diag:{volume}:{aid}"}
        if h_pos == "h_s0":
            _df["echo_support"] = _echo_support(_recs.get(aid) or {})
        new_facts.append(_df)
    # 同签名词干聚类(机械前筛 (24)):≥2 案同稳定词干 → common_cause 事实
    stems: dict[str, list[str]] = {}
    for aid, sig_list in sig_by_aid.items():
        for one in sig_list or []:
            stem = re.sub(r"\d{6,}", "<id>", " ".join(str(one).lower().split()))[:160]
            if stem and aid not in stems.get(stem, []):
                stems.setdefault(stem, []).append(aid)
    for stem, aids in stems.items():
        if len(aids) >= 2:
            new_facts.append({"ev": "common_cause", "aid": "", "key": stem,
                              "aids": sorted(aids), "run_id": f"cc:{volume}:{stem[:40]}"})
    # ③ 画像面缺席批末落一条 gate_disabled(不逐案刷账):s₀ 配对对这些案失明
    if _profile_failures:
        new_facts.append({"ev": "gate_disabled", "aid": "", "gate": "touch_profile",
                          "reason": f"case-touch profile extraction failed for "
                                    f"{len(_profile_failures)} case(s) — s0 pairing blind to them",
                          "aids": sorted(_profile_failures)[:20]})
        sh.emit(f"⚠ K 健康度:{len(_profile_failures)} 案触碰画像提取失败,s₀ 配对对其失明(已入账)")
    if new_facts:
        sh.append(state, new_facts)
        n_s0 = sum(1 for f in new_facts if f.get("h_position") == "h_s0")
        if n_s0:
            sh.emit(f"批级诊断:{n_s0} 案判床态残留(s₀)——复跑不可救,复跑闸已按此收紧")
    fs2 = sh.load_facts(state)
    return {"phase_status": "ok", **sh.counts_update(state, fs2)}


def ask_contradiction(state: dict) -> dict:
    """用户问询边终形(§11.11 构件六):目标 = 未答 ask_panel ∪ cap 二分 ∪ contra≥2
    ∪ env 待确认 ∪ 挂起案新批恢复。题面渲染自 panel(差异呈报+已检索+理解 Z);
    决策存小写 token(confirm|correct|defect|…);挂起/停止=常驻特权(自由输入兜底,
    不占选项);未获答案(非交互/面板取消)→ 自动挂起带可行动反馈,永不空转。"""
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    t = sh.ask_targets(state, fs, vw)
    cap_set = set(t["cap"])
    # 优先序 panel>contra>cap>env>bed>suspended;panel∩cap 合并一题(cap 语境附注)
    ordered = ([(a, "panel") for a in t["panel"]] + [(a, "contra") for a in t["contra"]]
               + [(a, "cap") for a in t["cap"]] + [(a, "env") for a in t["env"]]
               + [(a, "bed") for a in t.get("bed", [])]
               + [(a, "suspended") for a in t["suspended"]])
    seen: set = set()
    targets = [(a, k) for a, k in ordered if not (a in seen or seen.add(a))]
    if not targets:
        return {"phase_status": "nothing_to_do", **sh.counts_update(state, fs)}
    m = sh.manifest(state)
    titles = {str(c.get("autoid")): str(c.get("title") or "") for c in (m.get("cases") or [])}
    payload = []
    qids: dict[str, str] = {}
    from main.ist_core.compile_engine_v8 import remedies as RM
    _maxr = int(state.get("max_rounds") or 3)
    for aid, kind in targets:
        mine = [f for f in fs if f.get("aid") == aid]
        # 队列空证明(片4,§11.7「队列非空禁 ask」的题面侧):已试修法清单+当前队列。
        # 队列非空却进 ask 边=路由缺陷,如实告警(fail-open 照常问,人比闸权威)
        _q = RM.derive_queue(fs, vw, aid, _maxr, sh.granted_rounds(fs, aid))
        if _q and kind in ("cap", "env", "bed", "contra"):
            logger.warning("ask 目标 %s(%s) 的导出修法队列非空(%s)——路由应先自愈",
                           aid[-6:], kind, [x.get("action") for x in _q])
        item = {"autoid": aid, "kind": kind,
                "title": titles.get(aid, ""),
                "rounds": vw["cases"][aid]["rounds"],
                "contradictions": vw["cases"][aid]["contradictions"],
                "timeline": _case_story(mine),
                "diagnosis": _case_diag(mine)[:300],
                "tried": RM.tried_actions(fs, aid),
                "queue_empty": not _q,
                "prior_choices": [f.get("answer") for f in mine if f.get("ev") == "decision"]}
        if kind in ("cap", "env"):
            # 接线包 2e(claim_history 键名冻结,questions._claim_history_line 消费):
            # 题面呈全轮归因史——churn 不吞早轮假设(517027 r2「Timeout=0」题面消失);
            # r99 生命周期记录不入(那是裁决记账,不是技术判断史)
            item["claim_history"] = [
                {"round": int(f.get("round") or 0), "layer": str(f.get("layer") or ""),
                 "disposition": str(f.get("disposition") or ""),
                 "claim": str(f.get("user_note") or f.get("fix_direction") or "")[:400],
                 "evidence": str(f.get("evidence") or "")[:200]}
                for f in mine if f.get("ev") == "attribution"
                and int(f.get("round") or 0) != 99]
        if kind in ("contra", "cap"):
            # 接线包 2f(s0_dispute 键名冻结,questions._s0_dispute_note 消费):
            # 污染分歧投影——fork 判自污染 vs 机械配对无污染者的次数(N2′ 记账面);
            # 床态快照 pre_dirty/post_dirty 有数据源后同键补入,渲染自动生效
            _dsp = [f for f in mine if f.get("ev") == "s0_dispute"]
            if _dsp:
                item["s0_dispute"] = {"count": len({str(f.get("run_id")) for f in _dsp})}
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
        elif kind == "bed":
            diags = [f for f in mine if f.get("ev") == "diagnosis"]
            d = diags[-1] if diags else {}
            pol = [str(p.get("aid", ""))[-6:] for p in (d.get("polluters") or [])][:3]
            item["evidence"] = (str(d.get("basis") or "")
                                + (f";polluter(s): {'、'.join(pol)}" if pol else ""))[:300]
            item["echo_support"] = str(d.get("echo_support") or "necessity_only")   # 回显佐证强度
            # G2(§17):自污染者判定——本案卷面自身含无 τ 的差集内写(每次执行都
            # 重新污染,复跑=毒药出口,(40) 分类学)→题面换重编出口
            try:
                from main.case_compiler.tau_coverage import check_tau_coverage
                _rows = _load_case_rows(aid)
                _tr = check_tau_coverage(_rows)
                if not _tr.ok:
                    item["self_polluter"] = True
                    item["missing_tau"] = [m["cmd"] for m in _tr.missing][:3]
                    item["suggested_tau"] = [m["suggested_inverse"]
                                             for m in reversed(_tr.missing)][:3]
            except Exception:  # noqa: BLE001
                pass
            qids[aid] = f"bed:{aid}:{len(diags)}"
        elif kind == "suspended":
            n_runs = sum(1 for f in fs if f.get("ev") == "run_start")
            qids[aid] = f"resume:{aid}:{n_runs}"
        else:
            qids[aid] = f"contra:{aid}:{vw['cases'][aid]['contradictions']}"
        payload.append(item)
    # 题面入账(run11 体检发现#6:本节点产生了全部 7 次 decision 却零 ask_panel 事实
    # ——问询侧无痕,违 (16) 残差公理的对称面)。落题面摘要,选项/证据在 payload 原件。
    sh.append(state, [{"ev": "ask_shown", "aid": it["autoid"],
                       "question_id": qids[it["autoid"]], "kind": it["kind"],
                       "question": str(it.get("evidence") or it.get("hypothesis") or "")[:300]}
                      for it in payload])
    _ccs = [f for f in fs if f.get("ev") == "common_cause"]
    _cc_note = [{"key": str(c.get("key"))[:120],
                 "aids": [str(a)[-6:] for a in (c.get("aids") or [])]}
                for c in _ccs[-3:]]
    # 共因合题(run14 实弹修:11 案同因曾呈 11 题分 3 页——「回答一次」的机械保证):
    # bed 类目标按 (诊断依据, 污染者集) 分组,同组只出组长一题(题面注明代表案集),
    # 答案经 _group_leader 广播到组员;非 bed 题不折叠
    _group_leader: dict[str, str] = {}
    _folded: list[dict] = []
    _bed_groups: dict[tuple, dict] = {}
    for it in payload:
        if it["kind"] not in ("bed", "suspended"):
            _folded.append(it)
            continue
        # suspended 恢复题同因合并(run15 形态:11 个同因挂起案的恢复问询=一题)——
        # 分组键同 bed(最新诊断的依据+污染者集;无诊断的挂起案不合并)
        _d = next((f for f in reversed(fs) if f.get("ev") == "diagnosis"
                   and str(f.get("aid")) == it["autoid"]), {})
        _key = (str(_d.get("basis") or ""),
                tuple(sorted(str(pp.get("aid")) for pp in (_d.get("polluters") or []))))
        if _key in _bed_groups and _key != ("", ()):
            leader = _bed_groups[_key]
            leader.setdefault("group_aids", [leader["autoid"]]).append(it["autoid"])
            _group_leader[it["autoid"]] = leader["autoid"]
        else:
            _bed_groups[_key] = it
            _folded.append(it)
    if _group_leader:
        sh.emit(f"共因合题:{len(payload) - len(_folded)} 题并入代表题"
                f"(同诊断依据+同污染者集),答案将广播")
    ans = interrupt({"kind": "ask_contradiction", "cases": _folded,
                     # 批级共因摘要(§18.6 坑#8:common_cause 产出后曾零消费方)
                     "common_causes": _cc_note})
    # 组员答案回填:沿用组长(消化循环遍历原始 payload,组员据此拿到答案)
    if isinstance(ans, dict) and _group_leader:
        for member, leader in _group_leader.items():
            if member not in ans and leader in ans:
                ans[member] = ans[leader]
    new_facts = []
    for item in payload:
        aid, kind, qid = item["autoid"], item["kind"], qids[item["autoid"]]
        mine = [f for f in fs if f.get("aid") == aid]
        raw = (ans or {}).get(aid)
        # 双形态:dict={answer, token}(引擎同源精确映射,W3)/str=旧形态或直答
        if isinstance(raw, dict):
            a = str(raw.get("answer") or "")
            tok_exact = str(raw.get("token") or "")
        else:
            a, tok_exact = str(raw or ""), ""
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
        # 精确 token 优先(引擎产 label 的同源映射);Other 自由输入才走语义兜底
        tok = tok_exact or _answer_token(kind, a)
        new_facts.append({"ev": "decision", "aid": aid, "question_id": qid,
                          "answer": a, "token": tok,
                          # R5① 代理(片4):走了语义兜底=用户没选引擎给的选项
                          # (Other 自由输入)——选项不适配的机械信号
                          "freeform": not bool(tok_exact)})
        # G4 决策 echo-back((41)③ 消化保真):把 token 化结果即时复述——传输截断/
        # 对位竞态/语义兜底误判在此一眼可见(run12 实测:「停止:…」被截断兜底成
        # retry,一圈无效循环;echo 是展示零应答成本)
        sh.emit(f"…{aid[-6:]} 你的裁决「{a[:24]}」→ 引擎理解为:"
                f"{_TOKEN_CN.get(tok, tok)}"
                + ("(语义兜底,非选项原文——请核对)" if not tok_exact else ""))
        if tok == "suspend":
            new_facts.append({"ev": "suspended", "aid": aid, "reason": qid})
        elif tok in ("stop", "downgrade"):
            # 止损=用户显式裁决(N1a 台账本体论,2026-07-16 契约):生命周期记账与
            # 语义归因分离——zhaiyq 三例 r99 env_blocked(517027/600046/533020)全是
            # 记账形态,"环境阻塞"语义为假。契约(键名/值冻结,乙 questions 渲染
            # `_DISP_CN` 已备词条、views/report_gate 终态元组已收):
            # env 题面 stop → env_blocked 保留(选项原文即「确认环境问题」,用户选它
            # =确认环境,语义如实);其余题面 → {layer:"user", disposition:"user_stop"}
            # + 独立 user_stop 事实(questions/报告侧消费)。
            if kind == "env":
                acc = {"layer": "E", "disposition": "env_blocked"}
            else:
                acc = {"layer": "user", "disposition": "user_stop"}
                new_facts.append({"ev": "user_stop", "aid": aid, "question_id": qid,
                                  "answer": a, "token": tok})
            new_facts.append({"ev": "attribution", "aid": aid, "round": 99, **acc,
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
            if kind == "bed":
                # 床已治理(用户声明)→ 覆盖 s₀ 诊断(diagnosis 事实 append-only 叠加,
                # 最新条生效),复跑闸与停车位随之放行——复跑一次验证治理效果
                new_facts.append({"ev": "diagnosis", "aid": aid,
                                  "h_position": "user_cleared",
                                  "polluters": [], "basis": f"user attests bed treated: {a}"[:200],
                                  "run_id": f"user:bed_retry:{qid}"})
        elif tok == "reflow_tau":
            # G2((40)):自污染者→重编补 τ(唯一非绕路出口;fix_direction 携机械
            # 派生的恢复序列,briefs 注入重编 brief;G1 门核对重编结果——R11-P2)
            _tau = "; ".join(str(t) for t in (item.get("suggested_tau") or []))
            new_facts.append({"ev": "attribution", "aid": aid,
                              "round": F.rounds_used(mine, aid),
                              "run_id": f"user:reflow_tau:{qid}",
                              "layer": "V", "disposition": "reflow",
                              "fix_direction": ("append in-case teardown AFTER assertions "
                                                f"(suggested inverse replay: {_tau})"),
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
    # 本轮消化的实答数(answer 非空的 decision;自动挂起的空答不算)——路由据此区分
    # 「部分作答」与「真·未获答」:后者才允许 closing 禁空转(run17 实弹,§16.6)
    consumed = sum(1 for f in new_facts
                   if f.get("ev") == "decision" and str(f.get("answer") or "").strip())
    return {"phase_status": "ok", "ask_answers_consumed": consumed,
            **sh.counts_update(state, fs2)}


# --------------------------------------------------------------- [mech] closing
def _g4_decision_echoes(fs: list[dict]) -> list[dict]:
    """G4 收口卡 echo((41)③):每条实答 decision → {autoid, answer, understood}。
    understood=token 的人话映射(语义兜底误判在此与 answer 原文并排可核对——run12
    实录:「停止:…」截断被兜底成 retry,echo 上 answer 与 understood 明显相悖);
    token 不在表内=Other 自由输入,回落 answer 原文前 40 字(如实,不翻译)。"""
    out = []
    for f in fs:
        if f.get("ev") == "decision" and f.get("answer"):
            tok = str(f.get("token") or "")
            out.append({"autoid": str(f.get("aid") or ""),
                        "answer": str(f.get("answer"))[:80],
                        "understood": _TOKEN_CN.get(tok, str(f.get("answer"))[:40])})
    return out


def _archive_unsuccessful(aids: list[str], out_name: str) -> str | None:
    """未通过卷 xlsx(V6 契约迁入):gate-free 合并全部非交付案 → <批名>/unsuccessful_cases.xlsx。"""
    from main.ist_core.tools.device.emit_xlsx_tool import compile_emit_merged
    cases = []
    for aid in aids:
        rows = sh.case_rows(aid)
        if rows:
            cases.append({"autoid": aid, "steps": rows})
    if not cases:
        return None
    arch = f"{out_name}_unsuccessful"
    try:
        compile_emit_merged.func(cases_json=json.dumps(cases, ensure_ascii=False),
                                 out_name=arch)
    except Exception:  # noqa: BLE001
        logger.debug("未通过卷合并失败", exc_info=True)
        return None
    src = sh.outputs_root() / arch / "case.xlsx"
    if not src.is_file():
        return None
    import shutil
    dst = sh.outputs_root() / out_name / "unsuccessful_cases.xlsx"
    try:
        shutil.move(str(src), str(dst))
        shutil.rmtree(sh.outputs_root() / arch, ignore_errors=True)
        return str(dst)
    except Exception:  # noqa: BLE001
        return None


def _volume_composition_check(main_xlsx, deliverable: list) -> tuple[list, list]:
    """交付主卷组成对账(item2,§11.9 扩展,恢复设计符合性):交付 case.xlsx 实际 autoid 集
    vs deliverable 集。设计承诺「deliverable N == case.xlsx 内容」——止损转 failed_terminal/
    被 G3 封堵但未经新 merge 剔除的案会滞留物理卷(778041 实证 23≠22),即 swallowed verdict。
    返回 (leaked, absent):leaked=卷含非交付案;absent=deliverable 案缺席物理卷。任一非空=违约。
    卷读不出 autoid(读失败/非数字特殊卷)→ ([], [])(宁漏勿杀,同 _xlsx_real_autoids 契约)。"""
    from main.ist_core.tools.device.batch_tools import _xlsx_real_autoids
    try:
        vol = set(_xlsx_real_autoids(str(main_xlsx)))
    except Exception:  # noqa: BLE001
        vol = set()
    if not vol:
        return [], []
    dset = set(deliverable)
    return sorted(vol - dset), sorted(dset - vol)


def _attribution_observations(fs: list[dict], aid: str) -> list[dict]:
    """attributor 结构化观察 → 行为候选(A2′ 绑 C5 的生产侧兜底)。

    behavior_candidates 是 attributor **自愿**调 submit_behavior_fact 的产物——
    777976/593516 型最富信息的案恰好从不自愿登记;它们的归因 verbatim 证据
    (过了 submit_attribution 子串门)是仅存的设备观察,机械转候选抢救入库。
    观察级判据在此兑现:
    - verbatim 证据在:evidence 非空且 ≠"user"(用户裁决记账不是设备观察);
    - 源窗口 ok:该归因对应的 verdict 是 pass/fail(broken/not_run 轮的"观察"
      骑在失真窗口上,(43) 吸收态不产观察)。
    锚命令=失败断言的来源观测步(crash-gate 保证 check_point 前必有不带 H 的观测步;
    取最后一个 check_point 前最近者)。卷面读不出/无断言=无锚,如实 no-op——
    行为知识必须挂真实观测命令(merger 门),猜锚=知识挂错节点误导检索。
    信噪:defect_candidate 表单(actual=行为陈述,价值最高)全收;
    普通归因只收最新一轮 evidence(每案 ≤1 条,防多轮 churn 刷库)。
    """
    rows = _load_case_rows(aid)
    anchor = ""
    for i, r in enumerate(rows):
        if str(r.get("E")) == "check_point":
            for r2 in reversed(rows[:i]):
                e2, f2 = str(r2.get("E")), str(r2.get("F") or "")
                if e2 != "check_point" and "config" not in f2:
                    g2 = str(r2.get("G") or "").strip()
                    anchor = g2.splitlines()[-1].strip() if g2 else ""
                    break
    if not anchor:
        return []
    mine = [f for f in fs if str(f.get("aid")) == aid]
    verdicts = {str(v.get("run_id")): v for v in mine if v.get("ev") == "verdict"}
    atts = [f for f in mine if f.get("ev") == "attribution"]
    out: list[dict] = []
    for i, att in enumerate(atts):
        ev = str(att.get("evidence") or "")
        if not ev or ev == "user":
            continue
        v = verdicts.get(str(att.get("run_id") or ""))
        if v is not None and v.get("result") not in ("pass", "fail"):
            continue
        dc = att.get("defect_candidate")
        if isinstance(dc, dict) and str(dc.get("actual") or "").strip():
            out.append({"observe_cmd": anchor, "content": str(dc["actual"]).strip(),
                        "note": ("defect-candidate 轮观察:"
                                 + str(att.get("fix_direction") or "")[:80])})
        elif i == len(atts) - 1:
            out.append({"observe_cmd": anchor, "content": ev,
                        "note": str(att.get("fix_direction") or "")[:120]})
    return out


class _UncertainLed:
    """closing→入库器适配(A2′ 观察级判据换轴):案终态不作准入白名单。

    - deliverable 排除:其候选走 _promote 的 verified 晋升通道,不降格 uncertain;
    - broken 三态排除:源窗口失真((43)),失真窗口上的"观察"不是观察——
      run13 三条 config 泄漏观察骑在窗口失真上、事后撤销+6 份先例隔离的前科;
    - 其余(suspended/failed/contradicted/terminal/escalated/subset_verified/…)
      全部入源,状态只翻译成 observed_under 语境短句。
    """

    _CTX = {V.S_SUSPENDED: "挂起轮观察", V.S_TERMINAL: "止损收尾轮观察",
            V.S_ESCALATED: "升级轮观察", V.S_CONTRADICTED: "矛盾轮观察",
            V.S_FAILED: "fail 轮观察"}
    data = {"audit": {"notes": []}}

    def __init__(self, vw: dict, fs: list[dict]):
        self._vw, self._fs = vw, fs

    def observation_cases(self) -> list[tuple[str, str]]:
        skip = {V.S_DELIVERABLE, V.S_BROKEN, V.S_BROKEN_ERRORED, V.S_BROKEN_BLOCKED}
        return [(a, self._CTX.get(str(c["status"]), "fail/escalated 轮观察"))
                for a, c in self._vw["cases"].items() if c["status"] not in skip]

    def extra_candidates(self, aid: str) -> list[dict]:
        return _attribution_observations(self._fs, aid)


def _collect_defect_candidates(fs: list[dict], vw: dict, manifest: dict,
                               last_run: dict[str, dict] | None = None) -> list[dict]:
    """缺陷候选单汇总(P0 C20:submit_attribution 结构化表单的唯一交付出口)。

    此前全链湮灭:表单只落 last_run.json._attribution.defect_candidate → attribute
    收账不抄 → closing 删 last_run → 全 repo 零消费者,render 文案"已记入缺陷候选单"
    说谎。目标集=任意轮达 defect_candidate 的案(N1 floor:含后轮被弱处置覆盖的——
    517027 型 r2 真缺陷主张不再消失),排除最终 deliverable(换形态 PASS 证伪了缺陷
    假设:a pass certifies it was a form problem)。claim 级列全史(F.strong_claims),
    表单字段(repro/expected_with_source/actual/version/ticket_id)原样透传。

    在途批兼容(2026-07-16 硬要求):老 run 收账的 dc attribution 行**无** form 字段
    (旧代码只抄 5 字段),表单还躺在盘上 last_run.json(closing 删除前)——form 缺时
    从 last_run 记录回读补齐(zhaiyq 532862 续跑收口即此路径,活体验收点)。
    """
    mcases = {str(c.get("autoid")): c for c in (manifest.get("cases") or [])}
    out: list[dict] = []
    for aid, c in sorted(vw["cases"].items()):
        if c["status"] == V.S_DELIVERABLE:
            continue
        mine = [f for f in fs if str(f.get("aid")) == aid]
        atts = [f for f in mine if f.get("ev") == "attribution"]
        dcs = [a for a in atts if str(a.get("disposition")) == "defect_candidate"]
        if not dcs:
            continue
        form = next((a.get("defect_candidate") for a in reversed(dcs)
                     if isinstance(a.get("defect_candidate"), dict)), None)
        if form is None and last_run:
            _att = ((last_run.get(aid) or {}).get("_attribution") or {})
            if (str(_att.get("disposition")) == "defect_candidate"
                    and isinstance(_att.get("defect_candidate"), dict)):
                form = _att["defect_candidate"]
        claims = [cl for cl in F.strong_claims(mine, aid)
                  if cl["disposition"] == "defect_candidate"]
        trail = [{"round": int(a.get("round") or 0),
                  "disposition": str(a.get("disposition") or ""),
                  "by_user": str(a.get("evidence")) == "user"} for a in atts]
        out.append({
            "autoid": aid,
            "title": str((mcases.get(aid) or {}).get("title") or ""),
            "status": str(c["status"]),
            "user_confirmed": any(str(a.get("evidence")) == "user" for a in dcs),
            "layer": str(dcs[-1].get("layer") or ""),
            "claims": claims,
            "latest_claim": str(dcs[-1].get("fix_direction") or ""),
            "latest_evidence": str(dcs[-1].get("evidence") or ""),
            "form": form,
            "disposition_trail": trail,
        })
    return out


def closing(state: dict) -> dict:
    """收口(§11.2/11.5/11.9):uncertain 入库(自愈环)→ 缺陷候选单 → 机读报告 →
    判定式人话双报告(零 LLM,leak_scan 门)→ 未通过卷 xlsx → §11.9 清理(通过案目录删/
    未决案挪 unfinished/ 供续跑/facts 永久保留)→ 交付对账断言 → 收口卡。"""
    from main.ist_core.compile_engine_v8 import render as RD
    fs = sh.load_facts(state)
    vw = sh.view(state, fs)
    # 收口前置门兜底(回归#2 修 B,§16 批末必有聚合点 / §18.2 式③不静默):到 closing
    # 仍有未答欠定案(post-ask 路径 dismiss/非交互零答,或流失于极端错误)——落显式
    # awaiting_user_unasked 事实,禁静默吞。区分「从没被问」(无 ask_shown)与「问过没答」。
    _await = [a for a, c in vw["cases"].items() if c["status"] == V.S_AWAITING_USER]
    _already = {str(f.get("aid")) for f in fs if f.get("ev") == "awaiting_user_unasked"}
    _await = [a for a in _await if a not in _already]
    if _await:
        _shown = {str(f.get("aid")) for f in fs if f.get("ev") == "ask_shown"}
        _never = [a for a in _await if a not in _shown]
        sh.append(state, [{"ev": "awaiting_user_unasked", "aid": a,
                           "shown": a in _shown,
                           "reason": ("decision panel shown but left unanswered "
                                      "(dismissed/non-interactive)" if a in _shown else
                                      "reached closing without being shown a decision panel")}
                          for a in _await])
        fs = sh.load_facts(state)
        if _never:
            sh.emit(f"⚠ {len(_never)} 个欠定案收口前从未被问到——已如实入账(非静默),"
                    "下批同参可续问")
    out_name = str(state.get("out_name"))
    mdir = sh.outputs_root() / out_name
    # 自愈环:非 pass 案观察 uncertain 入库(A2′ 观察级判据换轴,2026-07-16——
    # 旧 _Led 按 {failed_terminal, escalated} 终态枚举,挂起/failed/contradicted 案的
    # defect_candidate 级观察整体丢弃,zhaiyq 532862 实证)
    try:
        from main.ist_core.compile_engine_v8.uncertain import _ingest_uncertain_observations
        _ingest_uncertain_observations(_UncertainLed(vw, fs))
    except Exception:  # noqa: BLE001
        logger.debug("uncertain 入库失败", exc_info=True)

    # 批后床态收敛(X11:谁弄脏谁收拾——快照 diff→己方交叉验证→机械逆放→残余入账)
    bed_note = ""
    try:
        host = str(state.get("bed_host") or "")
        before = sh.read_json(mdir / "bed_before.json", None)
        if host and isinstance(before, dict):
            after = B.bed_snapshot(_probe_fn)
            diff = B.bed_diff(before, after)
            # 平台基线面(snapshot_only:接口地址等)的漂移剥离出自动恢复通路——
            # 只呈报/入账,绝不生成删除命令(run18 实弹:批前探针截断致基线地址被
            # 误判漂移,险些删掉 port2 管理 IP;这类面由框架 IP 恢复契约管理,引擎越界)
            diff, observe_only = B.restorable_diff(diff)
            if observe_only:
                sh.emit("平台基线面漂移(接口地址等)仅呈报不自动恢复:"
                        + "、".join(observe_only.keys()))
            if diff or observe_only:
                lr = sh.read_json(sh.project_root() / str(state.get("last_run_ref") or ""),
                                  []) or []
                corpus = "\n".join(str(r.get("device_context") or "") for r in lr
                                   if isinstance(r, dict))
                # S4 兑现②(#76,run18 根因修复):己方判据=案面 config 命令里有创建该
                # 对象的命令(而非旧 own_writes 的「token 在 corpus 文本出现」——被 dig
                # 访问污染,误把 port2 判己方致删基线);pairs 空则全归 foreign(保守)
                config_cmds = B.parse_config_commands(corpus)
                pairs = B._inverse_pairs()
                own, foreign = B.own_writes_by_command(diff, config_cmds, pairs)
                # 基线面漂移并入 foreign(只报不动,INV-9)——入账供下批 bed_gate 呈报
                for name, d in observe_only.items():
                    foreign[name] = d
                # C1 维护通道:人工修床已登记的写 ≠ 案残留 ≠ 非己方漂移(run12
                # 五次修床被判 foreign 误告警的封堵)——分流只标注,不动手
                foreign, maintained = B.split_maintained(
                    foreign, B.maintenance_tokens(sh.project_root(), host))
                # 恢复命令:**机械逆放先行**(从案面创建命令取 no 逆元,零 LLM 零模板;
                # 作用域恒等于原命令,天然不越界)——机械派生不出的残余(inverse_forms
                # 缺 no 逆元)才走 LLM 后备,过实体越界门+执行后复探验证双门
                cmds, rejected = [], []
                if own:
                    cmds, residual_own = B.restore_mechanical(own, config_cmds, pairs)
                    if residual_own:
                        raw = B.restore_via_llm(residual_own, _bed_llm_fn)
                        llm_ok, rejected = B.entity_gate(raw, residual_own)
                        cmds = cmds + llm_ok
                if cmds:
                    for c in cmds:
                        _exec_fn(c)
                # residual 也剥离 snapshot_only:否则重拍 diff 会再引入基线面假漂移并
                # bed_record 入账,下批 bed_gate 床账接力(另一条 restore 路径)又删它
                if cmds:
                    residual, _ = B.restorable_diff(
                        B.bed_diff(before, B.bed_snapshot(_probe_fn)))
                elif own:
                    residual = {k: v for k, v in diff.items() if k in own}  # diff 已剥离
                else:
                    residual = {}
                verified = [c for c in cmds] if cmds and not residual else []
                for name, d in residual.items():
                    B.bed_record(sh.project_root(), host, "created", name,
                                 f"{state.get('out_name')}:{name}",
                                 batch=str(state.get("out_name") or ""),
                                 payload={"commands": [], "added": d.get("added"),
                                          "removed": d.get("removed")})
                parts = []
                if verified:
                    parts.append(f"己方漂移已恢复(验证通过,{len(verified)} 条随账可复用)")
                elif cmds:
                    parts.append(f"恢复执行 {len(cmds)} 条但复探未清零")
                if rejected:
                    parts.append(f"{len(rejected)} 条越界命令被门拒")
                if residual:
                    parts.append(f"{len(residual)} 通道残余入床账(下批接力)")
                if maintained:
                    parts.append(f"{len(maintained)} 通道为已登记的维护写(已解释)")
                if foreign:
                    parts.append(f"{len(foreign)} 通道非己方漂移(只报不动,INV-9)")
                bed_note = ";".join(parts)
                sh.emit(f"批后床态收敛:{bed_note or '干净'}")
    except Exception:  # noqa: BLE001
        # INV-11 式②(坑#12):床态收敛整块失败曾完全无痕——54% T1 根治线的失败
        # 模式必须入账;下批 bed_gate 读到该事实转 needs_ask(床态未知)
        logger.warning("批后床态收敛失败", exc_info=True)
        try:
            sh.append(state, [{"ev": "bed_closure_failed", "aid": "",
                               "host": str(state.get("bed_host") or ""),
                               "reason": "post-batch bed convergence crashed; bed state unknown"}])
            sh.emit("⚠ 批后床态收敛失败——床态未知,已入账(下批体检将呈报)")
        except Exception:  # noqa: BLE001
            logger.error("bed_closure_failed 入账也失败", exc_info=True)

    deliverable = [a for a, c in vw["cases"].items() if c["status"] == V.S_DELIVERABLE]
    others = {a: c for a, c in vw["cases"].items() if c["status"] != V.S_DELIVERABLE}
    # G3 污染者交付门(§17,(40)/(35) 对象×过程链接缝):卷面自身带无 τ 的网络层写的
    # 案,pass 也不入交付卷——「每次执行都拆床的卷」交付出去=把污染批发给所有
    # 未来使用者(run12 实测 655203 subset pass 差点带病交付)。呈报式:落
    # delivery_blocked 事实+挪入未通过卷,报告如实声明,非静默剔除。
    _blocked: list[str] = []
    for aid in list(deliverable):
        try:
            from main.case_compiler.tau_coverage import check_tau_coverage
            _tr = check_tau_coverage(_load_case_rows(aid))
            if not _tr.ok:
                _blocked.append(aid)
        except Exception:  # noqa: BLE001
            continue
    if _blocked:
        sh.append(state, [{"ev": "delivery_blocked", "aid": a,
                           "reason": "missing in-case teardown for network-layer writes",
                           "run_id": f"g3:{a}"} for a in _blocked])
        fs = sh.load_facts(state)
        # 状态改写必须落到 vw["cases"] 本体并重算 counts——report 的 cases/totals
        # 都引用 vw,只改 others 副本会让报告继续把封堵案算进通过数(G5 即拦此形态)
        from collections import Counter as _Counter
        for a in _blocked:
            vw["cases"][a] = {**vw["cases"][a], "status": "delivery_blocked"}
            others[a] = vw["cases"][a]
            deliverable.remove(a)
        vw["counts"] = dict(_Counter(str(v["status"]) for v in vw["cases"].values()))
        sh.emit(f"污染者交付门:{len(_blocked)} 案 pass 但卷面缺案尾清理——"
                f"不入交付卷(重编补自清后可交付)")
    mf = [f for f in fs if f.get("ev") == "merged"]
    moved = list(mf[-1].get("moved_tail") or []) if mf else []
    coexist = list(mf[-1].get("coexist_violations") or []) if mf else []
    # 缺陷候选单(P0 C20):在删 last_run 之前汇总——表单已随 attribute 收账进事实流,
    # 此处从 facts 投影(与报告同一 fold,渲染零 LLM);在途批(老 run 收账无表单字段)
    # 从盘上 last_run.json 回读兜底(532862 型续跑收口)
    _lr_recs: dict[str, dict] = {}
    for _rec in (sh.read_json(mdir / "last_run.json", []) or []):
        if isinstance(_rec, dict) and _rec.get("autoid"):
            _lr_recs[str(_rec["autoid"])] = _rec
    dc_entries = _collect_defect_candidates(fs, vw, sh.manifest(state), last_run=_lr_recs)
    report = {
        "engine": "v8",
        "outcome": ("delivered_all_pass" if not others else "delivered_with_labels"),
        "totals": {"cases": len(vw["cases"]), **vw["counts"],
                   "deliverable": len(deliverable)},
        "volume": vw.get("volume"),
        "moved_tail": moved, "coexist_violations": coexist,
        "bed": {"host": state.get("bed_host"), "device_build": state.get("device_build"),
                "closure": bed_note},
        "cases": vw["cases"],
        "refs": {"facts": state.get("facts_ref"), "merged": state.get("merged_ref")},
    }
    if dc_entries:
        report["defect_candidates"] = {"count": len(dc_entries),
                                       "autoids": [e["autoid"] for e in dc_entries]}
    (mdir / "engine_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 判定式人话双报告(同一 fold;panel/evidence 从事实引用回读;queues=D 片接缝)
    m = sh.manifest(state)
    panels: dict[str, dict] = {}
    evidence: dict[str, str] = {}
    for aid in others:
        mine = [f for f in fs if f.get("aid") == aid]
        panel, _ = _latest_panel(mine, aid)
        if panel:
            panels[aid] = panel
        last = F.latest_verdict(mine, aid)
        if last and last.get("result") == "fail":
            data = sh.read_json(sh.project_root() / str(last.get("evidence_ref") or ""), []) or []
            rec = next((r for r in data if str(r.get("autoid")) == aid), {})
            evidence[aid] = str(rec.get("device_context") or "")
    # 修法队列接线(V8.5 片4:§11.7 队列头=唯一导出修法,报告陈述句不设选项)
    from main.ist_core.compile_engine_v8 import remedies as RM
    _maxr = int(state.get("max_rounds") or 3)
    queues: dict[str, list] = {
        aid: RM.derive_queue(fs, vw, aid, _maxr, sh.granted_rounds(fs, aid))
        for aid in others}
    # R5 两布尔度量(§14-R5/§16.3:随裁决机械回填,零额外问询成本):
    # effective=裁决后该案达成终局(交付/按裁决收尾/挂起),未达=选项没解决问题;
    # freeform=用户走了 Other 自由输入(引擎选项不适配的信号,R5①题面质量代理)。
    _oc_facts = []
    for f in fs:
        if f.get("ev") != "decision" or not f.get("answer"):
            continue
        aid = str(f.get("aid"))
        st = str((vw["cases"].get(aid) or {}).get("status") or "")
        settled = st in (V.S_DELIVERABLE, V.S_TERMINAL, V.S_SUSPENDED, V.S_ESCALATED)
        _oc_facts.append({"ev": "decision_outcome", "aid": aid,
                          "question_id": f.get("question_id"),
                          "effective": bool(settled),
                          "freeform": bool(f.get("freeform"))})
    if _oc_facts:
        sh.append(state, _oc_facts)
        fs = sh.load_facts(state)
        report["totals"]["ask"] = {
            "answered": len(_oc_facts),
            "effective": sum(1 for x in _oc_facts if x["effective"]),
            "freeform": sum(1 for x in _oc_facts if x["freeform"])}
        (mdir / "engine_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    dmd = RD.render_delivery_report(report, fs, m, queues, panels)
    # G5 报告重算门(§17,(42) 报告保真):独立路径从 facts 重算计数与终态陈述,
    # 与 engine_report+人话报告逐项比对;失配=拒绝交付+告警(名义 26/26 前科封堵)
    from main.ist_core.compile_engine_v8 import report_gate as RG
    g5_issues, g5_detail = RG.check_report(report, dmd, fs, m)
    if g5_issues:
        (mdir / "REPORT_MISMATCH.json").write_text(
            json.dumps({"issues": g5_issues, "detail": g5_detail},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        report["outcome"] = "report_mismatch"
        (mdir / "engine_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        dmd = RG.mismatch_banner(g5_issues) + dmd
        sh.append(state, [{"ev": "report_mismatch", "aid": "",
                           "issues": g5_issues, "run_id": "g5"}])
        fs = sh.load_facts(state)
        logger.warning("G5 报告重算门失配:%s", g5_issues)
        sh.emit(f"⚠ 报告重算门:发现 {len(g5_issues)} 处报告与事实台账不一致,"
                f"本批暂不可作为交付依据(详见 REPORT_MISMATCH.json)")
    (mdir / "delivery_report.md").write_text(dmd, encoding="utf-8")
    deliver_files = ["case.xlsx", "delivery_report.md", "engine_report.json", "facts.jsonl"]
    # 缺陷候选单双文件(P0 C20):json 机读原样、md 人话渲染;进 deliver_files 走
    # 交付对账断言(报告说有=盘上真有)。写在 §11.9 清理与删 last_run 之前。
    if dc_entries:
        try:
            (mdir / "defect_candidates.json").write_text(
                json.dumps(dc_entries, ensure_ascii=False, indent=2), encoding="utf-8")
            (mdir / "defect_candidates.md").write_text(
                RD.render_defect_candidates_md(dc_entries, m), encoding="utf-8")
            deliver_files += ["defect_candidates.md", "defect_candidates.json"]
            sh.emit(f"缺陷候选单:{len(dc_entries)} 案已汇总(defect_candidates.md,"
                    f"含结构化表单与处置轨迹)")
        except Exception:  # noqa: BLE001
            # 产出失败不静默:不加入 deliver_files(对账不报缺),但显式告警
            logger.warning("缺陷候选单产出失败", exc_info=True)
            sh.emit("⚠ 缺陷候选单产出失败——结构化表单仍在 facts.jsonl 可审计")
    if others:
        umd = RD.render_unsuccessful_md(report, fs, m, queues, evidence, panels)
        (mdir / "unsuccessful_cases.md").write_text(umd, encoding="utf-8")
        if _archive_unsuccessful(sorted(others), out_name):
            deliver_files.append("unsuccessful_cases.xlsx")
        deliver_files.append("unsuccessful_cases.md")
        leaks = RD.leak_scan(dmd) + RD.leak_scan(umd)
        if leaks:
            logger.warning("报告术语泄漏(渲染门):%s", sorted(set(leaks))[:8])

    # §11.9 清理:per-case 目录全部收进批目录(outputs/ 根不留散目录)——
    # 通过案挪 delivered/(挂起案恢复后终验重组全卷时,merge 仍需其 xlsx,删=断链)、
    # 未通过/挂起案挪 unfinished/(续跑输入);两者 prep 开工都还原。
    # 中间件 manifest/last_run/__sub* 删;facts.jsonl 永久保留。
    import shutil

    def _stash(aids, sub: str) -> None:
        box = mdir / sub
        for aid in aids:
            src = sh.outputs_root() / aid
            if not src.is_dir():
                continue
            box.mkdir(exist_ok=True)
            dst = box / aid
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            try:
                shutil.move(str(src), str(dst))
            except Exception:  # noqa: BLE001
                logger.debug("%s 挪移失败 %s", sub, aid, exc_info=True)

    for d in sh.outputs_root().glob(f"{out_name}__sub*"):
        shutil.rmtree(d, ignore_errors=True)
    _stash(deliverable, "delivered")
    _stash(others, "unfinished")
    for name in ("manifest.json", "last_run.json"):
        try:
            (mdir / name).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    # item2 主卷组成对账门(§11.9 扩展,方案 b:纯加门,不碰 merge 元数据不变量):交付主卷
    # case.xlsx=最后 delivery merge 物理卷,可能含"止损转 failed_terminal/G3 封堵但未经新
    # merge 剔除"的案(778041 实证 23≠22)。核对实际组成 vs deliverable——设计承诺
    # 「deliverable N == case.xlsx 内容」,失配=swallowed verdict→落事实 + outcome 如实降级
    # (不静默交付超集卷)。重合并纠正(方案 a,涉 moved_tail/coexist 重设计)留行为修复专项轮。
    _leaked, _absent = _volume_composition_check(mdir / "case.xlsx", deliverable)
    if _leaked or _absent:
        logger.warning("主卷组成对账失配:泄漏=%s 缺失=%s", _leaked[:8], _absent[:8])
        sh.append(state, [{"ev": "volume_composition_mismatch", "aid": a, "kind": k,
                           "reason": r, "run_id": f"g_compose:{k}:{a}"}
                          for a, k, r in (
                              [(x, "leaked", "case.xlsx 含非 deliverable autoid(止损/G3 后未剔除)")
                               for x in _leaked]
                              + [(x, "absent", "deliverable 案缺席交付主卷 case.xlsx")
                                 for x in _absent])])
        if str(report.get("outcome", "")).startswith("delivered"):
            report["outcome"] = "delivery_incomplete"
        report["volume_composition_mismatch"] = {"leaked": _leaked, "absent": _absent}
        try:
            (mdir / "engine_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        sh.emit(f"⚠ 主卷组成对账失配(泄漏 {len(_leaked)}/缺失 {len(_absent)};尾号 "
                + "、".join(a[-6:] for a in (_leaked + _absent)[:4]) + ")——收口结论如实降级")

    # 交付对账断言(§11.9:报告说有=盘上真有)+ 收口卡
    missing = [f for f in deliver_files if not (mdir / f).is_file()]
    if missing:
        # 坑#26:报告说有=盘上真有,失配不再只是 warning——outcome 降级如实声明
        logger.warning("交付物清单与磁盘不一致:缺 %s", missing)
        if str(report.get("outcome", "")).startswith("delivered"):
            report["outcome"] = "delivery_incomplete"   # report_mismatch 更严重,不覆盖
        try:
            (mdir / "engine_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        sh.emit(f"⚠ 交付物缺失({', '.join(missing)})——收口结论降级为交付不完整")
    # G4 echo 入收口卡(§18.6 坑#21:此前仅流水行,收口卡无痕):每条用户裁决带
    # 「引擎理解为」复述,截断/兜底误判在收口卡上可核对
    _decision_echo = _g4_decision_echoes(fs)
    sh.emit_summary(state, {
        "outcome": report["outcome"],
        "decisions": _decision_echo,
        "ok": len(deliverable), "total": len(vw["cases"]),
        "labels": [{"autoid": a, "text": RD.STATUS_CN.get(str(c["status"]), str(c["status"]))}
                   for a, c in sorted(others.items())],
        "report": f"workspace/outputs/{out_name}/delivery_report.md",
        "files": deliver_files, "missing": missing,
        "report_mismatch": bool(g5_issues),
    })
    sh.emit(f"交付:{len(deliverable)}/{len(vw['cases'])} 可交付"
            + (f",{len(others)} 案带标注" if others else "")
            + f" · 交付物 {len(deliver_files)} 件已核对")
    sh.emit_tick(state, "closing", fs)
    return {"phase_status": "done", **sh.counts_update(state, fs)}
