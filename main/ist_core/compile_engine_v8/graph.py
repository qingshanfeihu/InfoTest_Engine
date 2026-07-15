"""V8 引擎图:节点表+条件边表(图即文档;拓扑门三方一致:本图 ↔ NODE_TYPES ↔ SKILL.md)。

条件边全部是 state 计数缓存的纯函数(缓存由各节点出口按视图重算;真理在事实流,INV-7)。

V8.5 片2(2026-07-12,DESIGN §16.1)——问询语义改「山穷水尽才 ask」(§14-R4 用户
裁决:能输出尽量全输出,单案待人不得阻塞全批):欠定案不再在 author 后立即
interrupt 阻塞全图——该案 suspended(awaiting_user 派生态天然挡在 merge ready
集外),其余案继续跑;**只有当全批再无可推进工作时**(各终态判定点经
_gather_or_close)才进 ask_decision 聚合呈报(批末 gather;答题→复活→续跑到
不动点,composition 锚保证复活案入卷后自动强制重新终验,INV-8 不破)。

    prep            ok→bed_gate | error→closing
    bed_gate        ok→author | bed_blocked→closing
    author          待验/处方复跑(actionable)→merge | 封顶/env/挂起恢复待问→ask_contradiction
                    | 无活可干∧欠定>0→ask_decision(gather) | 全躺→closing
                    (§16.6:actionable=失败∧不在问询等待集;处方复跑先于 ask)
    ask_decision    有待编(决策已答)→author | 有待验→merge | 全躺→closing
    merge           ok→run | nothing∧欠定>0→ask_decision(gather) | error→closing
    run             ok→reconcile | busy/error→closing
    reconcile       矛盾≥2待问→ask_contradiction | 有 fail→attribute | 有待终验→merge
                    | 全 deliverable∧欠定>0→ask_decision(gather) | 否则→closing
    attribute       →diagnose(必过批级诊断,V8.5 片3)
    diagnose        [mech] s₀ 配对(交换子 I6 近似)+common_cause 聚类→diagnosis 事实;
                    路由=原 attribute:reflow→author | rerun→merge(s₀ 案被复跑闸挡)
                    | 矛盾→ask_contradiction | 全终局∧欠定>0→gather | 否则→closing
    ask_contradiction 依用户答案:可推进失败案→attribute | 待验→merge
                    | 其余∧欠定>0→ask_decision(gather)
                    | 真·未获答(本轮零实答)→closing(禁空转;部分作答不吞已答案子,§16.6)
    closing         →END
"""

from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from main.ist_core.compile_engine_v8 import nodes as N
from main.ist_core.compile_engine_v8.state import V8State, NODE_TYPES


def _after_prep(s: dict) -> str:
    # prep 期无 authored→无欠定,_gather_or_close 恒收口(no-op);经门只为「所有 closing
    # 边统一前置 flush」的不变量完整(回归#2 修 B)
    return "bed_gate" if s.get("phase_status") != "error" else _gather_or_close(s)


def _after_bed(s: dict) -> str:
    return "author" if s.get("phase_status") == "ok" else _gather_or_close(s)


def _gather_or_close(s: dict) -> str:
    """收口前置门(回归#2 修 B,DESIGN_dongkl_finalization §⑥ INV-flush:§16「批末必有
    聚合点」立为**真不变量**)。

    原语义=批末 gather(V8.5 片2):终态点若还有欠定待答→聚合呈报,否则收口。
    但「山穷水尽才 ask」只在 happy-path(live 干净归零)成立;硬错误/停滞收口边曾
    **绕过本门直接 closing**,把未答欠定静默吞掉(yzg 实证:7 欠定案 reconcile→closing
    没被问)。现所有到 closing 的 pre-ask 边(bed_blocked/reconcile error/run 非 ok/
    merge error)都经本门——有欠定必先 gather 呈报(§18.2 式③不静默);确因非交互
    无法问,由 closing 节点落 awaiting_user_unasked 事实兜底(仍不静默)。
    (post-ask 的 ask_decision 耗尽/dismiss 不经此门——那是已问过的如实收口,重问会活锁。)"""
    return "ask_decision" if s.get("n_awaiting_user", 0) > 0 else "closing"


def _after_author(s: dict) -> str:
    # V8.5 片2:有活先干活——欠定案已由 awaiting_user 派生态挡在 merge ready 集外,
    # 不需要(也不允许)在此阻塞全图;问询降到本函数最后一个可达位(山穷水尽)。
    if s.get("n_authored", 0) > 0 or s.get("n_subset_verified", 0) > 0:
        return "merge"
    # rerun/transient 处方案:author 不重编,处方必达 merge 复跑(第5轮实证:668030 的
    # rerun_isolated 处方曾被此路由洞吞掉)。run17 实弹(§16.6)两向校准:①本检查必须
    # 先于 ask——resumed 复活案曾被「有未答题」截回问询成活锁;②判据用 actionable
    # (失败∧不在问询等待集)——封顶/env/bed 待问案不算"有活",否则 cap 资源问询被
    # merge 空转跳过(11.7:引擎无单方终结权)。
    if s.get("n_failed_actionable", 0) > 0:
        return "merge"
    if s.get("n_ask_contradiction", 0) > 0:
        return "ask_contradiction"   # 封顶资源问询/env 确认/挂起恢复(山穷水尽才问)
    return _gather_or_close(s)


def _after_ask_decision(s: dict) -> str:
    if s.get("n_pending", 0) > 0:
        return "author"
    if s.get("n_authored", 0) > 0:
        return "merge"
    return "closing"


