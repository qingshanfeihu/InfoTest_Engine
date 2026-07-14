"""守护:编译/上机工具的主 agent 挂载契约(V6 引擎架构)。

编译走 V6 引擎:主 agent 调 `compile_engine_run` 一次跑完整条闭环(编写/合并/上机/
归因/定向重编,断点续跑)。下面这组 compile_*/dev_run_batch* 同时是 ist-verify 上机
验证链 + 引擎内部构件(引擎以 .func 复用),故挂主 agent。
compile_precedent 是 compile-worker fork 内部件——只在 loader fork 注册表,不挂主 agent。
"""

from __future__ import annotations

# 主 agent 必须挂(V6 编译入口 + ist-verify 上机链 + 引擎复用构件)
_MAIN_AGENT_TOOLS = [
    "compile_engine_run", "dev_run_batch",
    "compile_prep", "compile_emit", "compile_emit_merged", "compile_fanout",
]
# fork 内部件:只在 loader fork 注册表,绝不挂主 agent(主 agent 手搓会 churn 不收敛)。
_FORK_INTERNAL = ["compile_precedent"]


def test_orchestration_entries_mounted_on_main_agent():
    """主 agent 挂 compile_engine_run(V6 编译入口)+ dev_run_batch(ist-verify 上机)。"""
    from main.ist_core.agents.main_agent import _default_generic_tools
    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    for t in _MAIN_AGENT_TOOLS:
        assert t in names, f"{t} 未挂在主 agent——编译/ist-verify 会调不到它"


def test_fork_internal_tools_not_mounted_on_main_agent():
    """compile_precedent 不挂主 agent(compile-worker fork 内部件,只在 fork 注册表)。"""
    from main.ist_core.agents.main_agent import _default_generic_tools
    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    for t in _FORK_INTERNAL:
        assert t not in names, (
            f"{t} 不应挂主 agent——它是 compile-worker fork 内部件,只在 loader fork 注册表"
        )


def test_compile_tools_have_metadata():
    """挂主 agent 的工具 + fork 内部件都须在 TOOL_METADATA 注册。"""
    from main.ist_core.tools._shared.metadata import get_tool_metadata
    for t in _MAIN_AGENT_TOOLS + _FORK_INTERNAL:
        assert get_tool_metadata(t) is not None, f"{t} 未在 TOOL_METADATA 注册"


def test_run_batch_marked_not_concurrency_safe():
    """上机串行是硬约束:dev_run_batch 绝不能标 concurrency_safe。"""
    from main.ist_core.tools._shared.metadata import get_tool_metadata
    md = get_tool_metadata("dev_run_batch")
    assert md and md.get("concurrency_safe") is False
