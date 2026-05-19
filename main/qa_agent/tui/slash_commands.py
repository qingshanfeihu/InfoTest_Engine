"""Slash command system — parse + dispatch + 12 内置命令。



User-facing rules:
- Slash 命令以 ``/`` 开头
- 命令名是第一个词；后续 ``(MCP)`` 是 MCP 标识；其他都是 args
- ``/help`` 输出全部命令 + 描述
- ``/clear`` 清 transcript 但保留 token 计数 / thread_id
- ``/plan`` 切模式：下一次输入按 plan-only 语义(intercept)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, Optional

if TYPE_CHECKING:
    from main.qa_agent.tui.app import IstApp


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


@dataclass
class ParsedSlashCommand:
    """Parsed slash command."""

    command_name: str
    args: str
    is_mcp: bool = False


def parse_slash_command(text: str) -> Optional[ParsedSlashCommand]:
    """Parse a slash command string.

    Examples::

        parse_slash_command("/search foo bar")
        # -> ParsedSlashCommand(command_name="search", args="foo bar", is_mcp=False)

        parse_slash_command("/mcp:tool (MCP) arg1 arg2")
        # -> ParsedSlashCommand(command_name="mcp:tool (MCP)", args="arg1 arg2", is_mcp=True)
    """
    trimmed = (text or "").strip()
    if not trimmed.startswith("/"):
        return None
    without_slash = trimmed[1:]
    words = without_slash.split(" ")
    if not words[0]:
        return None
    command_name = words[0]
    is_mcp = False
    args_start_index = 1
    if len(words) > 1 and words[1] == "(MCP)":
        command_name = command_name + " (MCP)"
        is_mcp = True
        args_start_index = 2
    args = " ".join(words[args_start_index:])
    return ParsedSlashCommand(command_name=command_name, args=args, is_mcp=is_mcp)


# ---------------------------------------------------------------------------
# Result types — what a slash command can ask the app to do
# ---------------------------------------------------------------------------


@dataclass
class InfoResult:
    """Append a single-line info message to the transcript."""

    text: str


@dataclass
class TextResult:
    """Append a multi-line text block (e.g. /help output)."""

    text: str


@dataclass
class ClearResult:
    """Clear the conversation transcript (keep thread_id and token counters)."""


@dataclass
class ExitResult:
    """Exit the TUI."""


@dataclass
class InjectResult:
    """Inject a synthetic user prompt for the next LLM turn (e.g. /init)."""

    prompt: str


@dataclass
class InterceptResult:
    """Toggle a mode flag (e.g. /plan); the next user message gets that mode applied."""

    mode: str  # "plan" / "ask" / etc.


@dataclass
class ErrorResult:
    """Append an error message (red)."""

    text: str


SlashCommandResult = (
    InfoResult | TextResult | ClearResult | ExitResult
    | InjectResult | InterceptResult | ErrorResult
)


# ---------------------------------------------------------------------------
# SlashCommand definition
# ---------------------------------------------------------------------------


@dataclass
class SlashCommand:
    """Single command registry entry. Single command registry entry."""

    name: str
    description: str
    handler: Callable[[str, "IstApp"], SlashCommandResult]
    source: Literal["builtin", "plugin", "mcp"] = "builtin"


# ---------------------------------------------------------------------------
# Built-in command handlers
# ---------------------------------------------------------------------------


def _cmd_help(args: str, app: "IstApp") -> SlashCommandResult:
    lines = ["Available commands:", ""]
    for cmd in BUILTIN_COMMANDS:
        src_tag = f" ({cmd.source})" if cmd.source != "builtin" else ""
        lines.append(f"  /{cmd.name:<12} {cmd.description}{src_tag}")
    lines.append("")
    lines.append("Type any text without `/` to chat with IST-Core.")
    return TextResult(text="\n".join(lines))


def _cmd_clear(args: str, app: "IstApp") -> SlashCommandResult:
    return ClearResult()


def _cmd_exit(args: str, app: "IstApp") -> SlashCommandResult:
    return ExitResult()


def _cmd_version(args: str, app: "IstApp") -> SlashCommandResult:
    return InfoResult(text="infotest 0.1.0 (IST-Core TUI MVP)")


def _cmd_threads(args: str, app: "IstApp") -> SlashCommandResult:
    try:
        threads = app._checkpoint_repo.list_threads(limit=20)
    except Exception as exc:  # noqa: BLE001
        return ErrorResult(text=f"failed to list threads: {exc}")
    if not threads:
        if not app._checkpoint_repo.is_persistent:
            return InfoResult(
                text="(no threads — using InMemorySaver; "
                     "set QA_AGENT_SQLITE_PATH or QA_AGENT_POSTGRES_CHECKPOINT_DSN to persist)"
            )
        return InfoResult(text="(no threads found)")
    lines = ["Recent threads:", ""]
    for t in threads:
        preview = (t.preview or "")[:60].replace("\n", " ")
        tid_short = t.thread_id[-12:] if len(t.thread_id) > 12 else t.thread_id
        lines.append(f"  #{tid_short}  step={t.last_step}  {preview}")
    return TextResult(text="\n".join(lines))


def _cmd_resume(args: str, app: "IstApp") -> SlashCommandResult:
    tid = (args or "").strip()
    if not tid:
        return ErrorResult(text="usage: /resume <thread-id>")
    try:
        app._on_thread_selected(tid)
    except Exception as exc:  # noqa: BLE001
        return ErrorResult(text=f"failed to resume {tid}: {exc}")
    return InfoResult(text=f"resumed thread {tid}")


def _cmd_continue(args: str, app: "IstApp") -> SlashCommandResult:
    tid = app._checkpoint_repo.most_recent_thread_id()
    if not tid:
        return ErrorResult(text="no recent thread to continue")
    try:
        app._on_thread_selected(tid)
    except Exception as exc:  # noqa: BLE001
        return ErrorResult(text=f"failed to continue: {exc}")
    return InfoResult(text=f"continuing thread {tid}")


def _cmd_tier(args: str, app: "IstApp") -> SlashCommandResult:
    """List or switch model tier (3-tier).

    - /tier        -- list 3 tiers and each configured model
    - /tier <name> -- set default tier for next turn (opus / sonnet / haiku)
    """
    name = (args or "").strip().lower()
    try:
        from main.qa_agent.agents._llm import (
            TIER_ENV_VARS,
            qa_agent_default_model,
            qa_agent_tier_model,
        )
    except Exception as exc:  # noqa: BLE001
        return ErrorResult(text=f"failed to load tier helpers: {exc}")

    current = app.tui_state.__dict__.get("active_tier") or "sonnet"

    if not name:
        lines = ["Model tiers (3-tier):", ""]
        for tier_name in ("opus", "sonnet", "haiku"):
            model = qa_agent_tier_model(tier_name)
            mark = "● " if tier_name == current else "  "
            label = (
                f"{tier_name:6}  -> {model}"
                + ("  (current)" if tier_name == current else "")
            )
            lines.append(f"  {mark}{label}")
        lines.append("")
        lines.append("Usage: /tier <opus|sonnet|haiku>  — switch default tier for next turn")
        lines.append("")
        lines.append(
            "Configure each tier via env: "
            "QA_AGENT_OPUS_MODEL / QA_AGENT_SONNET_MODEL / QA_AGENT_HAIKU_MODEL"
        )
        return TextResult(text="\n".join(lines))

    if name not in TIER_ENV_VARS:
        return ErrorResult(text=(
            f"unknown tier {name!r}; valid: opus / sonnet / haiku"
        ))
    model = qa_agent_tier_model(name)
    app.tui_state.__dict__["active_tier"] = name
    app.tui_state.__dict__["override_model"] = model
    return InfoResult(text=(
        f"tier switched to {name} -> {model} (applies to next turn)"
    ))


def _cmd_model(args: str, app: "IstApp") -> SlashCommandResult:
    """List available models or switch to one. 

    - ``/model``        -> list available models(QA_AGENT_ALLOWED_MODELS env or default)
    - ``/model <name>`` -> switch model for next turn
    """
    name = (args or "").strip()
    try:
        from main.qa_agent.agents._llm import (
            qa_agent_allowed_models,
            qa_agent_default_model,
        )
        allowed = qa_agent_allowed_models()
        default = qa_agent_default_model()
    except Exception:  # noqa: BLE001
        allowed = []
        default = "qwen-plus"

    current = app.tui_state.__dict__.get("override_model") or default

    if not name:
        # 列出可用模型
        lines = ["Available models:", ""]
        for m in allowed:
            mark = "● " if m == current else "  "
            label = m + (" (current)" if m == current else "")
            label += " (default)" if m == default and m != current else ""
            lines.append(f"  {mark}{label}")
        lines.append("")
        lines.append("Usage: /model <name>  — switch model for next turn")
        if not allowed or len(allowed) == 1:
            lines.append("")
            lines.append(
                "(Configure ``QA_AGENT_ALLOWED_MODELS=`` env to add more model options)"
            )
        return TextResult(text="\n".join(lines))

    # 切换：检查是否在 allowed 列表
    if allowed and name not in allowed:
        return ErrorResult(text=(
            f"model {name!r} not in allowed list: {allowed}.\n"
            f"Set QA_AGENT_ALLOWED_MODELS env to expand."
        ))
    app.tui_state.__dict__["override_model"] = name
    return InfoResult(text=f"model switched to {name} (applies to next turn)")


def _cmd_cost(args: str, app: "IstApp") -> SlashCommandResult:
    used = app.tui_state.tokens_used
    budget = app.tui_state.tokens_budget
    pct = (used / budget * 100) if budget else 0
    llm_calls = app.tui_state.llm_calls
    tool_calls = app.tui_state.tool_calls
    return TextResult(text=(
        f"Token usage:\n"
        f"  used:    {used:,}\n"
        f"  budget:  {budget:,}\n"
        f"  percent: {pct:.1f}%\n"
        f"  LLM calls: {llm_calls}\n"
        f"  tool calls: {tool_calls}"
    ))


def _cmd_compact(args: str, app: "IstApp") -> SlashCommandResult:
    # MVP: compact 由 deepagents summarization_middleware 自动触发；
    # /compact 当前只是手动重置 token 累计 + 清屏(保留 thread)
    app.tui_state.tokens_used = 0
    return ClearResult()


def _cmd_plan(args: str, app: "IstApp") -> SlashCommandResult:
    # 设置 mode flag；下一次 user input 会被加 plan 模式 system prompt 前缀
    return InterceptResult(mode="plan")


def _cmd_init(args: str, app: "IstApp") -> SlashCommandResult:
    return InjectResult(prompt=(
        "请帮我做项目初始化分析：\n"
        "1. 用 qa_deepagent_ls 看顶级目录\n"
        "2. 读关键文档(README.md、AGENTS.md)\n"
        "3. 用 qa_deepagent_glob 找 Python 包结构\n"
        "4. 给一份项目能力总结报告(5 段以内)"
    ))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


BUILTIN_COMMANDS: list[SlashCommand] = [
    SlashCommand("help",     "List all commands with descriptions",          _cmd_help),
    SlashCommand("clear",    "Clear conversation transcript (keep thread)",  _cmd_clear),
    SlashCommand("threads",  "List recent threads with previews",            _cmd_threads),
    SlashCommand("resume",   "Resume specific thread (usage: /resume <tid>)", _cmd_resume),
    SlashCommand("continue", "Resume the most recent thread",                _cmd_continue),
    SlashCommand("model",    "Override LLM model for next turn",             _cmd_model),
    SlashCommand("tier",     "Show / switch 3-tier model (opus/sonnet/haiku)", _cmd_tier),
    SlashCommand("cost",     "Show token usage and call counts",             _cmd_cost),
    SlashCommand("compact",  "Reset token counter (clears transcript)",      _cmd_compact),
    SlashCommand("plan",     "Toggle plan-only mode for next query",         _cmd_plan),
    SlashCommand("init",     "Run project bootstrap analysis workflow",      _cmd_init),
    SlashCommand("version",  "Print version",                                _cmd_version),
    SlashCommand("exit",     "Exit the TUI",                                 _cmd_exit),
]

#: Map command_name -> SlashCommand for O(1) dispatch
COMMAND_REGISTRY: dict[str, SlashCommand] = {cmd.name: cmd for cmd in BUILTIN_COMMANDS}


# ---------------------------------------------------------------------------
# Public dispatch helpers
# ---------------------------------------------------------------------------


def dispatch_slash_command(parsed: ParsedSlashCommand, app: "IstApp") -> SlashCommandResult:
    """Look up the command in the registry and run its handler.

    Unknown command -> ErrorResult.
    """
    cmd = COMMAND_REGISTRY.get(parsed.command_name)
    if cmd is None:
        return ErrorResult(text=(
            f"Unknown command: /{parsed.command_name}. "
            f"Type /help for the list of commands."
        ))
    try:
        return cmd.handler(parsed.args, app)
    except Exception as exc:  # noqa: BLE001
        return ErrorResult(text=f"command /{parsed.command_name} crashed: {exc}")


def filter_completions(prefix: str, *, limit: int = 8) -> list[SlashCommand]:
    """Return commands whose names start with ``prefix`` (case-insensitive).

    Used by widgets/slash_completion.py to populate the footer pill.
    
    """
    if prefix.startswith("/"):
        prefix = prefix[1:]
    prefix = prefix.lower()
    matches = [cmd for cmd in BUILTIN_COMMANDS if cmd.name.lower().startswith(prefix)]
    return matches[:limit]