def _after_merge(s: dict) -> str:
    if s.get("phase_status") == "ok":
        return "run"
    if s.get("phase_status") == "nothing_to_merge":
        return _gather_or_close(s)   # 全部剩余=挂起/待决 → 批末 gather
    return _gather_or_close(s)   # error/device_busy 收口前也先 flush 欠定(回归#2 修 B)


def _after_run(s: dict) -> str:
    # 收口前置门(回归#2 修 B):device_busy/digest 无 last_run 等硬错误收口前也先
    # flush 欠定,不静默吞;无欠定时照旧如实收口
    return "reconcile" if s.get("phase_status") == "ok" else _gather_or_close(s)


def _after_reconcile(s: dict) -> str:
    if s.get("phase_status") == "error":
        # INV-2 残差/last_run 不可读:硬停如实收口(§18.2)——但收口前先 flush 欠定
        # (回归#2 修 B:硬停不该连带静默吞掉独立于本错误的待答欠定案)
        return _gather_or_close(s)
    if s.get("n_ask_contradiction", 0) > 0:
        return "ask_contradiction"   # blocked 子类经 reconcile 机械 env_blocked 归因在此呈报(§④)
    if s.get("n_failed", 0) > 0 or s.get("n_broken_errored", 0) > 0:
        return "attribute"      # errored 子类:已由 reconcile 落机械 reflow 归因,过 attribute
                                # (跳已归因)→diagnose→author 重写(§④;不空跑同一缺陷)
    live = (s.get("n_authored", 0) + s.get("n_subset_verified", 0)
            + s.get("n_broken", 0))   # broken=协议级分不清,处置=复跑((44));连击护栏在 reconcile
    if live > 0:
        return "merge"          # 待终验(子集过)/新卷待验/broken 复跑
    return _gather_or_close(s)


def _after_diagnose(s: dict) -> str:
    """diagnose(批级机械裁决,V8.5 片3)承接原 attribute 的路由——归因收账后先过
    批级视野(s₀ 配对/common_cause 聚类)再定去向。"""
    if s.get("n_ask_contradiction", 0) > 0:
        return "ask_contradiction"
    if (s.get("n_failed", 0) > 0 or s.get("n_pending", 0) > 0
            or s.get("n_broken_errored", 0) > 0):
        return "author"         # reflow 定向重编(author 内部按处置/封顶筛);
                                # broken_errored 携机械 reflow 归因,同走此路重写(§④)
    if s.get("n_authored", 0) + s.get("n_subset_verified", 0) > 0:
        return "merge"          # rerun_isolated/transient:不重编直接复跑(s₀ 案已被复跑闸挡)
    return _gather_or_close(s)


def _after_ask_contradiction(s: dict) -> str:
    # 真·未获答(非交互/面板取消:本轮零实答)→ 如实收口,禁 ask↔attribute 空转。
    # run17 实弹(§16.6):旧判据「有任何未答题即 closing」在部分作答时吞掉已答案子
    # ——3 题答 1,668044 resumed 产生可推进工作,却被直接收口;设计原文「未获答」
    # 指零答案的非交互场,不指「答了但没答全」。
    if s.get("ask_answers_consumed", 0) <= 0 and s.get("n_ask_contradiction", 0) > 0:
        # 零实答收口前也 flush 欠定(回归#2 修 B):ask_contradiction 与 ask_decision 是
        # 不同面板,零答 contradiction 后仍经 ask_decision 问 needs_decision;后者零答/
        # dismiss → _after_ask_decision 收口,不 ping-pong(ask_decision 提供终止)
        return _gather_or_close(s)
    if s.get("n_failed_actionable", 0) > 0:
        return "attribute"      # 计数<2 的矛盾案/翻转案/resumed 复活案继续归因定向回环(验收发现#7)
    if s.get("n_authored", 0) + s.get("n_subset_verified", 0) > 0:
        return "merge"
    return _gather_or_close(s)  # 用户刚在场:顺路聚合欠定(批末 gather);答案全为挂起/降级时如实收口


def build_v8_graph(checkpointer=None):
    g = StateGraph(V8State)
    for name in NODE_TYPES:
        g.add_node(name, getattr(N, name))
    g.add_edge(START, "prep")
    g.add_conditional_edges("prep", _after_prep, ["bed_gate", "closing"])
    g.add_conditional_edges("bed_gate", _after_bed, ["author", "closing"])
    g.add_conditional_edges("author", _after_author,
                            ["ask_decision", "merge", "ask_contradiction", "closing"])
    g.add_conditional_edges("ask_decision", _after_ask_decision, ["author", "merge", "closing"])
    g.add_conditional_edges("merge", _after_merge, ["run", "ask_decision", "closing"])
    g.add_conditional_edges("run", _after_run, ["reconcile", "closing"])
    g.add_conditional_edges("reconcile", _after_reconcile,
                            ["ask_contradiction", "attribute", "merge", "ask_decision", "closing"])
    g.add_edge("attribute", "diagnose")   # 归因收账后必过批级诊断(V8.5 片3)
    g.add_conditional_edges("diagnose", _after_diagnose,
                            ["ask_contradiction", "author", "merge", "ask_decision", "closing"])
    g.add_conditional_edges("ask_contradiction", _after_ask_contradiction,
                            ["attribute", "merge", "ask_decision", "closing"])
    g.add_edge("closing", END)
    return g.compile(checkpointer=checkpointer)


graph = build_v8_graph()
