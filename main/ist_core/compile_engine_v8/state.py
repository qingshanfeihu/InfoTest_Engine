"""V8 图状态(薄;账实分离 INV-7):真理在事实流,state 只有游标缓存+引用+入参。

checkpoint 因此只承载 LangGraph 自身需要的东西(图游标+interrupt 挂起态+本表)——
恢复时业务值以 facts/views 重算为准,state 缓存仅供条件边读取。
"""

from __future__ import annotations

from typing import TypedDict


class V8State(TypedDict, total=False):
    # 入参
    mindmap_path: str
    product_version: str
    out_name: str
    max_rounds: int
    # 引用(路径,相对 project root)
    facts_ref: str
    manifest_ref: str
    merged_ref: str          # 最近一次合并卷
    last_run_ref: str        # 最近一次 run 的 last_run.json(reconcile 的裁决源)
    error: str               # 节点错误详情(phase_status=error 时)
    # 床态
    bed_host: str
    device_build: str        # bed_gate 探得的设备自述(verdict 事实的 build 源)
    # 游标缓存(派生值;恢复时以视图为准)
    phase_status: str
    run_ctx: str             # 最近一次 run 的语境(delivery|subset)
    vol_seq: int             # 合并卷序号(子集卷目录命名)
    # 条件边计数缓存(views.batch_view 每节点出口重算)
    n_pending: int
    n_awaiting_user: int
    n_authored: int
    n_failed: int
    n_failed_actionable: int  # 失败/矛盾且不在任何问询等待集(run17:路由「有活」判据,§16.6)
    n_subset_verified: int
    n_broken: int
    n_broken_errored: int    # pyATS Errored 子类:命令畸形/断言被反证→reflow(§④)
    n_broken_blocked: int    # pyATS Blocked 子类:设备不可达→env 呈报(§④)
    n_deliverable: int
    n_contradicted: int
    n_settled_bad: int       # escalated + failed_terminal
    n_ask_contradiction: int  # 问询等待集大小(panel/contra/cap/env/bed/suspended 去重并)
    ask_answers_consumed: int  # ask_contradiction 本轮消化的实答数(部分作答≠真·未获答,§16.6)


# 节点表(拓扑门三方一致锚:graph ↔ 本表 ↔ SKILL.md phases)
NODE_TYPES: dict[str, str] = {
    "prep": "mech",
    "bed_gate": "mech+user",
    "author": "llm",
    "ask_decision": "user",
    "merge": "mech",
    "run": "mech",
    "reconcile": "mech",
    "attribute": "llm",
    "diagnose": "mech",
    "ask_contradiction": "user",
    "closing": "mech",
}
