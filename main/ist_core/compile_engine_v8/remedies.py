# -*- coding: utf-8 -*-
"""修法导出队列(V8.5 片4=原 D 片;§11.7:「案进 ask 的机械前提=导出修法队列为空;
队列非空禁 ask,继续自愈环」)。

本模块把引擎既有路由决策**显式化为数据**(不新增行动——每个 action 都是图上
已存在的合法通路,X7 能力原语表),供两处消费:
① 报告渲染(render.remedy_text:队列头=唯一导出修法,陈述句不设选项);
② ask 边机械前提(题面携「已试修法+队列空」证明——R5 标准②的工程载体:
   选项不再是绕弯子,因为能绕的弯子队列非空时引擎自己走了)。

判定链=归因判定树×通道知识×判例(全机械,零 LLM):
- reflow/frozen 未封顶 → recompile_directed(frozen 追加 vary_form 换法);
- rerun/transient 非 s₀ → rerun_isolated(复跑=h 重采样,只救 π——s₀ 由片3
  复跑闸挡,案级队列为空 → bed 呈报合法,床权在用户);
- 矛盾案自身有持久写且无清理 → self_cleanup 置头(互扰消解推论:复合施加);
- defect_candidate 未经形态检验 → vary_form(四查坐实);
- env_blocked/封顶/s₀/panel 待答 → 队列空(修法在引擎权限外或待人裁,ask 合法)。
"""
from __future__ import annotations

from main.ist_core.compile_engine_v8 import facts as F
from main.ist_core.compile_engine_v8 import views as V


def _mine(fs: list[dict], aid: str) -> list[dict]:
    return [f for f in fs if str(f.get("aid")) == aid]


def derive_queue(fs: list[dict], vw: dict, aid: str,
                 max_rounds: int = 3, granted: int = 0) -> list[dict]:
    """单案导出修法队列(队列项 {action, direction, basis};头=下一步)。"""
    c = (vw.get("cases") or {}).get(aid) or {}
    status = str(c.get("status") or "")
    if status not in (V.S_FAILED, V.S_CONTRADICTED):
        return []
    mine = _mine(fs, aid)
    atts = [f for f in mine if f.get("ev") == "attribution"]
    att = atts[-1] if atts else {}
    disp = str(att.get("disposition") or "")
    diags = [f for f in mine if f.get("ev") == "diagnosis"]
    s0 = bool(diags) and str(diags[-1].get("h_position", "")).startswith("h_s0")
    rounds = F.rounds_used(mine, aid)
    capped = rounds >= max_rounds + granted

    queue: list[dict] = []
    # 互扰消解推论:矛盾案自身持久写且无清理 → 自清理置头(复合施加的案内半)
    if status == V.S_CONTRADICTED and not s0:
        try:
            from main.ist_core.compile_engine_v8.nodes import _case_touch_profile
            prof = _case_touch_profile(aid)
            if prof["persist"]:
                queue.append({"action": "self_cleanup",
                              "direction": "case leaves persistent artifacts; "
                                           "add in-case cleanup then re-verify",
                              "basis": "interference-resolution corollary"})
        except Exception:  # noqa: BLE001
            pass
    if s0:
        return queue  # 床治理在引擎权限外 → 案级队列空(bed 呈报合法,片3)
    if disp in ("reflow", "frozen") and not capped:
        queue.append({"action": "recompile_directed",
                      "direction": str(att.get("fix_direction") or "")[:200],
                      "basis": f"attribution {att.get('layer')}/{disp}"})
        if disp == "frozen":
            queue.append({"action": "vary_form",
                          "direction": "same approach proven ineffective twice; "
                                       "change the verification form",
                          "basis": "frozen: same-signature two rounds"})
    elif disp in ("rerun_isolated", "transient"):
        queue.append({"action": "rerun_isolated", "direction": "",
                      "basis": "transient/interference suspicion; rerun re-samples noise"})
    elif disp == "defect_candidate":
        varied = any(f.get("ev") == "authored" and int(f.get("round") or 0) > 1
                     for f in mine)
        if not varied:
            queue.append({"action": "vary_form",
                          "direction": "reproduce under a different config form "
                                       "to confirm/rule out the defect",
                          "basis": "defect four-check: form variation required"})
    # env_blocked / capped / 无归因:队列空——修法在权限外或待归因/待人裁
    return queue


def tried_actions(fs: list[dict], aid: str) -> list[str]:
    """已试修法的机械清单(题面「队列空证明」的另一半:不是没试,是试尽了)。
    user-facing 中文——直接进面板题面。"""
    mine = _mine(fs, aid)
    out: list[str] = []
    rounds = F.rounds_used(mine, aid)
    if rounds > 1:
        out.append(f"重编 {rounds - 1} 次")
    n_rerun = sum(1 for f in mine if f.get("ev") == "attribution"
                  and str(f.get("disposition")) in ("rerun_isolated", "transient"))
    n_subset = sum(1 for f in mine if f.get("ev") == "verdict"
                   and str(f.get("ctx")) == F.CTX_SUBSET)
    if n_rerun and n_subset:
        out.append(f"隔离复跑 {n_subset} 次")
    n_reorder = sum(1 for f in mine if f.get("ev") == "decision"
                    and str(f.get("token")) == "reorder")
    if n_reorder:
        out.append(f"重排复验 {n_reorder} 次")
    return out
