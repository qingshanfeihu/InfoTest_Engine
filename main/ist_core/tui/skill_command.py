"""Slash command: /skill — 用户侧三命令：on / off / all。

TUI 常用：
  /skill all              列出全部 skill 及状态（含 off）
  /skill on <name>        恢复默认（模型可见可触发）
  /skill off <name>       关闭（模型与用户菜单均隐藏）

底层仍支持四态（``skillOverrides``）：on / name-only / user-invocable-only / off。
高级用法保留 ``/skill set``、``/skill cycle``（不在 help 中展示）。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from main.ist_core.skills.state import (
    cycle_skill_state,
    get_skill_state,
    set_skill_state,
    SkillState,
)

if TYPE_CHECKING:
    from main.ist_core.tui.slash_commands import SlashCommandResult

_SKILLS_DIR = Path(__file__).resolve().parents[1] / "skills"

_VALID_STATES: tuple[str, ...] = ("on", "name-only", "user-invocable-only", "off")


def _scan_all_skills() -> list[dict[str, str]]:
    """扫描 skills 目录，返回所有 skill 的 name + context."""
    from main.ist_core.middleware.per_turn_skill_reminder import (
        _parse_skill_frontmatter,
    )

    out: list[dict[str, str]] = []
    if not _SKILLS_DIR.is_dir():
        return out
    for child in sorted(_SKILLS_DIR.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        meta = _parse_skill_frontmatter(skill_md)
        if meta and meta.get("name"):
            out.append(meta)
    return out


def _skill_exists(name: str) -> dict[str, str] | None:
    """检查 skill 是否存在，返回 meta 或 None."""
    from main.ist_core.middleware.per_turn_skill_reminder import (
        _parse_skill_frontmatter,
    )

    skill_md = _SKILLS_DIR / name / "SKILL.md"
    if not skill_md.exists():
        return None
    return _parse_skill_frontmatter(skill_md)


def cmd_skill(args: str, app: object) -> "SlashCommandResult":
    """Dispatch /skill sub-commands."""
    from main.ist_core.tui.slash_commands import ErrorResult

    parts = (args or "").strip().split(None, 2)
    sub = parts[0].lower() if parts else "all"

    if sub in ("all", "list", "ls"):
        return _cmd_list(show_all=True)
    if sub == "set":
        if len(parts) < 3:
            return ErrorResult(text="usage: /skill set <name> <on|name-only|user-invocable-only|off>")
        return _cmd_set(parts[1].strip(), parts[2].strip())
    if sub == "cycle":
        if len(parts) < 2:
            return ErrorResult(text="usage: /skill cycle <name>")
        return _cmd_cycle(parts[1].strip())
    if sub == "on":
        if len(parts) < 2:
            return ErrorResult(text="usage: /skill on <name>")
        return _cmd_set(parts[1].strip(), "on")
    if sub == "off":
        if len(parts) < 2:
            return ErrorResult(text="usage: /skill off <name>")
        return _cmd_set(parts[1].strip(), "off")
    
    if sub in ("enable",):
        if len(parts) < 2:
            return ErrorResult(text="usage: /skill on <name>")
        return _cmd_set(parts[1].strip(), "on")
    if sub in ("disable",):
        if len(parts) < 2:
            return ErrorResult(text="usage: /skill off <name>")
        return _cmd_set(parts[1].strip(), "off")
    if sub == "help":
        return _cmd_help()
    return ErrorResult(
        text=f"unknown /skill subcommand: {sub!r}. Use: /skill all | /skill on <name> | /skill off <name>"
    )


_STATE_MARKER = {
    "on": "✓",
    "name-only": "◐",
    "user-invocable-only": "○",
    "off": "✗",
}


def _cmd_list(*, show_all: bool = True) -> "SlashCommandResult":
    """列出 skill 及当前状态（默认含 off）。"""
    from main.ist_core.tui.slash_commands import TextResult

    skills = _scan_all_skills()
    if not skills:
        return TextResult(text="No skills found.")
    lines = ["Skills (state from .skill_overrides.json):"]
    for s in skills:
        name = s["name"]
        state = get_skill_state(name)
        marker = _STATE_MARKER.get(state, "?")
        lines.append(f"  {marker} {name}  [{state}]")
    return TextResult(text="\n".join(lines))


def _cmd_set(name: str, state: str) -> "SlashCommandResult":
    from main.ist_core.tui.slash_commands import ErrorResult, InfoResult

    if not name:
        return ErrorResult(text="usage: /skill set <name> <state>")
    if state not in _VALID_STATES:
        return ErrorResult(
            text=f"invalid state {state!r}; must be one of: {', '.join(_VALID_STATES)}"
        )
    meta = _skill_exists(name)
    if not meta:
        return ErrorResult(text=f"skill {name!r} not found")
    set_skill_state(name, state)  # type: ignore[arg-type]
    return InfoResult(text=f"skill {name!r} state set to {state!r}")


def _cmd_cycle(name: str) -> "SlashCommandResult":
    from main.ist_core.tui.slash_commands import ErrorResult, InfoResult

    if not name:
        return ErrorResult(text="usage: /skill cycle <name>")
    meta = _skill_exists(name)
    if not meta:
        return ErrorResult(text=f"skill {name!r} not found")
    new_state = cycle_skill_state(name)
    return InfoResult(text=f"skill {name!r} state → {new_state!r}")


def _cmd_help() -> "SlashCommandResult":
    from main.ist_core.tui.slash_commands import TextResult

    return TextResult(text=(
        "/skill              same as /skill all\n"
        "/skill all          list all skills and states\n"
        "/skill on <name>    enable (model + user can invoke)\n"
        "/skill off <name>   disable (hidden from both)\n"
        "\n"
        "Markers: ✓ on   ✗ off   ◐ name-only   ○ user-invocable-only"
    ))
