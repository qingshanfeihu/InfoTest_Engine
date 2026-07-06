"""引擎图节点(相位函数薄壳):机械节点直调工具 .func,LLM 孔经 execute_fork_skill。

节点契约:`def node(state: CompileEngineState) -> dict`(返回 partial state update);
类型声明在 state.NODE_TYPES(拓扑门断言三方一致)。
"""

from main.ist_core.compile_engine.nodes.compile_phase import (  # noqa: F401
    prep, worker_fanout, ask_decision,
)
from main.ist_core.compile_engine.nodes.verify_phase import (  # noqa: F401
    merge, run_digest, attribute,
)
from main.ist_core.compile_engine.nodes.closing import (  # noqa: F401
    writeback, report,
)
