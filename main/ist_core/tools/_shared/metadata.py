r"""Tool metadata registry, permission policy, and attach helper.

LangChain 的 @tool decorator 没有原生 metadata 参数，但 BaseTool 类有 metadata
字段。本模块用独立 registry 维护当前 runtime 工具元数据，由 build_main_agent
在挂载工具时调 :func:`attach_tool_metadata` 注入。

元数据字段语义：

- ``read_only``: True 表示工具契约上用于只读分析，不应修改本地状态/磁盘/远端。
- ``concurrency_safe``: True 表示同一 turn 内多次调用本工具可并发执行。
- ``fallback_for``: 当上游工具失效/无召回时，agent 应优先调用本工具作替代。值是
  上游工具名（或 None 表本工具无 fallback 链上游）。
- ``intent``: 工具的查询语义，read/grep/exec 之一。
- ``category``: 工具所属能力域（如 "document"、"device"、"knowledge"）。
- ``risk_level``: 风险等级 "low" / "medium" / "high"。主 agent 默认过滤 high。
- ``direct_use``: bool。medium risk 工具 True=主 agent 可直接调用，False=仅 skill。
- ``allowed_skills``: 允许使用此工具的 skill 列表（文档性，fork skill 解析用）。
- ``depends_on``: 此工具依赖的底层工具列表（组合关系声明）。
- ``require_explicit_creation_intent``: bool。True 时仅在用户有明确创建意图时调用，
  普通问答不得触发（如「介绍一下 SLB」不应创建文档）。

新增工具时**必须**在此注册——build_main_agent 启动时若发现挂载的 @tool 不在
本表中会记 warning。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 风险等级常量
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

# 过滤规则（direct_use 替代 allowed_skills 作为主 Agent 过滤依据）：
# - low: 主 agent 始终可用
# - medium + direct_use=True: 主 agent 可用（用户明确请求时）
# - medium + direct_use=False: 主 agent 过滤（仅 skill 上下文可用）
# - high: 主 agent 过滤（必须 skill + 确认）






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

    # 企业微信云文档工具（基础能力 + 权限策略）
    "wx_create_doc": {
        # 创建企微云文档：只给 fork agent（document-author）使用
        # main agent 通过 invoke_skill("doc-authoring") → fork agent 间接调用
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
        "category": "document",
        "risk_level": RISK_MEDIUM,
        "direct_use": False,
        "require_explicit_creation_intent": True,
        "depends_on": [],
        "allowed_skills": ["doc-authoring", "report-gen", "bug-report-gen"],
    },
    "wx_update_doc": {
        # 更新已有企微云文档：只给 fork agent 使用
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "intent": "write",
        "category": "document",
        "risk_level": RISK_MEDIUM,
        "direct_use": False,
        "require_explicit_creation_intent": True,
        "depends_on": ["wx_create_doc"],
        "allowed_skills": ["doc-authoring", "report-gen", "bug-report-gen"],
    },
    "report_to_doc": {
        # 结构化测试报告专用：Schema→MD→创建云文档+注册
        # direct_use=False: 仅 report-gen skill 可调用，主 agent 不可见
        # depends_on: 底层依赖 wx_create_doc（组合工具）
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": "wx_create_doc",
        "intent": "write",
        "category": "report",
        "risk_level": RISK_MEDIUM,
        "direct_use": False,
        "require_explicit_creation_intent": False,
        "depends_on": ["wx_create_doc"],
        "allowed_skills": ["report-gen"],
    },
    "wx_list_docs": {
        # 查询文档注册表（SQLite 只读）
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "read",
        "category": "document",
        "risk_level": RISK_LOW,
        "direct_use": True,
        "require_explicit_creation_intent": False,
        "depends_on": [],
        "allowed_skills": [],
    },
    "wx_search_doc": {
        # 全文搜索文档注册表（SQLite FTS）
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "search",
        "category": "document",
        "risk_level": RISK_LOW,
        "direct_use": True,
        "require_explicit_creation_intent": False,
        "depends_on": [],
        "allowed_skills": [],
    },
    "wx_read_doc": {
        # 读取企微云文档内容（Markdown 格式）
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "intent": "read",
        "category": "document",
        "risk_level": RISK_LOW,
        "direct_use": True,
        "require_explicit_creation_intent": False,
        "depends_on": [],
        "allowed_skills": [],
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


def should_filter_from_main_agent(tool_name: str) -> bool:
    """判断工具是否应从主 agent 默认工具列表中过滤。

    过滤规则（direct_use 控制）：
    - low risk → 不过滤（查询类，始终可用）
    - medium + direct_use=True → 不过滤（用户明确请求时可用）
    - medium + direct_use=False → 过滤（仅 skill 上下文可用）
    - high → 过滤（必须 skill + 确认）

    被过滤的工具仍可通过以下方式访问：
    - loader._get_tool_registry()（fork skill 解析用）
    - invoke_skill 内部调用
    - ToolGatingMiddleware 按 skill 上下文动态开放
    """
    meta = TOOL_METADATA.get(tool_name)
    if meta is None:
        return False  # 未注册工具不过滤（保持 fail-open）

    risk = meta.get("risk_level", RISK_LOW)
    direct_use = meta.get("direct_use", False)

    if risk == RISK_HIGH:
        return True
    if risk == RISK_MEDIUM and not direct_use:
        return True
    return False


def filter_tools_for_main_agent(tools: list[Any]) -> list[Any]:
    """根据权限策略过滤工具列表。

    过滤 high risk 工具和指定了 allowed_skills 的 medium risk 工具。
    被过滤的工具名记 info 日志。
    """
    filtered = []
    removed = []
    for t in tools:
        name = getattr(t, "name", "")
        if should_filter_from_main_agent(name):
            removed.append(name)
        else:
            filtered.append(t)
    if removed:
        logger.info(
            "权限策略：从主 agent 过滤 %d 个受限工具: %s",
            len(removed), removed,
        )
    return filtered


__all__ = [
    "TOOL_METADATA",
    "RISK_LOW",
    "RISK_MEDIUM",
    "RISK_HIGH",
    "attach_tool_metadata",
    "filter_tools_for_main_agent",
    "get_tool_metadata",
    "is_concurrency_safe",
    "is_read_only",
    "should_filter_from_main_agent",
]
