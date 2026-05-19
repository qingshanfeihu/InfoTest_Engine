"""LangGraph dev / Studio 服务器入口。

`langgraph dev` / `langgraph build` 启动时会读取根目录 ``langgraph.json``，
据此 import 本模块并取 ``graph`` 属性作为已编译的 ``CompiledStateGraph``。

服务器自带 checkpointer / store 注入，因此这里关闭本地的 SqliteSaver / MemorySaver，
避免双重持久化。
"""
from __future__ import annotations

from main.qa_agent.graph import build_qa_agent_graph

graph = build_qa_agent_graph(checkpointer=False, store=False)
