"""引擎图 State(数据按引用:只放路径与机读计数,明细在盘上台账)。

条件边只读这里的计数字段;逐 case 明细(状态机/verdict 历史/归因)在
engine_ledger.json(ledger.py),LLM 孔的输入输出在 workspace 文件。
State 全 JSON 可序列化——checkpoint 安全(SqliteSaver)。
"""

from __future__ import annotations

from typing import TypedDict


class CompileEngineState(TypedDict, total=False):
    # —— 输入不变量(prep 后冻结) ——
    mindmap_path: str
    product_version: str
    out_name: str
    max_rounds: int

    # —— 台账引用(workspace 相对路径) ——
    manifest_ref: str        # workspace/outputs/<out>/manifest.json
    ledger_ref: str          # workspace/outputs/<out>/engine_ledger.json
    merged_xlsx_ref: str     # 本轮上机卷(整卷或 fail 子集卷)
    last_run_ref: str        # 本轮上机卷同目录 last_run.json
    report_ref: str          # workspace/outputs/<out>/engine_report.json

    # —— 机读计数(条件边唯一依据;来源=ledger 聚合) ——
    round: int               # 上机轮次(0=未上机)
    wave: int                # worker 派发波次
    n_pending_compile: int
    n_pending_decision: int
    n_awaiting_user: int
    n_produced: int
    n_passed: int
    n_failed_active: int
    n_failed_terminal: int
    run_scope: str           # "full" | "subset"
    need_final_full_run: bool

    # —— 迁移信号 ——
    phase_status: str        # 各节点出口:"ok"|"error"|"device_busy"|"nothing_to_do"
    error: str


# 节点类型注册表:图上每个节点必须在此声明 mech/llm/user 三类之一——
# 拓扑门(test_graph_topology)断言图节点集与本表、与 SKILL.md phases 三方一致。
NODE_TYPES: dict[str, str] = {
    "prep": "mech",
    "worker_fanout": "llm",      # 孔①:compile-worker fork
    "ask_decision": "user",      # 孔②(机械模板为主)+ ask_user
    "merge": "mech",
    "run_digest": "mech",
    "attribute": "llm",          # 孔③:compile-attributor fork(机械预判在前)
    "writeback": "mech",
    "report": "mech",
}
