"""V8 节点共享底座:路径/事实流装载/视图缓存/指纹/进度 emit/fork 执行器。

V6 差异:无 ledger——真理=事实流,计数=视图现算(counts_update 吃 batch_view)。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import views as V

logger = logging.getLogger(__name__)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def outputs_root() -> Path:
    return project_root() / "workspace" / "outputs"


def facts_path(state: dict) -> Path:
    ref = str(state.get("facts_ref") or "")
    if ref:
        return project_root() / ref
    return outputs_root() / str(state.get("out_name") or "engine") / "facts.jsonl"


def load_facts(state: dict) -> list[dict]:
    return F.load_facts(facts_path(state))


def append(state: dict, new_facts: list[dict]) -> int:
    return F.append_facts(facts_path(state), new_facts)


def manifest(state: dict) -> dict:
    return read_json(project_root() / str(state.get("manifest_ref") or ""), {}) or {}


def view(state: dict, fs: list[dict] | None = None) -> dict:
    return V.batch_view(fs if fs is not None else load_facts(state), manifest(state))


def case_rows(aid: str) -> list[dict]:
    """卷面行(未通过卷合并用;失败返回空,判定保守)。"""
    from main.ist_core.tools.device.precedent_tools import _load_case_rows as _l
    p = outputs_root() / aid / "case.xlsx"
    try:
        return _l(str(p)) if p.is_file() else []
    except Exception:  # noqa: BLE001
        return []


def emit_summary(state: dict, summary: dict) -> None:
    """收口卡事件(TUI §11.2:「交付结果」卡一屏讲完;字段已是渲染层人话)。"""
    try:
        from main.ist_core.skills.loader import _fork_emit_event
        _fork_emit_event({"event": "engine_summary",
                          "run": str(state.get("out_name") or "engine"), **summary})
    except Exception:  # noqa: BLE001
        logger.debug("engine summary emit 失败", exc_info=True)


def cap_waiting(fs: list[dict]) -> list[str]:
    """轮次封顶待授权案:cap_reached 事实存在且该轮 cap 问题未获 decision(§11.7 资源问询)。"""
    out = []
    for f in fs:
        if f.get("ev") != "cap_reached":
            continue
        aid, rnd = str(f.get("aid")), int(f.get("round") or 0)
        qid = f"cap:{aid}:{rnd}"
        if not any(d.get("ev") == "decision" and d.get("question_id") == qid for d in fs):
            if aid not in out:
                out.append(aid)
    return out


def granted_rounds(fs: list[dict], aid: str) -> int:
    """用户已授权的追加轮次(cap 问询答「继续」每次 +2;token 优先,兼容早期无 token 事实)。

    cap-correct 同计(接线包 2g,2026-07-16):cap 题面 Other 纠正意见=「带我的纠正
    继续修」——授权轮次+纠正原文经 briefs 注入重编;不计则 correct 决策落账可见但
    永不行动(诚实降级但用户意见被闲置)。"""
    n = 0
    for f in fs:
        if (f.get("ev") == "decision" and str(f.get("aid")) == aid
                and str(f.get("question_id", "")).startswith("cap:")):
            tok = str(f.get("token") or "")
            if tok in ("continue", "correct") or (not tok and "继续" in str(f.get("answer", ""))):
                n += 2
    return n


def env_confirm_waiting(fs: list[dict], vw: dict) -> list[str]:
    """归因器自判 env_blocked 待用户确认的案(§11.7:止损归用户,引擎无单方终结权)。

    最新归因为 env_blocked 且非用户来源、且该判断未获 decision → 进 ask 边。"""
    out = []
    for aid, c in vw["cases"].items():
        if c["status"] in (V.S_DELIVERABLE, V.S_TERMINAL, V.S_SUSPENDED, V.S_ESCALATED):
            continue
        mine = [f for f in fs if str(f.get("aid")) == aid]
        atts = [f for f in mine if f.get("ev") == "attribution"]
        if not atts or str(atts[-1].get("disposition")) != "env_blocked":
            continue
        if V._user_sourced(atts[-1]):
            continue
        qid = f"env:{aid}:{int(atts[-1].get('round') or 0)}"
        if not any(d.get("ev") == "decision" and d.get("question_id") == qid for d in mine):
            out.append(aid)
    return out


def panel_waiting(fs: list[dict], vw: dict) -> list[str]:
    """归因孔呈报的 ought-欠定面板待答案(§11.11:panel 事实存在且该轮未获 decision
    也未被同键判例机械采信——adopted 即免问,收敛律的采信面)。"""
    out = []
    for f in fs:
        if f.get("ev") != "ask_panel":
            continue
        aid = str(f.get("aid"))
        rnd = int(f.get("round") or 0)
        c = vw["cases"].get(aid)
        if not c or c["status"] in (V.S_DELIVERABLE, V.S_TERMINAL, V.S_SUSPENDED,
                                    V.S_ESCALATED):
            continue
        qid = f"panel:{aid}:{rnd}"
        answered = any(d.get("ev") == "decision" and d.get("question_id") == qid
                       for d in fs)
        adopted = any(d.get("ev") == "adopted" and str(d.get("aid")) == aid
                      and int(d.get("round") or 0) == rnd for d in fs)
        if not answered and not adopted and aid not in out:
            out.append(aid)
    return out


def suspended_resume_waiting(fs: list[dict], vw: dict) -> list[str]:
    """挂起案跨批恢复问询:新批(run_start 在最后 suspended 之后)开工时问一次
    「恢复处理/保持挂起」——同批内挂起后绝不再问(挂起=本批不打扰)。"""
    n_runs = sum(1 for f in fs if f.get("ev") == "run_start")
    out = []
    for aid, c in vw["cases"].items():
        if c["status"] != V.S_SUSPENDED:
            continue
        idx_susp = max((i for i, f in enumerate(fs)
                        if f.get("ev") == "suspended" and str(f.get("aid")) == aid),
                       default=-1)
        if idx_susp < 0 or not any(f.get("ev") == "run_start" for f in fs[idx_susp + 1:]):
            continue
        qid = f"resume:{aid}:{n_runs}"
        if not any(d.get("ev") == "decision" and d.get("question_id") == qid
                   and str(d.get("aid")) == aid for d in fs):
            out.append(aid)
    return out


def bed_treatment_waiting(fs: list[dict], vw: dict) -> list[str]:
    """s₀ 停车案待呈报(V8.5 片3;§11.7:唯一可行修法=床治理,床权在用户——必问,
    redline 实证缺口②的修复):批级诊断判 h_s0 ∧ 复跑处方(复跑闸已挡) ∧ 本次
    诊断未获裁决 → 进 ask 边。未答自动挂起(既有安全件),不静默停车。"""
    out = []
    for aid, c in vw["cases"].items():
        if c["status"] not in (V.S_FAILED, V.S_CONTRADICTED):
            continue
        mine = [f for f in fs if str(f.get("aid")) == aid]
        diag = [f for f in mine if f.get("ev") == "diagnosis"]
        if not diag or not str(diag[-1].get("h_position", "")).startswith("h_s0"):
            continue
        atts = [f for f in mine if f.get("ev") == "attribution"]
        if not atts or str(atts[-1].get("disposition")) not in ("rerun_isolated",
                                                                "transient"):
            continue
        qid = f"bed:{aid}:{len(diag)}"
        if not any(d.get("ev") == "decision" and d.get("question_id") == qid
                   for d in fs):
            out.append(aid)
    return out


def ask_targets(state: dict, fs: list[dict], vw: dict) -> dict:
    """ask 边目标(§11.11 构件六;B 片再加采信失败队列):
    panel = 归因孔 ought-欠定呈报待确认;contra = 矛盾≥2 且本次矛盾未获裁决;
    cap = 轮次封顶待授权(有 panel 呈报之/无则工程故障呈报——二分在题面层);
    env = 归因器止损判断待确认;bed = s₀ 停车案床治理呈报(片3);
    suspended = 挂起案新批恢复问询。"""
    contra = []
    for aid, c in vw["cases"].items():
        if c["status"] == V.S_CONTRADICTED and c["contradictions"] >= 2:
            qid = f"contra:{aid}:{c['contradictions']}"
            if not any(d.get("ev") == "decision" and d.get("question_id") == qid
                       for d in fs):
                contra.append(aid)
    return {"panel": panel_waiting(fs, vw), "contra": contra,
            "cap": cap_waiting(fs), "env": env_confirm_waiting(fs, vw),
            "bed": bed_treatment_waiting(fs, vw),
            "suspended": suspended_resume_waiting(fs, vw)}


def counts_update(state: dict, fs: list[dict] | None = None) -> dict:
    """视图 → 条件边计数缓存(INV-7:缓存;真理在事实流)。"""
    if fs is None:
        fs = load_facts(state)
    vw = view(state, fs)
    c = vw["counts"]
    t = ask_targets(state, fs, vw)
    _waiting = (set(t["panel"]) | set(t["contra"]) | set(t["cap"])
                | set(t["env"]) | set(t["bed"]) | set(t["suspended"]))
    return {
        "n_pending": c.get(V.S_PENDING, 0),
        "n_awaiting_user": c.get(V.S_AWAITING_USER, 0),
        "n_authored": c.get(V.S_AUTHORED, 0),
        "n_failed": c.get(V.S_FAILED, 0) + c.get(V.S_CONTRADICTED, 0),
        "n_subset_verified": c.get(V.S_SUBSET_VERIFIED, 0),
        "n_broken": c.get(V.S_BROKEN, 0),
        # pyATS 子类(§④):errored 走 reflow(reconcile→attribute→diagnose→author)、
        # blocked 走 env 呈报(reconcile 写机械 env_blocked 归因→env_confirm_waiting→ask)
        "n_broken_errored": c.get(V.S_BROKEN_ERRORED, 0),
        "n_broken_blocked": c.get(V.S_BROKEN_BLOCKED, 0),
        "n_deliverable": c.get(V.S_DELIVERABLE, 0),
        "n_contradicted": c.get(V.S_CONTRADICTED, 0),
        "n_settled_bad": (c.get(V.S_ESCALATED, 0) + c.get(V.S_TERMINAL, 0)
                          + c.get(V.S_SUSPENDED, 0)),
        # 去重计数(一个案可能同时命中 panel 与 cap,题面层合并成一题)
        "n_ask_contradiction": len(_waiting),
        # 可推进的失败案 = 失败/矛盾 且 不在任何问询等待集(run17 实弹:封顶/env/bed/
        # 挂起恢复等待案不算"有活",否则 ask 边被 merge 空转跳过;而 rerun 处方案必须
        # 算活,否则被「有未答题」吞掉——两个方向的实弹都在 §16.6)
        "n_failed_actionable": len(
            {a for a, cc in vw["cases"].items()
             if cc["status"] in (V.S_FAILED, V.S_CONTRADICTED)} - _waiting),
    }


# ── 指纹(裁决-卷面绑定的物理载体,INV-8) ─────────────────────────────────────


def artifact_fingerprint(aid: str) -> str:
    """单案卷面指纹:emit 凭证的 xlsx_mtime(工具层契约不变;无凭证=无指纹)。"""
    cred = read_json(outputs_root() / aid / ".grade_credential.json", {}) or {}
    mt = cred.get("xlsx_mtime")
    return f"{aid}:{mt}" if mt is not None else ""


def volume_fingerprint(pairs: list[tuple[str, str]]) -> str:
    """整卷组成指纹 = sorted (aid, artifact) 的 sha1(组成或任一卷面变即变)。"""
    blob = json.dumps(sorted(pairs), ensure_ascii=False)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


# ── 进度(TUI 契约与 V6 相同:fastlog 行 + engine_tick 事件) ────────────────────


def emit(text: str) -> None:
    """引擎进度 → 默认 EventBus(TUI 'evidence_added' → '· …' 行)。失败一律静默
    (进度不拖垮主流程)。原 compile_pipeline._emit_progress 归位于此(遗留壳随之删除)。"""
    try:
        from main.ist_core.events import get_default_bus
        get_default_bus().emit("evidence_added", payload={"text": f"[engine] {text}"})
    except Exception:  # noqa: BLE001
        logger.debug("engine 进度 emit 失败", exc_info=True)


# V8 内部 13 态 → footer 显示词汇的投影(显示契约与引擎词汇解耦,前端零改动消费)。
# 桶必须覆盖全部 13 个 case 状态、每态恰入一桶——否则桶和<total、案在 footer 凭空消失
# (活证 29906 round1:51<53,broken 三态漏投)。纯遥测,不碰编译行为。
# 2026-07-20 FOOTER-1:折桶按**状态语义**归位,不按"最近的非通过桶"将就——投影错位
# 让 footer 说谎(挂起报「失败」、死床报「编写中」),比漏投更难发现(桶和仍等于 total)。
# 测试锚:test_footer_projection_complete(全 13 态 → Σ桶==total,残差 0)。
def _footer_bucket_counts(c: dict) -> dict:
    return {
        "pending": c.get("pending", 0),
        "dispatched": 0,
        "produced": c.get("authored", 0) + c.get("subset_verified", 0),
        # suspended 是**非终态**(views.py:33:用户裁决挂起,下批同参续跑)——旧版折进
        # failed_terminal 让 footer 显示「失败N」,把可续跑的案报成死案(FOOTER-1)。
        # 归欠定桶:它确实卡在用户决策上,与 awaiting_user 同轴。
        "pending_decision": c.get("awaiting_user", 0) + c.get("suspended", 0),
        "awaiting_user": 0,
        "passed": c.get("deliverable", 0),
        # broken/broken_errored=非通过非终态、仍在编译环内(复跑/reflow)→ failed_active(待重跑)。
        "failed_active": (c.get("failed", 0) + c.get("contradicted", 0)
                          + c.get("broken", 0) + c.get("broken_errored", 0)),
        # broken_blocked=设备 ping 不通,复跑救不了(views.py:26)——折进 failed_active 会让
        # 死床显示「编写中N」(TUI 把 failed_active 计入编写中),等于报告一个不存在的进度。
        # 独立成桶:不属显示层五组任何一组,由 TUI 既有「其他N」残差桶浮现(FOOTER-1)。
        "broken": c.get("broken_blocked", 0),
        "failed_terminal": c.get("failed_terminal", 0),
        "escalated": c.get("escalated", 0),
    }


def emit_tick(state: dict, phase: str, fs: list[dict] | None = None) -> None:
    """引擎聚合 → events.jsonl(TUI 契约:V6 定稿的九态词汇,V8 视图标签在此翻译——
    显示契约与引擎内部词汇解耦,前端零改动消费)。"""
    try:
        from main.ist_core.skills.loader import _fork_emit_event
        vw = view(state, fs)
        _fork_emit_event({"event": "engine_tick",
                          "run": str(state.get("out_name") or "engine"),
                          "phase": phase, "round": int(state.get("vol_seq") or 0),
                          "wave": 0, "counts": _footer_bucket_counts(vw["counts"]),
                          "total": len(vw["cases"])})
    except Exception:  # noqa: BLE001
        logger.debug("engine tick emit 失败", exc_info=True)


def fork_executor(n_items: int):
    from main.ist_core.tools.device.batch_tools import _resolve_concurrency
    from main.ist_core.resilience import AdaptiveLimiter, ForkExecutor
    ceiling = _resolve_concurrency(0, n_items=max(1, n_items))
    limiter = AdaptiveLimiter(start=max(2, ceiling // 2), min_limit=1, max_limit=ceiling)
    wc = float(os.environ.get("IST_FORK_WALLCLOCK_S") or 900)
    return ForkExecutor(limiter, wallclock_s=wc), limiter, ceiling


def env_flag(name: str, default: str = "1") -> bool:
    """布尔环境开关(默认开;"0"/"false"/"no" 关)。回归锚:test_promote_env_flag_regression
    (曾缺失致 PASS 行为晋升被 debug-except 静默吞)。"""
    v = (os.environ.get(name) or default).strip().lower()
    return v not in ("0", "false", "no")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def signal(name: str, subject: str, **payload) -> None:
    try:
        from main.ist_core.memory.footprint.signals import emit_signal
        emit_signal(name, subject, source="engine_v8", **payload)
    except Exception:  # noqa: BLE001
        pass
