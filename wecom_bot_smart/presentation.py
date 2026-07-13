"""Agent Presentation Layer —— 内部事件 → 用户可理解状态的隔离层。

架构位置::

    Agent Runtime
          |
          v
    IstCoreEvent (EventBus)
          |
          +----------------+
          |                |
          v                v
    EventAuditLogger   Presentation Layer
                           |
                           v
                     ThoughtRenderer
                           |
                           v
                     UserVisibleEvent → WeCom Stream

设计原则：
- 不修改业务逻辑、Agent 行为或 Tool 执行
- 原始 thought 文本不进入用户通道（仅审计日志保留）
- AgentPhase 状态机避免重复状态刷屏
- ToolDisplayConfig 三级匹配：精确 → 前缀 → 默认
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("wecom_bot_smart.presentation")


# ============================================================================
# 1. Agent Phase 状态机
# ============================================================================

class AgentPhase(Enum):
    """Agent 工作阶段，控制用户可见的状态展示。"""
    IDLE        = "idle"
    UNDERSTANDING = "understanding"  # 理解需求（LLM 首次推理）
    SEARCHING   = "searching"        # 搜索/读取资料
    EXECUTING   = "executing"        # 执行任务（设备/编译/脚本）
    ANALYZING   = "analyzing"        # 分析结果
    GENERATING  = "generating"       # 生成最终回答
    DONE        = "done"


# Phase 展示文案（进入该 phase 时显示，同一 phase 内不重复）
_PHASE_DISPLAY: dict[AgentPhase, str] = {
    AgentPhase.UNDERSTANDING: "🧠 正在理解需求…",
    AgentPhase.SEARCHING:     "🔍 正在查找信息…",
    AgentPhase.EXECUTING:     "⚙️ 正在执行任务…",
    AgentPhase.ANALYZING:     "📊 正在分析结果…",
    AgentPhase.GENERATING:    "✍️ 正在整理答案…",
}


# ============================================================================
# 2. UserVisibleEvent 模型
# ============================================================================

class UserEventType(Enum):
    """用户可见事件类型。"""
    THINKING    = "thinking"     # 阶段变化 → 状态行
    TOOL_STATUS = "tool_status"  # 工具状态（友好描述，非原始名）
    ASK_USER    = "ask_user"     # 等待用户输入
    ERROR       = "error"        # 错误
    HEARTBEAT   = "heartbeat"    # 保活
    ANSWER      = "answer"       # 最终答案（generator return value）


@dataclass
class UserVisibleEvent:
    """Presentation Layer 产出的用户可见事件。

    所有字段都不包含内部工具名、原始参数或 LLM 思考文本。
    """
    type: UserEventType
    content: str = ""          # 用户可见的友好文本
    phase: AgentPhase = AgentPhase.IDLE
    tool_name: str = ""        # 内部工具名（仅 gateway 内部用于 render 和 audit）
    metadata: dict[str, Any] = field(default_factory=dict)
    # 文件追踪（内部用，不展示给用户）
    written_file: str = ""


# ============================================================================
# 3. Tool Display Config（三级匹配）
# ============================================================================

@dataclass
class ToolDisplayConfig:
    """单个工具的用户展示配置。"""
    icon: str
    message: str            # 正在{message}… / {message}完成
    phase: AgentPhase = AgentPhase.EXECUTING  # 该工具归属的 Agent 阶段


# 精确匹配表（前缀条目用 "*" 结尾）
TOOL_DISPLAY_CONFIG: dict[str, ToolDisplayConfig] = {
    # ---- 文件系统 ----
    "fs_read":   ToolDisplayConfig(icon="📄", message="正在读取文件",
                                   phase=AgentPhase.SEARCHING),
    "fs_write":  ToolDisplayConfig(icon="📝", message="正在保存文件",
                                   phase=AgentPhase.EXECUTING),
    "fs_edit":   ToolDisplayConfig(icon="✏️", message="正在编辑文件",
                                   phase=AgentPhase.EXECUTING),
    "fs_ls":     ToolDisplayConfig(icon="📂", message="正在浏览目录",
                                   phase=AgentPhase.SEARCHING),
    "fs_glob":   ToolDisplayConfig(icon="🔎", message="正在查找文件",
                                   phase=AgentPhase.SEARCHING),
    "fs_grep":   ToolDisplayConfig(icon="🔍", message="正在搜索内容",
                                   phase=AgentPhase.SEARCHING),
    # ---- 知识库 ----
    "kb_footprint":     ToolDisplayConfig(icon="📚", message="正在查阅技术文档",
                                          phase=AgentPhase.SEARCHING),
    "kb_bug_search":    ToolDisplayConfig(icon="🐛", message="正在查询缺陷库",
                                          phase=AgentPhase.SEARCHING),
    "kb_memory_search": ToolDisplayConfig(icon="🧠", message="正在检索历史记录",
                                          phase=AgentPhase.SEARCHING),
    # ---- 设备（前缀匹配） ----
    "dev_*":            ToolDisplayConfig(icon="⚙️", message="正在操作设备",
                                          phase=AgentPhase.EXECUTING),
    # ---- 编译（前缀匹配） ----
    "compile_*":        ToolDisplayConfig(icon="🔧", message="正在编译处理",
                                          phase=AgentPhase.EXECUTING),
    "submit_*":         ToolDisplayConfig(icon="📋", message="正在提交结果",
                                          phase=AgentPhase.EXECUTING),
    # ---- 元工具 ----
    "invoke_skill":     ToolDisplayConfig(icon="🤖", message="正在调用分析任务",
                                          phase=AgentPhase.EXECUTING),
    "agent_define":     ToolDisplayConfig(icon="🤖", message="正在定义子任务",
                                          phase=AgentPhase.EXECUTING),
    "task":             ToolDisplayConfig(icon="🔄", message="正在执行子任务",
                                          phase=AgentPhase.EXECUTING),
    # ---- 脚本 ----
    "run_python":       ToolDisplayConfig(icon="🐍", message="正在运行数据分析",
                                          phase=AgentPhase.EXECUTING),
    "run_shell":        ToolDisplayConfig(icon="💻", message="正在执行系统命令",
                                          phase=AgentPhase.EXECUTING),
    # ---- 其他 ----
    "ask_user":         ToolDisplayConfig(icon="❓", message="等待用户输入",
                                          phase=AgentPhase.IDLE),
    "remember":         ToolDisplayConfig(icon="💾", message="正在保存记忆",
                                          phase=AgentPhase.EXECUTING),
    "wx_send_file":     ToolDisplayConfig(icon="📤", message="正在发送文件",
                                          phase=AgentPhase.EXECUTING),
}

# 默认配置（三级匹配的兜底）
_DEFAULT_CONFIG = ToolDisplayConfig(icon="🤖", message="正在执行任务",
                                    phase=AgentPhase.EXECUTING)


def lookup_tool_config(tool_name: str) -> ToolDisplayConfig:
    """三级匹配：精确 → 前缀（`prefix_*`）→ 默认。

    >>> cfg = lookup_tool_config("fs_read")
    >>> cfg.icon
    '📄'
    >>> cfg = lookup_tool_config("dev_run_batch")
    >>> cfg.icon
    '⚙️'
    >>> cfg = lookup_tool_config("totally_unknown")
    >>> cfg.icon
    '🤖'
    """
    # 1. 精确匹配
    if tool_name in TOOL_DISPLAY_CONFIG:
        return TOOL_DISPLAY_CONFIG[tool_name]
    # 2. 前缀匹配（配置中以 * 结尾的条目）
    for pattern, cfg in TOOL_DISPLAY_CONFIG.items():
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            if tool_name.startswith(prefix):
                return cfg
    # 3. 默认
    return _DEFAULT_CONFIG


# ============================================================================
# 4. Event Audit Logger
# ============================================================================

class EventAuditLogger:
    """记录所有经过 Presentation Layer 的原始事件，用于 debug 和分析。

    与用户展示完全分离——这里保留完整内部信息（工具名、参数等）。
    """

    def __init__(self, max_entries: int = 200) -> None:
        self._entries: list[dict[str, Any]] = []
        self._max = max_entries

    def log(self, kind: str, payload: dict[str, Any],
            user_visible: str = "", visible: bool = False) -> None:
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "kind": kind,
            "name": payload.get("name", ""),
            "user_visible": user_visible,
            "visible": visible,
        }
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]
        logger.debug("audit: kind=%s name=%s visible=%s",
                     kind, entry["name"], visible)

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def to_json(self) -> str:
        return json.dumps(self._entries, ensure_ascii=False, indent=2)


# ============================================================================
# 5. ThoughtRenderer（核心渲染器）
# ============================================================================

class ThoughtRenderer:
    """有状态渲染器：IstCoreEvent → UserVisibleEvent。

    内部维护 AgentPhase 状态机：
    - 相同 phase 内连续工具调用只在首次进入时产生一条状态消息
    - phase 转换时产生新的状态消息
    - 原始 thought 文本不进入输出（仅审计日志保留）
    """

    def __init__(self) -> None:
        self._current_phase: AgentPhase = AgentPhase.IDLE
        self._announced_phases: set[AgentPhase] = set()
        self._last_shown_tool: str = ""
        self._last_shown_detail: str = ""
        self._audit = EventAuditLogger()

    @property
    def current_phase(self) -> AgentPhase:
        return self._current_phase

    @property
    def audit(self) -> EventAuditLogger:
        return self._audit

    def _transition(self, new_phase: AgentPhase) -> bool:
        """转到新 phase，返回是否为首次进入该 phase。"""
        self._current_phase = new_phase
        if new_phase in self._announced_phases:
            return False
        self._announced_phases.add(new_phase)
        return True

    @staticmethod
    def _parse_raw_input(raw: str) -> dict[str, str]:
        """从 Python repr 字符串中提取 key-value 对。

        streaming.py 把 dict 转成了 repr 字符串如 "{'skill': 'config-answer', ...}"。
        """
        import re as _re
        result: dict[str, str] = {}
        for m in _re.finditer(r"'(\w+)':\s*'([^']*)'", raw):
            result[m.group(1)] = m.group(2)
        return result

    def _extract_detail(self, tool_name: str, input_data: dict[str, Any]) -> str:
        """从工具输入中提取有意义的上下文信息（如文件名、搜索词）。"""
        if not input_data:
            return ""
        # 如果 input_data 是 {"raw": "repr字符串"}，先解析
        if set(input_data.keys()) == {"raw"}:
            parsed = self._parse_raw_input(input_data["raw"])
            if parsed:
                input_data = parsed
        # 搜索/查询类 → 显示搜索词（必须在 fs_ 之前，因为 fs_grep 也以 fs_ 开头）
        if tool_name in ("fs_grep", "kb_bug_search", "kb_memory_search"):
            for key in ("search_term", "query", "pattern", "grep", "raw"):
                val = input_data.get(key)
                if isinstance(val, str) and val:
                    return val[:40]
        # 文件操作 → 显示文件名
        if tool_name.startswith("fs_"):
            path = input_data.get("path") or input_data.get("file_path") or ""
            if path:
                return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        # invoke_skill → 显示 skill 名
        if tool_name == "invoke_skill":
            for key in ("skill", "raw", "query"):
                val = input_data.get(key)
                if isinstance(val, str) and val:
                    return val.split("(")[0].strip()[:40]  # 去掉括号内 brief
            # 兜底：如果 input 本身就是字符串
            if isinstance(input_data, str):
                return input_data[:40]
        logger.debug("extract_detail: tool=%s keys=%s result=%r",
                     tool_name, list(input_data.keys())[:5], "")
        return ""

    def process_event(self, kind: str, payload: dict[str, Any],
                      input_data: dict[str, Any] | None = None) -> UserVisibleEvent | None:
        """处理一个 IstCoreEvent，返回用户可见事件（或 None 表示抑制）。

        完整的内部信息仅记录到审计日志。
        """
        name = payload.get("name", "")

        # --- 工具调用开始 ---
        if kind == "tool_call" or kind == "tool_start":
            cfg = lookup_tool_config(name)
            detail = self._extract_detail(name, input_data or {})
            display = f"{cfg.icon} {cfg.message}"
            if detail:
                display += f" {detail}"
            self._audit.log(kind, payload, user_visible=display, visible=True)
            is_new_phase = self._transition(cfg.phase)
            # 展示条件：新 phase / 有 detail 且不同于上次 / 不同工具
            same_as_last = (name == self._last_shown_tool
                            and detail == self._last_shown_detail)
            should_show = is_new_phase or (detail and not same_as_last) or (name != self._last_shown_tool)
            if not should_show:
                return None
            self._last_shown_tool = name
            self._last_shown_detail = detail
            return UserVisibleEvent(
                type=UserEventType.THINKING,
                content=display,
                phase=self._current_phase,
            )

        # --- 工具调用结束 ---
        if kind == "tool_result" or kind == "tool_end":
            self._audit.log(kind, payload, visible=False)
            # tool_end 不直接展示给用户（避免重复刷屏）
            return None

        # --- LLM 思考（thought / final_thought） ---
        if kind == "llm_end" and name in ("thought", "final_thought"):
            self._audit.log(kind, payload,
                            user_visible="🧠 正在分析…",
                            visible=True)
            if name == "final_thought":
                is_new = self._transition(AgentPhase.GENERATING)
            else:
                is_new = self._transition(AgentPhase.UNDERSTANDING)
            if not is_new:
                return None
            return UserVisibleEvent(
                type=UserEventType.THINKING,
                content=_PHASE_DISPLAY.get(self._current_phase, "🧠 正在分析…"),
                phase=self._current_phase,
            )

        # --- LLM token（流式输出 token） ---
        if kind == "llm_token":
            self._audit.log(kind, payload, visible=False)
            # 不直接展示——最终答案来自 generator return value
            return None

        # --- 阶段标记 ---
        if kind == "phase_marker":
            self._audit.log(kind, payload, visible=False)
            return None

        # --- ask_user ---
        if kind == "ask_user_request":
            self._audit.log(kind, payload,
                            user_visible="❓ 等待用户输入",
                            visible=True)
            return UserVisibleEvent(
                type=UserEventType.ASK_USER,
                content="❓ 等待用户输入",
                phase=AgentPhase.IDLE,
                metadata=payload,
            )

        # --- 错误 ---
        if kind in ("error", "run_error"):
            error_msg = payload.get("error", "") or payload.get("message", "")
            self._audit.log(kind, payload,
                            user_visible=f"❌ {error_msg}",
                            visible=True)
            return UserVisibleEvent(
                type=UserEventType.ERROR,
                content=error_msg,
                phase=self._current_phase,
            )

        # --- 其他事件（info, node_start/end 等） ---
        self._audit.log(kind, payload, visible=False)
        return None

    def render_summary(self, tool_names: list[str],
                       tool_details: dict[str, str] | None = None) -> str:
        """从工具名列表生成处理过程摘要（用于最终消息折叠区）。

        tool_details: tool_name → 提取的上下文信息（如文件名、搜索词）。
        按首次出现顺序去重，展示友好的中文描述（已完成状态）。
        """
        if not tool_names:
            return ""
        details = tool_details or {}
        seen: set[str] = set()
        steps: list[str] = []
        for name in tool_names:
            if name in seen:
                continue
            seen.add(name)
            cfg = lookup_tool_config(name)
            done_msg = cfg.message.replace("正在", "已").replace("等待", "已等待")
            detail = details.get(name, "")
            step = f"{cfg.icon} {done_msg}"
            if detail:
                step += f" {detail}"
            steps.append(step)
        if not steps:
            return ""
        return (
            '<details><summary>📋 处理过程</summary>\n\n'
            + " · ".join(steps)
            + "\n\n</details>"
        )
