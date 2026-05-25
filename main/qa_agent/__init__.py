"""InfoTest Engine 的 IST-Core 兼容子包（历史路径：main.qa_agent）。

详细设计见 ``ARCHITECTURE.md §11-§12``。

- ``state.py``      — LangGraph ``QaAgentState`` + Pydantic schema
- ``graph.py``      — 顶层 StateGraph（normalize_input -> qa_node -> finalize）
- ``runner.py``     — CLI 入口
- ``server_graph.py`` — ``langgraph dev`` 入口（langgraph.json 指向这里）
- ``events.py``     — 类型化事件 ``QaAgentEvent`` + ``EventBus``
- ``streaming.py``  — ``astream_events(version="v2")`` -> ``QaAgentEvent`` 适配器
- ``agents/``       — IST-Core（main_agent 兼容入口）/ 专用 Reviewer（deepagents + ChatOpenAI 兼容端点）
- ``tools/``        — 12 个 ``@tool``（8 检索 + 4 对话式评审编排）
- ``sinks/``        — CLI / JSONL / LangSmith 三端 sink

代码命名继续遵循历史 ``qa_`` 前缀规范，以保持工具、graph id 和已入库数据兼容。
"""

from __future__ import annotations

__all__ = [
    "build_qa_agent_graph",
]


def build_qa_agent_graph(*args, **kwargs):
    """延迟导入图构造函数，避免 import 本包即触发 LangGraph/deepagents 初始化。"""
    from main.qa_agent.graph import build_qa_agent_graph as _build

    return _build(*args, **kwargs)
