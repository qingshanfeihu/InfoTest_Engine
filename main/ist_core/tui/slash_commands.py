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
    from main.ist_core.tui.app import IstApp






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

    mode: str


@dataclass
class ErrorResult:
    """Append an error message (red)."""

    text: str


SlashCommandResult = (
    InfoResult | TextResult | ClearResult | ExitResult
    | InjectResult | InterceptResult | ErrorResult
)







@dataclass
class SlashCommand:
    """Single command registry entry. Single command registry entry."""

    name: str
    description: str
    handler: Callable[[str, "IstApp"], SlashCommandResult]
    source: Literal["builtin", "plugin", "mcp"] = "builtin"







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
    return InfoResult(text="infotest 1.0.4 (IST-Core)")


def _cmd_threads(args: str, app: "IstApp") -> SlashCommandResult:
    try:
        threads = app._checkpoint_repo.list_threads(limit=20)
    except Exception as exc:  # noqa: BLE001
        return ErrorResult(text=f"failed to list threads: {exc}")
    if not threads:
        if not app._checkpoint_repo.is_persistent:
            return InfoResult(
                text="(no threads — using InMemorySaver; "
                     "set IST_SQLITE_PATH or IST_POSTGRES_CHECKPOINT_DSN to persist)"
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


def _cmd_model(args: str, app: "IstApp") -> SlashCommandResult:
    """List available models or switch to one. 

    - ``/model``        -> list available models(IST_ALLOWED_MODELS env or default)
    - ``/model <name>`` -> switch model for next turn
    """
    name = (args or "").strip()
    try:
        from main.ist_core.agents._llm import (
            ist_core_allowed_models,
            ist_core_default_model,
        )
        allowed = ist_core_allowed_models()
        default = ist_core_default_model()
    except Exception:  # noqa: BLE001
        allowed = []
        default = "qwen-plus"

    current = app.tui_state.__dict__.get("override_model") or default

    if not name:
        lines = ["Available models:", ""]
        for m in allowed:
            mark = "● " if m == current else "  "
            label = m + (" (current)" if m == current else "")
            label += " (default)" if m == default and m != current else ""
            lines.append(f"  {mark}{label}")
        lines.append("")
        lines.append("Usage: /model <name>  — switch model for next turn")
        
        try:
            from main.ist_core.agents._llm import ist_core_tier_model
            lines.append("")
            lines.append("Model tiers:")
            for tier_name in ("opus", "sonnet", "haiku"):
                tier_model = ist_core_tier_model(tier_name)
                lines.append(f"  {tier_name:6} -> {tier_model}")
        except Exception:  # noqa: BLE001
            pass
        if not allowed or len(allowed) == 1:
            lines.append("")
            lines.append(
                "(Configure ``IST_ALLOWED_MODELS=`` env to add more model options)"
            )
        return TextResult(text="\n".join(lines))

    
    if allowed and name not in allowed:
        return ErrorResult(text=(
            f"model {name!r} not in allowed list: {allowed}.\n"
            f"Set IST_ALLOWED_MODELS env to expand."
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
    
    
    app.tui_state.tokens_used = 0
    return ClearResult()


def _cmd_plan(args: str, app: "IstApp") -> SlashCommandResult:
    
    return InterceptResult(mode="plan")


def _cmd_style(args: str, app: "IstApp") -> SlashCommandResult:
    """切换输出风格。"""
    from main.ist_core.output_styles import OUTPUT_STYLES, set_active_style, get_active_style

    name = (args or "").strip().lower()
    current = get_active_style()

    if not name:
        lines = ["Output styles:", ""]
        for key, cfg in OUTPUT_STYLES.items():
            mark = "● " if key == current else "  "
            label = cfg.name + (" (current)" if key == current else "")
            lines.append(f"  {mark}{label} — {cfg.description}")
        lines.append("")
        lines.append("Usage: /style <name>")
        return TextResult(text="\n".join(lines))

    if name not in OUTPUT_STYLES:
        available = ", ".join(OUTPUT_STYLES.keys())
        return ErrorResult(text=f"unknown style {name!r}. Available: {available}")

    set_active_style(name)
    style_cfg = OUTPUT_STYLES[name]
    return InfoResult(text=f"output style → {style_cfg.name}")


def _cmd_init(args: str, app: "IstApp") -> SlashCommandResult:
    return InjectResult(prompt=(
        "请帮我做项目初始化分析：\n"
        "1. 用 fs_ls 看顶级目录\n"
        "2. 读关键文档(README.md、AGENTS.md)\n"
        "3. 用 fs_glob 找 Python 包结构\n"
        "4. 给一份项目能力总结报告(5 段以内)"
    ))


def _cmd_reset(args: str, app: "IstApp") -> SlashCommandResult:
    """清除对话历史和 agent 临时存储文件。

    用法::

        /reset           — 默认清理（保留长期记忆）
        /reset --all     — 同时清理长期记忆
    """
    from main.ist_core.tui.reset_command import perform_reset

    include_long_term = "--all" in (args or "")
    try:
        result = perform_reset(include_long_term=include_long_term)
    except Exception as exc:  # noqa: BLE001
        return ErrorResult(text=f"reset failed: {exc}")
    return TextResult(text=result.summary())








def _cmd_skill_dispatch(args: str, app: "IstApp") -> SlashCommandResult:
    from main.ist_core.tui.skill_command import cmd_skill
    return cmd_skill(args, app)


def _cmd_footprint_dispatch(args: str, app: "IstApp") -> SlashCommandResult:
    from main.ist_core.tui.footprint_command import cmd_footprint
    return cmd_footprint(args, app)


def _cmd_memory_dispatch(args: str, app: "IstApp") -> SlashCommandResult:
    from main.ist_core.tui.memory_command import cmd_memory
    return cmd_memory(args, app)


def _cmd_remember_dispatch(args: str, app: "IstApp") -> SlashCommandResult:
    from main.ist_core.tui.memory_command import cmd_remember
    return cmd_remember(args, app)


BUILTIN_COMMANDS: list[SlashCommand] = [
    SlashCommand("help",     "List all commands with descriptions",          _cmd_help),
    SlashCommand("clear",    "Clear conversation transcript (keep thread)",  _cmd_clear),
    SlashCommand("threads",  "List recent threads with previews",            _cmd_threads),
    SlashCommand("resume",   "Resume specific thread (usage: /resume <tid>)", _cmd_resume),
    SlashCommand("continue", "Resume the most recent thread",                _cmd_continue),
    SlashCommand("model",    "Override LLM model for next turn",             _cmd_model),
    SlashCommand("style",    "Switch output style (explanatory / learning / default)", _cmd_style),
    SlashCommand("cost",     "Show token usage and call counts",             _cmd_cost),
    SlashCommand("compact",  "Reset token counter (clears transcript)",      _cmd_compact),
    SlashCommand("plan",     "Toggle plan-only mode for next query",         _cmd_plan),
    SlashCommand("init",     "Run project bootstrap analysis workflow",      _cmd_init),
    SlashCommand("reset",    "Clear conversation history and temp storage (--all for long-term)", _cmd_reset),
    SlashCommand("memory",   "Memory overview / show / clear (subcommands: show, clear, status)", _cmd_memory_dispatch),
    SlashCommand("remember", "Add user preference / feedback / project / reference",   _cmd_remember_dispatch),
    SlashCommand("skill",    "Skill on/off/all — /skill on|off <name>, /skill all",         _cmd_skill_dispatch),
    SlashCommand("footprint","Footprint knowledge tree (subcommands: show, search, stats, list)", _cmd_footprint_dispatch),
    SlashCommand("version",  "Print version",                                _cmd_version),
    SlashCommand("exit",     "Exit the TUI",                                 _cmd_exit),
]


COMMAND_REGISTRY: dict[str, SlashCommand] = {cmd.name: cmd for cmd in BUILTIN_COMMANDS}







# ── user-invocable skill 作为 slash 命令 ───────────────────────────────────
# /<skill> <自然语言> 强制触发某 user-invocable skill(绕过主 agent"自己先探"的不确定性):
# 渲染成 InjectResult(立即 invoke_skill + 任务),由 ist_app 直接 _submit。通用——任何
# frontmatter `user-invocable: true` 的 skill(ist-compile / ist-verify / device-verify…)
# 都能 /<name> 触发;fork 子流程(user-invocable: false)不暴露。


def _truthy(v: object) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "yes", "1", "on")


def _skill_frontmatter(skill_md) -> dict:
    """读 SKILL.md 的 `---` frontmatter dict;失败返回 {}。"""
    try:
        import yaml
        raw = skill_md.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    return fm if isinstance(fm, dict) else {}


def _skills_dir():
    from pathlib import Path
    return Path(__file__).resolve().parents[1] / "skills"


def _resolve_user_invocable_skill(name: str) -> "str | None":
    """命令名(连字符/下划线互通)匹配某 user-invocable skill → 规范 name,否则 None。"""
    skills_dir = _skills_dir()
    seen: set[str] = set()
    for cand in (name, name.replace("-", "_"), name.replace("_", "-")):
        if cand in seen:
            continue
        seen.add(cand)
        skill_md = skills_dir / cand / "SKILL.md"
        if not skill_md.exists():
            continue
        fm = _skill_frontmatter(skill_md)
        if _truthy(fm.get("user-invocable")):
            return str(fm.get("name") or cand)
        return None  # 存在但非 user-invocable(fork 子流程)→ 不暴露
    return None


def _render_skill_prompt(skill_name: str, args: str) -> str:
    """把 /<skill> <args> 渲染成**强制触发**该 skill 的合成 prompt。"""
    task = (args or "").strip()
    base = (
        f"立即调用 invoke_skill(\"{skill_name}\") 加载并严格执行 **{skill_name}** 技能。"
        f"在加载技能之前,不要自己读取或解析任何文件、也不要自行拆解流程——一切按技能指令走。"
    )
    return f"{base}\n\n【任务】\n{task}" if task else base


_USER_SKILL_NAMES_CACHE: "list[str] | None" = None


def _user_invocable_skill_names() -> list[str]:
    """所有 user-invocable skill 的 name(供 slash 补全);懒扫描 + 缓存。"""
    global _USER_SKILL_NAMES_CACHE
    if _USER_SKILL_NAMES_CACHE is not None:
        return _USER_SKILL_NAMES_CACHE
    out: list[str] = []
    skills_dir = _skills_dir()
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            if not child.is_dir():
                continue
            md = child / "SKILL.md"
            if not md.exists():
                continue
            fm = _skill_frontmatter(md)
            if _truthy(fm.get("user-invocable")) and fm.get("name"):
                out.append(str(fm["name"]))
    _USER_SKILL_NAMES_CACHE = out
    return out


def _noop_handler(args: str, app: "IstApp") -> SlashCommandResult:  # 补全占位,实际走 dispatch fallback
    return InfoResult(text="")


def dispatch_slash_command(parsed: ParsedSlashCommand, app: "IstApp") -> SlashCommandResult:
    """Look up the command in the registry and run its handler.

    内置命令未命中时,再看是不是 user-invocable skill —— 是则强制触发该 skill。
    都不是 -> ErrorResult。
    """
    cmd = COMMAND_REGISTRY.get(parsed.command_name)
    if cmd is None:
        skill = _resolve_user_invocable_skill(parsed.command_name)
        if skill is not None:
            return InjectResult(prompt=_render_skill_prompt(skill, parsed.args))
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
    # user-invocable skill 也作为可补全的 slash 命令(/<skill> 强制触发该 skill)
    have = {c.name.lower() for c in matches}
    for sname in _user_invocable_skill_names():
        if sname.lower().startswith(prefix) and sname.lower() not in have:
            matches.append(SlashCommand(sname, f"强制运行 {sname} 技能", _noop_handler))
    return matches[:limit]
