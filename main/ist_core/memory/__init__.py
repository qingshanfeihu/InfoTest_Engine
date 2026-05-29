"""IST-Core 三层记忆子系统。

三层架构：
- L1 工作记忆（/working/）：thread 内，StateBackend，checkpointer 持久化
- L2 长期记忆（/memories/）：跨 thread，StoreBackend，namespace 隔离
- L3 项目指令（memory/AGENTS.md）：真实磁盘 + deepagents MemoryMiddleware 注入

为什么 lazy import：
- 单测 / dream cron 经常只需要某一两个子模块，不应该被 deepagents +
  langchain_anthropic + langchain_openai 整个家族拉起来（~60MB 起）
- 主 agent 启动路径仍走 main_agent.py 显式 import，行为不变
- 这里只导 is_enabled / get_default_root 两个轻量函数与 __all__ 名单；
  其余符号通过 __getattr__ 按需 lazy load
"""

from __future__ import annotations

import os
from typing import Any


def is_enabled() -> bool:
    """总开关：env IST_MEMORY_ENABLED != '0' 时启用。"""
    return (os.environ.get("IST_MEMORY_ENABLED") or "1").strip() != "0"


def get_default_root():
    """转发到 backend.get_default_root；lazy 避免提早拉 langgraph。"""
    from main.ist_core.memory.backend import get_default_root as _impl
    return _impl()


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    
    "build_memory_backend":         ("main.ist_core.memory.backend",         "build_memory_backend"),
    "make_memory_backend_factory":  ("main.ist_core.memory.backend",         "make_memory_backend_factory"),
    "get_default_store":            ("main.ist_core.memory.backend",         "get_default_store"),
    "get_memory_sources":           ("main.ist_core.memory.backend",         "get_memory_sources"),
    "MemoryStore":                  ("main.ist_core.memory.store",           "MemoryStore"),
    "MemoryInjectionMiddleware":    ("main.ist_core.memory.middleware",      "MemoryInjectionMiddleware"),
    "MemoryWriteMiddleware":        ("main.ist_core.memory.middleware",      "MemoryWriteMiddleware"),
    "build_extractor_agent":        ("main.ist_core.memory.extractor_agent", "build_extractor_agent"),
}


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute loader."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod_name, attr = target
    import importlib
    mod = importlib.import_module(mod_name)
    value = getattr(mod, attr)
    globals()[name] = value
    return value


__all__ = [
    "is_enabled",
    "get_default_root",
    "get_default_store",
    "get_memory_sources",
    "build_memory_backend",
    "build_extractor_agent",
    "MemoryInjectionMiddleware",
    "MemoryWriteMiddleware",
    "MemoryStore",
]
