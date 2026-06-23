"""守护:批量编译工具必须挂在主 agent 上。

ist_compile 是 inline skill,在**主 agent 上下文**执行,所以它用的
compile_prep/compile_fanout/dev_run_batch/compile_emit_merged 必须挂在
主 agent 工具表(_default_generic_tools)里——否则 agent 看 SKILL.md 让它调这些
工具却调不到,会困惑地退回 run_python 手搓(本会话踩过的真 bug)。

同时这些工具必须在 TOOL_METADATA 注册(build_main_agent 启动会校验)。
"""

from __future__ import annotations

_BATCH_TOOLS = ["compile_prep", "compile_fanout", "dev_run_batch", "compile_emit_merged"]


def test_batch_tools_mounted_on_main_agent():
    from main.ist_core.agents.main_agent import _default_generic_tools
    names = {getattr(t, "name", "") for t in _default_generic_tools()}
    for t in _BATCH_TOOLS:
        assert t in names, f"批量工具 {t} 未挂在主 agent——ist_compile 编译链会调不到它"


def test_batch_tools_have_metadata():
    from main.ist_core.tools._shared.metadata import get_tool_metadata
    for t in _BATCH_TOOLS:
        assert get_tool_metadata(t) is not None, f"{t} 未在 TOOL_METADATA 注册"


def test_run_batch_marked_not_concurrency_safe():
    """上机串行是硬约束:dev_run_batch 绝不能标 concurrency_safe。"""
    from main.ist_core.tools._shared.metadata import get_tool_metadata
    md = get_tool_metadata("dev_run_batch")
    assert md and md.get("concurrency_safe") is False
