"""守护:编译/上机工具的主 agent 挂载契约(main-orchestrated 架构)。

ist_compile 是 inline skill,主 agent 作为 orchestrator **自己编排**:compile_prep 解析脑图→
manifest、invoke_skill 派 compile_worker 逐 case 编、compile_grade_extract 合并前确定性自查 +
派 grade、compile_emit_merged 合并打包。故这些编排件**挂**主 agent。compile_pipeline 保留当
fallback(也挂)。compile_fanout **不挂**——main-orchestrated 用 invoke_skill 派 worker,不走
fanout 散件(防主 agent 越过 invoke_skill 手搓 fan-out)。
ist_verify 上机验证链用 dev_run_batch(串行上机),故它必须挂主 agent。
"""

from __future__ import annotations

# 主 agent 必须挂(orchestrator 直接调的编排/上机入口)
_MAIN_AGENT_TOOLS = [
    "compile_pipeline", "dev_run_batch",
    "compile_prep", "compile_emit", "compile_emit_merged", "compile_grade_extract",
]
# main-orchestrated 下仍不挂主 agent:compile_fanout(主 agent 用 invoke_skill 派 worker,不用 fanout)
_PIPELINE_INTERNAL = ["compile_fanout"]


def test_orchestration_entries_mounted_on_main_agent():
    """主 agent 挂 compile_pipeline(编译入口)+ dev_run_batch(ist_verify 上机)。"""
    from main.ist_core.agents.main_agent import _default_generic_tools
    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    for t in _MAIN_AGENT_TOOLS:
        assert t in names, f"{t} 未挂在主 agent——ist_compile/ist_verify 会调不到它"


def test_pipeline_internal_tools_not_mounted_on_main_agent():
    """compile_fanout 不挂主 agent(main-orchestrated 用 invoke_skill 派 worker,不手搓 fan-out)。"""
    from main.ist_core.agents.main_agent import _default_generic_tools
    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    for t in _PIPELINE_INTERNAL:
        assert t not in names, (
            f"{t} 不应挂主 agent——main-orchestrated 用 invoke_skill 派 worker,不走 fanout 散件"
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
