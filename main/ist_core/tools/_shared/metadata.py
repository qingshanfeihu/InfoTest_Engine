"""Current tool metadata registry + attach helper.

LangChain 的 @tool decorator 没有原生 metadata 参数，但 BaseTool 类有 metadata
字段。本模块用独立 registry 维护当前 runtime 工具元数据，由 build_main_agent
在挂载工具时调 :func:`attach_tool_metadata` 注入。

元数据字段语义：

- ``read_only``: True 表示工具契约上用于只读分析，不应修改本地状态/磁盘/远端。
- ``concurrency_safe``: True 表示同一 turn 内多次调用本工具可并发执行。
- ``fallback_for``: 当上游工具失效/无召回时，agent 应优先调用本工具作替代。值是
  上游工具名（或 None 表本工具无 fallback 链上游）。
- ``intent``: 工具的查询语义，read/grep/exec 之一。

新增工具时**必须**在此注册——build_main_agent 启动时若发现挂载的 @tool 不在
本表中会记 warning。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)






TOOL_METADATA: dict[str, dict[str, Any]] = {
    
    "fs_ls": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "read",
    },
    "fs_glob": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "fs_ls",
        "intent": "grep",
    },
    "fs_grep": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "fs_glob",
        "intent": "grep",
    },
    "fs_read": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "fs_grep",
        "intent": "read",
    },
    "fs_write": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
    },
    "fs_edit": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
    },
    "run_python": {
        "read_only": True,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "run_shell": {
        "read_only": True,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "dev_ssh": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "dev_rest": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "dev_run_case": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "dev_probe": {
        "read_only": True,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "compile_precedent": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "read",
    },
    "remember": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
    },
    "compile_emit": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
    },

    # V6 编译引擎入口:一次跑完整条闭环(编写/合并/上机/归因/重编),写本地产物 + 设备上机。
    "compile_engine_run": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    # 批量编译工具(V6 引擎构件 / ist-verify 链)
    "compile_prep": {
        # 解析脑图→manifest 落盘:写本地 manifest.json(非设备态),read_only=False。
        "read_only": False,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "read",
    },
    "compile_attribute": {
        # 上机 fail 四层归因(G/E/V/瞬态)。纯确定性内存计算,不读写设备/落盘。
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "read",
    },
    "compile_fanout": {
        # 内部线程池并发派发 fork(draft/grade),本身可并发,但通常一次性调度全批。
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "dev_run_batch": {
        # 串行上机(改设备态),绝不并发。
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "compile_emit_merged": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
    },

    "kb_bug_search": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "search",
    },
    
    "kb_footprint": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "search",
    },

    # 交互 / 元工具
    "ask_user": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "invoke_skill": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    "qa_file_server": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "exec",
    },
    # 上机回填 runtime 槽位（ist-verify 用）
    "compile_runtime_slots": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "read",
    },
    "compile_runtime_fill": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
    },
}







def get_tool_metadata(name: str) -> dict[str, Any] | None:
    """按工具名取元数据；未注册返回 None。"""
    return TOOL_METADATA.get(name)


def attach_tool_metadata(tool_obj: Any, *, strict: bool = False) -> Any:
    """把元数据合并到 LangChain Tool 对象的 ``.metadata`` 字段。

    LangChain BaseTool 的 metadata 字段是 ``Optional[dict]``，本函数：

    1. 若 tool_obj 已有 metadata（用户在 @tool 装饰器外手动 set 过），合并不覆盖
    2. 若工具名未在 :data:`TOOL_METADATA` 注册：
       - ``strict=False``（默认）记 warning 后跳过
       - ``strict=True`` 抛 ValueError

    返回的仍是原 tool_obj（in-place mutate），可链式使用。
    """
    name = getattr(tool_obj, "name", None)
    if not name:
        logger.warning("attach_tool_metadata: tool has no .name; skip")
        return tool_obj
    registered = TOOL_METADATA.get(name)
    if registered is None:
        msg = f"Tool '{name}' not registered in TOOL_METADATA (main/ist_core/tools/_shared/metadata.py)"
        if strict:
            raise ValueError(msg)
        logger.warning("%s — staying tolerant for now", msg)
        return tool_obj

    existing = getattr(tool_obj, "metadata", None) or {}
    
    merged = {**registered, **existing}
    try:
        tool_obj.metadata = merged
    except Exception as exc:  # pragma: no cover — Tool 对象通常允许 set
        logger.warning("attach_tool_metadata(%s) failed to set .metadata: %s", name, exc)
    return tool_obj


def is_concurrency_safe(tool_obj: Any) -> bool:
    """便捷：判断工具是否可并发（A3 partition 用）。"""
    md = getattr(tool_obj, "metadata", None) or {}
    if "concurrency_safe" in md:
        return bool(md["concurrency_safe"])
    
    registered = TOOL_METADATA.get(getattr(tool_obj, "name", ""))
    if registered:
        return bool(registered.get("concurrency_safe", False))
    return False


def is_read_only(tool_obj: Any) -> bool:
    """便捷：判断工具是否只读（plan mode gate 用）。"""
    md = getattr(tool_obj, "metadata", None) or {}
    if "read_only" in md:
        return bool(md["read_only"])
    registered = TOOL_METADATA.get(getattr(tool_obj, "name", ""))
    if registered:
        return bool(registered.get("read_only", False))
    return False


__all__ = [
    "TOOL_METADATA",
    "attach_tool_metadata",
    "get_tool_metadata",
    "is_concurrency_safe",
    "is_read_only",
]
