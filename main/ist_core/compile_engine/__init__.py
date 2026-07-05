"""V6 编译引擎:循环驱动的编排核心(LangGraph StateGraph 图 DSL)。

三层栈定位(docs/PLAN 数据结构学):
- 定义层:skills/ist-compile-engine/SKILL.md(元数据+孔位声明)
- 运行时层:本包 graph.py 的 StateGraph——节点=py 纯函数,条件边=state 计数的纯函数
- 回合层:三个 [llm] 孔经 execute_fork_skill 各是一张小图(create_agent)

LLM 只在孔里,永远不当胶水;数据按引用流(state 只放路径与计数,明细在盘上台账)。
"""

from main.ist_core.compile_engine.graph import build_compile_engine_graph  # noqa: F401
