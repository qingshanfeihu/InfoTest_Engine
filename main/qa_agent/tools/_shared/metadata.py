"""R0.5 Stage A1：工具元数据注册表 + attach helper。

LangChain 的 @tool decorator 没有原生 metadata 参数，但 BaseTool 类有 metadata
字段。本模块用独立 registry 维护元数据，由 build_main_agent / build_reviewer_agent
在挂载工具时调 :func:`attach_tool_metadata` 注入。

元数据字段语义：

- ``read_only``: True 表示工具不修改本地状态/磁盘/远端。只读批可并发跑（A3 partition）。
- ``concurrency_safe``: True 表示同一 turn 内多次调用本工具可并发执行。
  ``read_only`` 的工具通常也 ``concurrency_safe``，但 *写入* 操作必为 False。
- ``fallback_for``: 当上游工具失效/无召回时，agent 应优先调用本工具作替代。值是
  上游工具名（或 None 表本工具无 fallback 链上游）。
- ``stage``: 评审 pipeline 三阶段归属，scope/research/write/orchestration，
  R0.5 Stage C 起按 stage 切 sub-agent 暴露面（write 阶段不暴露 research 工具，等等）。
- ``intent``: 工具的查询语义，semantic/grep/read/dispatch/web/control 之一，
  研究员 agent 据此组合检索路径。

新增工具时**必须**在此注册——build_main_agent 启动时若发现挂载的 @tool 不在
本表中会记 warning（A1 阶段先 warn，Stage C 起 raise）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 元数据表
# ---------------------------------------------------------------------------

TOOL_METADATA: dict[str, dict[str, Any]] = {
    # ---- 一阶段通用 DeepAgents-style 只读工具 ------------------------------
    "qa_deepagent_ls": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "read",
    },
    "qa_deepagent_glob": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_deepagent_ls",
        "stage": "research",
        "intent": "grep",
    },
    "qa_deepagent_grep": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_deepagent_glob",
        "stage": "research",
        "intent": "grep",
    },
    "qa_deepagent_read_file": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_deepagent_grep",
        "stage": "research",
        "intent": "read",
    },
    # ---- 语义检索类（read_only + concurrency_safe）-------------------------
    "qa_search_product_kb": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["feature_json", "trunk_unit"],
    },
    "qa_search_assets": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["test_case", "test_spec", "qa_trunk_unit"],
    },
    "qa_search_knowledge_ref": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_web_search",
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["rfc", "linux_man", "osi_layer"],
    },
    "qa_command_exists": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "grep",
        "doc_type_filter": ["cli_graph"],
    },
    "qa_search_architecture": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_search_product_kb",
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["architecture_doc"],
    },
    "qa_search_scenario": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_search_product_kb",
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["scenario_doc"],
    },
    "qa_search_by_cli_anchor": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_search_product_kb",
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["feature_json", "trunk_unit"],
    },
    "qa_get_sibling_features": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_search_by_cli_anchor",
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["feature_json"],
    },
    # ---- R0.7+ static-diff 系列（零 LLM，纯结构对账）----------------------
    "qa_static_diff_suite_vs_feature": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "grep",
        "doc_type_filter": ["feature_json"],
    },
    "qa_static_diff_suite_vs_baseline": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "grep",
        "doc_type_filter": ["baseline_doc"],
    },
    "qa_static_diff_suite_vs_bug": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "grep",
        "doc_type_filter": ["bug"],
    },
    "qa_static_check_cli_typos": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": "qa_command_exists",
        "stage": "research",
        "intent": "grep",
        "doc_type_filter": ["cli_graph"],
    },
    "qa_static_check_qa_merged_pollution": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "grep",
        "doc_type_filter": ["qa_trunk_unit"],
    },
    "qa_web_search": {
        "read_only": True,
        "concurrency_safe": False,  # DDG rate limit; 不并发避免被封
        "fallback_for": "qa_search_knowledge_ref",
        "stage": "research",
        "intent": "web",
    },
    "defect_search_kb": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "semantic",
        "doc_type_filter": ["bug", "plm_ticket"],
    },
    "defect_fetch_on_demand": {
        "read_only": True,
        "concurrency_safe": False,  # Playwright session 不可并发
        "fallback_for": "defect_search_kb",
        "stage": "research",
        "intent": "fetch",
    },
    "defect_fetch_direct": {
        "read_only": True,
        "concurrency_safe": False,  # 跟 on_demand 共享 Playwright session
        "fallback_for": "defect_fetch_on_demand",
        "stage": "research",
        "intent": "fetch",
    },
    "qa_trace_change": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "research",
        "intent": "semantic",
    },
    # ---- 评审编排控制类（部分 read_only）----------------------------------
    "qa_check_origin_updates": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "scope",
        "intent": "read",
    },
    "qa_scope_review_context": {
        "read_only": False,  # 默认 persist_to_review_input=True，会写回 review_input._meta
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "scope",
        "intent": "read",
    },
    "qa_load_baseline_rules": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "scope",
        "intent": "read",
    },
    "qa_read_large_tool_result": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "orchestration",
        "intent": "read",
    },
    "qa_summarize_test_list": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "scope",
        "intent": "read",
        "doc_type_filter": ["test_case", "test_spec"],
    },
    # ---- 写入/流水线类（必为 read_only=False）-----------------------------
    "qa_ingest_test_list": {
        "read_only": False,  # 落盘 review_input.json
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "scope",
        "intent": "write",
    },
    "qa_run_pipeline": {
        "read_only": False,  # subprocess + 落盘
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "scope",
        "intent": "write",
    },
    "qa_invoke_reviewer": {
        "read_only": False,  # 写 audit.json + 落盘 report
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "write",
        "intent": "dispatch",
    },
    "qa_invoke_reviewer_async": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "write",
        "intent": "dispatch",
    },
    "qa_resume_pending_review": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "write",
        "intent": "control",
    },
    "qa_check_review_status": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "orchestration",
        "intent": "read",
    },
    "qa_cancel_review": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "orchestration",
        "intent": "control",
    },
    # ---- 平台 runtime 工具 -------------------------------------------------
    "qa_platform_run_task": {
        "read_only": False,
        "concurrency_safe": False,
        "fallback_for": None,
        "stage": "orchestration",
        "intent": "dispatch",
    },
    "qa_platform_plan_test_execution": {
        "read_only": True,
        "concurrency_safe": True,
        "fallback_for": None,
        "stage": "orchestration",
        "intent": "read",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_tool_metadata(name: str) -> dict[str, Any] | None:
    """按工具名取元数据；未注册返回 None。"""
    return TOOL_METADATA.get(name)


def attach_tool_metadata(tool_obj: Any, *, strict: bool = False) -> Any:
    """把元数据合并到 LangChain Tool 对象的 ``.metadata`` 字段。

    LangChain BaseTool 的 metadata 字段是 ``Optional[dict]``，本函数：

    1. 若 tool_obj 已有 metadata（用户在 @tool 装饰器外手动 set 过），合并不覆盖
    2. 若工具名未在 :data:`TOOL_METADATA` 注册：
       - ``strict=False``（默认，Stage A 行为）记 warning 后跳过
       - ``strict=True``（Stage C 起的行为）抛 ValueError

    返回的仍是原 tool_obj（in-place mutate），可链式使用。
    """
    name = getattr(tool_obj, "name", None)
    if not name:
        logger.warning("attach_tool_metadata: tool has no .name; skip")
        return tool_obj
    registered = TOOL_METADATA.get(name)
    if registered is None:
        msg = f"Tool '{name}' not registered in TOOL_METADATA (main/qa_agent/tools/_metadata.py)"
        if strict:
            raise ValueError(msg)
        logger.warning("R0.5 Stage A: %s — staying tolerant for now", msg)
        return tool_obj

    existing = getattr(tool_obj, "metadata", None) or {}
    # 注册表优先；用户手动 set 的字段保留（merge 但 registered 不覆盖 existing 已有键）
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
    # fallback 到注册表
    registered = TOOL_METADATA.get(getattr(tool_obj, "name", ""))
    if registered:
        return bool(registered.get("concurrency_safe", False))
    return False  # 未知工具保守串行


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
