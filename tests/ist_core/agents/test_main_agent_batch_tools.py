"""守护:编译/上机工具的主 agent 挂载契约(v3 pipeline 架构 + 桶 D 解耦)。

ist_compile 是 inline skill,在主 agent 上下文执行,但它**只调一次** compile_pipeline
——固定序列 prep→fanout→merge 锁在该工具内部(直接 import,不经主 agent 工具表)。
故主 agent **挂 compile_pipeline,不挂** compile_prep/compile_fanout/compile_emit_merged
(桶 D:主 agent 只编排不手搓,避免它越过 pipeline 逐步调散件而失控——本会话踩过的真 bug)。
ist_verify 上机验证链用 dev_run_batch(串行上机),故它必须挂主 agent。
"""

from __future__ import annotations

# 主 agent 必须挂(它直接调的编排/上机入口)
_MAIN_AGENT_TOOLS = ["compile_pipeline", "dev_run_batch"]
# pipeline 内部件,主 agent 不挂(compile_pipeline 内部直接 import 调用)
_PIPELINE_INTERNAL = ["compile_prep", "compile_fanout", "compile_emit_merged"]


def test_orchestration_entries_mounted_on_main_agent():
    """主 agent 挂 compile_pipeline(编译入口)+ dev_run_batch(ist_verify 上机)。"""
    from main.ist_core.agents.main_agent import _default_generic_tools
    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    for t in _MAIN_AGENT_TOOLS:
        assert t in names, f"{t} 未挂在主 agent——ist_compile/ist_verify 会调不到它"


def test_pipeline_internal_tools_not_mounted_on_main_agent():
    """桶 D:prep/fanout/emit_merged 是 pipeline 内部件,不挂主 agent(防主 agent 手搓拆步)。"""
    from main.ist_core.agents.main_agent import _default_generic_tools
    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    for t in _PIPELINE_INTERNAL:
        assert t not in names, (
            f"{t} 不应挂主 agent——它是 compile_pipeline 内部件,主 agent 只调 pipeline 一次"
        )


def test_compile_tools_have_metadata():
    """编排入口 + pipeline 内部件都须在 TOOL_METADATA 注册(仍是合法工具,供 pipeline/fork 取用)。"""
    from main.ist_core.tools._shared.metadata import get_tool_metadata
    for t in _MAIN_AGENT_TOOLS + _PIPELINE_INTERNAL:
        assert get_tool_metadata(t) is not None, f"{t} 未在 TOOL_METADATA 注册"


def test_run_batch_marked_not_concurrency_safe():
    """上机串行是硬约束:dev_run_batch 绝不能标 concurrency_safe。"""
    from main.ist_core.tools._shared.metadata import get_tool_metadata
    md = get_tool_metadata("dev_run_batch")
    assert md and md.get("concurrency_safe") is False
