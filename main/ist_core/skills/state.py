"""Skill visibility control via skillOverrides settings.

提供 skillOverrides 四态机制，
配置文件位置使用 IST-Core 风格——和 skills 模块同目录。

四种状态：
- "on" (default):           name + description 都进 listing，模型/用户都可调
- "name-only":              仅 name 进 listing（节省 budget），模型可调
- "user-invocable-only":    模型不可见（不进 listing 也不可调），仅用户可调
- "off":                    完全隐藏（用户菜单 + 模型 listing 都不可见）

skillOverrides 优先级高于 SKILL.md frontmatter。

文件路径：main/ist_core/skills/.skill_overrides.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

SkillState = Literal["on", "name-only", "user-invocable-only", "off"]
_VALID_STATES: tuple[str, ...] = ("on", "name-only", "user-invocable-only", "off")


_SETTINGS_PATH = Path(__file__).resolve().parent / ".skill_overrides.json"


def _load_settings() -> dict[str, Any]:
    """读 .skill_overrides.json，返回完整 dict。文件不存在返回 {}。"""
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug(".skill_overrides.json 解析失败: %s", exc)
        return {}


def _save_settings(settings: dict[str, Any]) -> None:
    """原子写回 .skill_overrides.json。"""
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("settings.local.json 写入失败: %s", exc)


def get_skill_state(name: str) -> SkillState:
    """返回 skill 的当前状态。未配置时默认 'on'。"""
    settings = _load_settings()
    overrides = settings.get("skillOverrides") or {}
    state = overrides.get(name, "on")
    if state not in _VALID_STATES:
        logger.debug("invalid skillOverride state %r for %s, fallback 'on'", state, name)
        return "on"
    return state  # type: ignore[return-value]


def set_skill_state(name: str, state: SkillState) -> None:
    """写入 skill 状态到 .skill_overrides.json。"""
    if state not in _VALID_STATES:
        raise ValueError(f"invalid state {state!r}; must be one of {_VALID_STATES}")
    settings = _load_settings()
    overrides = dict(settings.get("skillOverrides") or {})
    if state == "on":
        
        overrides.pop(name, None)
    else:
        overrides[name] = state
    if overrides:
        settings["skillOverrides"] = overrides
    else:
        settings.pop("skillOverrides", None)
    _save_settings(settings)


def cycle_skill_state(name: str) -> SkillState:
    """循环到下一个状态（用于 TUI Space 键交互），返回新状态。"""
    cur = get_skill_state(name)
    idx = _VALID_STATES.index(cur)
    nxt = _VALID_STATES[(idx + 1) % len(_VALID_STATES)]
    set_skill_state(name, nxt)  # type: ignore[arg-type]
    return nxt  # type: ignore[return-value]







def is_listed_to_model(name: str) -> bool:
    """skill 是否进入模型 listing（模型能看到 name）。

    True: state in ('on', 'name-only')
    """
    return get_skill_state(name) in ("on", "name-only")


def is_listed_with_description(name: str) -> bool:
    """skill 是否带 description 进 listing（False = 仅 name）。"""
    return get_skill_state(name) == "on"


def is_user_invocable(name: str) -> bool:
    """skill 是否在用户 / 菜单中显示。

    True: state in ('on', 'name-only', 'user-invocable-only')
    """
    return get_skill_state(name) != "off"


def is_callable_by_model(name: str) -> bool:
    """模型是否可通过 invoke_skill 调用此 skill。

    True: state in ('on', 'name-only')
    （'user-invocable-only' 模型不可见也不可调，'off' 完全禁用）
    """
    return get_skill_state(name) in ("on", "name-only")







def get_all_overrides() -> dict[str, SkillState]:
    """返回所有显式配置的 skill state 映射（不含默认 'on' 的 skill）。"""
    settings = _load_settings()
    overrides = settings.get("skillOverrides") or {}
    return {k: v for k, v in overrides.items() if v in _VALID_STATES}


__all__ = [
    "SkillState",
    "get_skill_state",
    "set_skill_state",
    "cycle_skill_state",
    "is_listed_to_model",
    "is_listed_with_description",
    "is_user_invocable",
    "is_callable_by_model",
    "get_all_overrides",
]
