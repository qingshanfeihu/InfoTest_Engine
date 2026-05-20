"""IstMessage 基类与 17 类子类——TUI 的渲染契约。

这是「通用 tools/skills 的渲染契约」核心：每种通用工具/能力对应一个消息子类，
MessageLog 按 ``isinstance`` 派发到专属 widget。新增通用 tool/skill 时只需新增一个
消息子类 + dispatch 表加一行 + 写一个 widget，不动 sink 主逻辑。


  AssistantTextMessage     → AIThinkingMessage / AIFinalMessage
  AssistantToolUseMessage  → ToolCallMessage（泛型 fallback）
  UserBashInputMessage     → BashExecMessage
  UserBashOutputMessage    → BashExecMessage（同消息双段渲染）
  TaskAssignmentMessage    → SubAgentDispatchMessage
  PlanApprovalMessage      → HilRequestMessage / HilDecisionMessage
  HookProgressMessage      → PhaseMarkerMessage（暂保留）

Tool name dispatch table is documented at the bottom; TuiSink consumes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class IstMessage:
    """所有 TUI 消息的基类。携带事件溯源公共字段。"""

    run_id: str = ""
    seq: int = 0
    ts: str = ""

    #: 子类的 widget CSS class 标识，用于 Textual styling 派发。
    css_class: ClassVar[str] = "ist-message"


# ---------------------------------------------------------------------------
# Conversation messages
# ---------------------------------------------------------------------------


@dataclass
class HumanInputMessage(IstMessage):
    """用户输入。"""

    text: str = ""
    css_class: ClassVar[str] = "ist-human-input"


@dataclass
class AIThinkingMessage(IstMessage):
    """流式 token 累积块。``content`` 在 llm_token 到达时增量追加。

    llm_end 事件触发后，外层逻辑会用同 run_id+seq 的 AIFinalMessage 替换这个实例，
    从纯文本切换到 Markdown 渲染（避免每 token 重渲染整树）。
    """

    content: str = ""
    css_class: ClassVar[str] = "ist-ai-thinking"


@dataclass
class AIFinalMessage(IstMessage):
    """LLM 完成后的最终消息。Markdown 渲染 + 章节自动折叠 + P0/P1/P2/P3 高亮。"""

    content: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    css_class: ClassVar[str] = "ist-ai-final"


# ---------------------------------------------------------------------------
# Generic tool fallback (must remain after specialized subclasses for dispatch)
# ---------------------------------------------------------------------------


@dataclass
class ToolCallMessage(IstMessage):
    """泛型工具调用 fallback。所有未识别工具走这里。"""

    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-tool-call"


# ---------------------------------------------------------------------------
# Specialized tool messages (each maps to a generic tool/skill in IST-Core)
# ---------------------------------------------------------------------------


@dataclass
class PlatformTaskMessage(IstMessage):
    """``qa_platform_run_task`` 4 段渲染：session / task / allowed_tools / result。

    高亮 ``dry_run`` 边界与 ``permission_profile`` 切换。对应
    main/qa_agent/tools/platform/runtime.py。
    """

    session: dict[str, Any] = field(default_factory=dict)
    task: dict[str, Any] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = True
    permission_profile: str = ""
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-platform-task"


@dataclass
class FileReadMessage(IstMessage):
    """``qa_deepagent_read_file`` 文本/源码渲染。语法高亮 + 折叠（>200 行）。"""

    path: str = ""
    content: str = ""
    lines: int = 0
    truncated: bool = False
    language: str = "text"
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-file-read"


@dataclass
class XlsxSheetMessage(IstMessage):
    """``read_file & path.endswith(.xlsx)`` 多 sheet TabbedContent 渲染。

    数据来源：``main/qa_agent/tools/deepagent/file_tools.py:171-196`` 的 ``_read_spreadsheet``，
    返回的格式化文本由 TuiSink 解析回 sheets 字典。

    summary 段统计字段空值率，对齐 cluade.md 步骤 2 的 274 行用例分析。
    """

    workbook_path: str = ""
    sheets: dict[str, list[list[str]]] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-xlsx-sheet"


@dataclass
class GrepHitsMessage(IstMessage):
    """``qa_deepagent_grep`` 命中表格：path / line / preview。"""

    pattern: str = ""
    hits: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-grep-hits"


@dataclass
class LsTreeMessage(IstMessage):
    """``qa_deepagent_ls`` / glob 目录树。"""

    path: str = ""
    entries: list[dict[str, Any]] = field(default_factory=list)
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-ls-tree"


@dataclass
class PythonExecMessage(IstMessage):
    """``qa_exec`` 执行结果。命令头 + stdout(syntax) + stderr(red) + 返回码 + 耗时。

    See main/qa_agent/tools/deepagent/exec_tools.py (Stage 4 新建).
    
    """

    code: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    elapsed_ms: int = 0
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-python-exec"


@dataclass
class BashExecMessage(IstMessage):
    """``qa_bash`` 执行结果.

    
    """

    command: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    elapsed_ms: int = 0
    status: str = "pending"  # pending | running | done | error
    css_class: ClassVar[str] = "ist-bash-exec"


@dataclass
class SubAgentDispatchMessage(IstMessage):
    """4 sub-agent 并行委派的层级渲染 + 各 sub-agent 独立 telemetry。

    对应 main/qa_agent/agents/hierarchical/sub_agents/，沿用 deepagents
    middleware/subagents.py 的 SubAgent 接口。
    """

    name: str = ""
    status: str = "pending"  # pending | running | done | error
    telemetry: dict[str, Any] = field(default_factory=dict)
    child_messages: list[IstMessage] = field(default_factory=list)
    css_class: ClassVar[str] = "ist-subagent-dispatch"


@dataclass
class SkillAssembledPromptMessage(IstMessage):
    """SkillAssembler 装配后的 system prompt 折叠预览。

    对应 main/qa_agent/agents/_prompt_assembler.py。
    """

    skill_name: str = ""
    fragments: list[str] = field(default_factory=list)
    assembled_prompt: str = ""
    css_class: ClassVar[str] = "ist-skill-prompt"


# ---------------------------------------------------------------------------
# HIL messages (LangGraph interrupt() protocol)
# ---------------------------------------------------------------------------


@dataclass
class HilRequestMessage(IstMessage):
    """``graph.py:469-493`` 的 hil_gate 触发 interrupt() 时的请求。"""

    findings: dict[str, Any] = field(default_factory=dict)
    draft_answer: str = ""
    reason: str = ""
    css_class: ClassVar[str] = "ist-hil-request"


@dataclass
class HilDecisionMessage(IstMessage):
    """用户在 HilModal 中作出决策后的回写记录。

    Decision dict 形状对齐 graph.py:485-493:
      {"approved": bool, "override_answer": Optional[str]}
    """

    decision: dict[str, Any] = field(default_factory=dict)
    css_class: ClassVar[str] = "ist-hil-decision"


# ---------------------------------------------------------------------------
# Process / phase / log messages
# ---------------------------------------------------------------------------


@dataclass
class PhaseMarkerMessage(IstMessage):
    """Reviewer 专用 phase_marker。通用 main_agent 不发，由 ProgressTrail
    fallback 到 node_start/end 自行推导。"""

    phase: str = ""
    css_class: ClassVar[str] = "ist-phase-marker"


@dataclass
class EvidenceMessage(IstMessage):
    """evidence_added 事件。"""

    payload: dict[str, Any] = field(default_factory=dict)
    css_class: ClassVar[str] = "ist-evidence"


@dataclass
class FindingMessage(IstMessage):
    """finding_emitted / finding_written 事件。"""

    payload: dict[str, Any] = field(default_factory=dict)
    css_class: ClassVar[str] = "ist-finding"


@dataclass
class ErrorMessage(IstMessage):
    text: str = ""
    css_class: ClassVar[str] = "ist-error"


@dataclass
class WarnMessage(IstMessage):
    text: str = ""
    css_class: ClassVar[str] = "ist-warn"


@dataclass
class InfoMessage(IstMessage):
    text: str = ""
    css_class: ClassVar[str] = "ist-info"


@dataclass
class WelcomeMessage(IstMessage):
    """启动屏的欢迎 box（WelcomeV2 等价，简化版）。

    显示在消息流顶部，用户首次提交后被移除。
    """

    cwd: str = ""
    model: str = ""
    tips: list[str] = field(default_factory=list)
    css_class: ClassVar[str] = "ist-welcome"


@dataclass
class ThinkingMessage(IstMessage):
    """LLM 输出里 ``type=thinking`` block 的渲染消息.

    
    默认折叠为 ``∴ Thinking (ctrl+o to expand)``；按 Ctrl+O 切换展开为 dim markdown。
    qwen3 系列、Claude 系列都支持 thinking 输出。

    上游字段（Anthropic SDK ThinkingBlock）：
      - type: "thinking"
      - thinking: str    （UI 显示的内容）
      - signature: str   （API 内部签名；UI 不渲染）
    """

    thinking: str = ""
    css_class: ClassVar[str] = "ist-thinking"


# ---------------------------------------------------------------------------
# Dispatch table — TuiSink consumes this to map ``tool_call.name`` → subclass
# ---------------------------------------------------------------------------


#: 工具名到消息子类的映射。新增通用 tool 时只在这里加一行。
#: 顺序无关——TuiSink 用 dict.get(name, ToolCallMessage) 查找。
TOOL_NAME_TO_MESSAGE: dict[str, type[IstMessage]] = {
    "qa_platform_run_task": PlatformTaskMessage,
    "qa_deepagent_read_file": FileReadMessage,  # xlsx 路径由 TuiSink 二次判断升级为 XlsxSheetMessage
    "qa_deepagent_grep": GrepHitsMessage,
    "qa_deepagent_ls": LsTreeMessage,
    "qa_deepagent_glob": LsTreeMessage,
    "qa_exec": PythonExecMessage,
    "qa_bash": BashExecMessage,
}
