r"""运行时工具权限管理。

根据 intent + agent_type + skill 动态决定可用工具集。
不修改 Tool API，只在 middleware 层过滤 request.tools。

用法::

    from main.ist_core.middleware.runtime_permission import RuntimeToolPermission
    perm = RuntimeToolPermission()
    allowed = perm.get_allowed_tool_names(Intent.CREATE_DOCUMENT, agent_type="main")
    # → {"wx_create_doc", "wx_update_doc", "wx_list_docs", "wx_search_doc", "fs_read", ...}
"""

from __future__ import annotations

import logging
from typing import Any

from .intent_router import Intent

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# 基础工具集（任何 intent 都可用）
# ──────────────────────────────────────────────────────────────

_BASE_TOOLS: set[str] = {
    # 文件操作
    "fs_ls", "fs_glob", "fs_grep", "fs_read",
    # 执行
    "run_python", "run_shell",
    # 交互
    "ask_user", "invoke_skill", "remember",
    # 知识检索（只读，任何场景可用）
    "kb_footprint", "kb_memory_search", "kb_bug_search",
}

# ──────────────────────────────────────────────────────────────
# Intent → 额外工具集（在基础工具之上叠加）
# ──────────────────────────────────────────────────────────────

_INTENT_TOOLSETS: dict[Intent, set[str]] = {
    Intent.CHAT: {
        # 普通问答：基础 + 写文件 + 设备只读 + 文档查询
        "fs_write", "fs_edit",
        "dev_ssh", "dev_rest", "dev_probe",
        "wx_list_docs", "wx_search_doc",
    },
    Intent.CREATE_DOCUMENT: {
        # 创建文档：基础 + 文档 CRUD
        "wx_create_doc", "wx_update_doc",
        "wx_list_docs", "wx_search_doc",
    },
    Intent.UPDATE_DOCUMENT: {
        # 更新文档：基础 + 文档更新
        "wx_update_doc",
        "wx_list_docs", "wx_search_doc",
    },
    Intent.GENERATE_REPORT: {
        # 生成报告：基础 + 结构化报告工具 + 文档 CRUD
        # 注意：report_to_doc 由 fork skill 内部使用，不在主 agent 工具表
        "report_to_doc",
        "wx_create_doc", "wx_update_doc",
        "wx_list_docs", "wx_search_doc",
    },
    Intent.SEARCH_KNOWLEDGE: {
        # 搜索知识：基础即可（kb_* 已在 base 中）
        # 额外加文档搜索
        "wx_list_docs", "wx_search_doc",
    },
}

# ──────────────────────────────────────────────────────────────
# Agent 类型修饰（某些 agent 不需要某些工具）
# ──────────────────────────────────────────────────────────────

_AGENT_RESTRICTIONS: dict[str, set[str]] = {
    "explore": {
        # 探索 agent：只读，不能写
        "fs_write", "fs_edit", "run_shell",
        "wx_create_doc", "wx_update_doc", "report_to_doc",
        "dev_ssh", "dev_rest", "dev_run_case", "dev_run_batch",
    },
}

# ──────────────────────────────────────────────────────────────
# 额外工具集（按需叠加，如编译/设备）
# ──────────────────────────────────────────────────────────────

_EXTRA_TOOLSETS: dict[str, set[str]] = {
    "compile": {
        "compile_emit", "compile_emit_merged", "compile_prep",
        "compile_fanout", "compile_engine_run", "compile_attribute",
        "compile_precedent", "compile_writeback", "compile_expected_hits",
        "compile_runtime_slots", "compile_runtime_fill",
        "compile_check_verifiability",
        "submit_attribution", "submit_behavior_fact",
    },
    "device": {
        "dev_ssh", "dev_rest", "dev_probe", "dev_run_case",
        "dev_run_batch", "dev_run_batch_digest", "dev_init_device",
    },
    "file_write": {
        "fs_write", "fs_edit",
    },
}

# 保守模式工具集（中置信度时使用）：只保留安全的读/查询工具
_CONSERVATIVE_TOOLS: set[str] = {
    # 基础文件读取
    "fs_ls", "fs_glob", "fs_grep", "fs_read",
    # 知识检索
    "kb_footprint", "kb_memory_search", "kb_bug_search",
    # 交互
    "ask_user", "invoke_skill", "remember",
    # 文档查询（只读）
    "wx_list_docs", "wx_search_doc",
    # 执行（受控）
    "run_python",
}


class RuntimeToolPermission:
    """运行时工具权限管理器。

    根据 intent + agent_type + active_groups 动态计算可用工具集。
    """

    def __init__(self) -> None:
        pass

    def get_allowed_tool_names(
        self,
        intent: Intent,
        agent_type: str = "main",
        active_groups: set[str] | None = None,
    ) -> set[str]:
        """计算当前请求允许的工具名集合。

        Args:
            intent: 检测到的用户意图
            agent_type: agent 类型（main / explore / fork agent 名）
            active_groups: ToolGatingMiddleware 激活的能力域组

        Returns:
            允许的工具名集合
        """
        # 1. 基础工具集
        allowed = set(_BASE_TOOLS)

        # 2. 叠加 intent 工具集
        intent_tools = _INTENT_TOOLSETS.get(intent, set())
        allowed |= intent_tools

        # 3. 叠加 active_groups 工具集（来自 ToolGatingMiddleware）
        if active_groups:
            for group in active_groups:
                extra = _EXTRA_TOOLSETS.get(group, set())
                allowed |= extra

        # 4. 应用 agent 类型限制
        restrictions = _AGENT_RESTRICTIONS.get(agent_type, set())
        allowed -= restrictions

        return allowed

    def filter_tools(
        self,
        tools: list[Any],
        intent: Intent,
        agent_type: str = "main",
        active_groups: set[str] | None = None,
    ) -> list[Any]:
        """过滤工具列表。

        Args:
            tools: 当前工具列表
            intent: 检测到的意图
            agent_type: agent 类型
            active_groups: 激活的能力域组

        Returns:
            过滤后的工具列表
        """
        allowed = self.get_allowed_tool_names(intent, agent_type, active_groups)
        filtered = []
        dropped = 0
        for t in tools:
            name = getattr(t, "name", "") if not isinstance(t, dict) else t.get("name", "")
            if name in allowed:
                filtered.append(t)
            else:
                dropped += 1
        if dropped:
            logger.info(
                "RuntimePermission: intent=%s agent=%s 允许 %d/%d 工具",
                intent.value, agent_type, len(filtered), len(tools),
            )
        return filtered

    def filter_tools_conservative(
        self,
        tools: list[Any],
    ) -> list[Any]:
        """保守模式过滤：只保留安全的读/查询工具。

        用于中置信度场景（0.5 ≤ confidence < 0.8）：
        不确定用户意图时，隐藏所有写/创建/执行类工具，
        只保留 fs_read、kb_*、wx_list/search 等安全工具。

        Args:
            tools: 当前工具列表

        Returns:
            过滤后的工具列表
        """
        filtered = []
        for t in tools:
            name = getattr(t, "name", "") if not isinstance(t, dict) else t.get("name", "")
            if name in _CONSERVATIVE_TOOLS:
                filtered.append(t)
        logger.info(
            "RuntimePermission(conservative): 保留 %d/%d 工具",
            len(filtered), len(tools),
        )
        return filtered
