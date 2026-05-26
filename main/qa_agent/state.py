"""IST-Core 顶层 State 定义。

字段全部可选（``total=False``）便于：
- ``normalize_input`` 节点补齐 ``normalized_input``
- ``finalize`` 写 ``final_answer``
- 子节点/Tool 可以安全读取未初始化字段（``state.get(...)``）
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages

TaskType = Literal["QA", "Plan", "Author", "Execute", "Report"]


class QaAgentState(TypedDict, total=False):
    """IST-Core 顶层 State。"""

    task_type: TaskType
    user_input: str | dict[str, Any]
    normalized_input: dict[str, Any]
    messages: Annotated[list, add_messages]
    final_answer: str

    run_id: str
    thread_id: str

    # review_gate 硬闸状态（Step 4，仿 cc-haha hookHelpers.ts:70-83
    # registerStructuredOutputEnforcement）。
    # gate_status: "pending" 注入提示重路由 qa_node；"passed" 走下一节点；
    #              "failed" 重试上限到，写错误 final_answer 走 finalize。
    gate_retry_count: int
    gate_status: Literal["pending", "passed", "failed"]
    gate_missing_reason: str

    # ReviewResult 结构化输出（Step 6，仿 cc-haha SyntheticOutputTool）。
    # structured_extract 节点产出，下游 TUI / 日志消费。
    final_review: dict[str, Any]
