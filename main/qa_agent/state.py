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
