"""IST-Core 工具沙箱：CWD 解析层（

本模块的职责是 **CWD 选择策略**——根据目标路径选最匹配的沙箱根作为子进程
``cwd``。沙箱根本身（``_AGENT_ROOT`` / ``_WORKSPACE_ROOT`` /
``_PLATFORM_DENIED_*``）的真实定义在 ``file_tools.py``，本模块从那里读取，
保证 monkeypatch ``file_tools._AGENT_ROOT`` 等历史用法仍然 work。
+ `业界 agent 设计` + `业界 agent 设计`）：

- 多根 + 显式扩展（``allWorkingDirectories`` = originalCwd ∪ additional）
- CWD 用 AsyncLocalStorage 并发隔离（``pwd()`` 读 store）
- **不用 SandboxedToolBase 基类**——明确反对深继承

InfoTest_Engine 落地（Python + LangGraph 简化版）：

- ``_default_cwd()`` ↔
- ``_resolve_cwd_for_target()``——根据目标路径选最匹配的沙箱根

**不做**：

- SandboxedToolBase 抽象基类（
- contextvars cwd 隔离（无并发场景；``_default_cwd()`` 留好钩子）
- OS 级沙箱运行时（
- permission prompt UI（agent 评审场景不交互）
"""

from __future__ import annotations

from pathlib import Path

def _default_cwd() -> Path:
    """工具默认 cwd——返回 ``_agent_roots()[0]`` (knowledge/data/)。
    InfoTest_Engine 简化为静态读首根，未来可升级 contextvars 驱动支持
    并发 agent 各自 cwd（钩子已留好）。
    """
    
    from main.ist_core.tools.deepagent.file_tools import _agent_roots
    return _agent_roots()[0]

def _resolve_cwd_for_target(target: Path | str | None) -> Path:
    """根据目标路径选最匹配的沙箱根作为 cwd。

    用法：``run_shell`` 解析命令路径参数后传给本函数，得到子进程 cwd。

    - target 为 None / 不在任何沙箱根 → 返回 ``_default_cwd()``
    - target 在某个沙箱根下 → 返回该根
    把相对路径解析成绝对路径再校验；InfoTest_Engine 反向做：先看目标在哪个
    根下，再选 cwd（因为我们没有用户 ``cd`` 概念）。
    """
    if target is None:
        return _default_cwd()
    target_path = target if isinstance(target, Path) else Path(target)
    try:
        target_resolved = target_path.resolve()
    except (OSError, ValueError):
        return _default_cwd()
    
    from main.ist_core.tools.deepagent.file_tools import _agent_roots
    for root in _agent_roots():
        try:
            target_resolved.relative_to(root.resolve())
            return root
        except ValueError:
            continue
    return _default_cwd()

__all__ = [
    "_default_cwd",
    "_resolve_cwd_for_target",
]
