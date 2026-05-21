"""Per-turn skill listing injection middleware（仿 Claude Code 机制）。

为什么需要这个 middleware：
- deepagents 0.5.9 的 SkillsMiddleware 把 skill listing 拼到 system prompt 末尾，
  对 Claude 模型有效，但 qwen3.6-plus 等非 Anthropic 模型对 system prompt 末尾
  的指令跟随性弱，会忽略 "BLOCKING REQUIREMENT" 等强约束。
- Claude Code 二进制（cc 2.1.141）的实际做法：把 skill listing 作为
  user-role meta 消息（system-reminder 标签包裹）每轮注入，离当前 reasoning
  context 最近，所有模型对此的注意力权重都极高。

实现要点：
- 必须用 wrap_model_call hook 改 ModelRequest.messages（**不持久化到 state**）
- 不能用 before_model 返回 {"messages": [...]}，那会通过 add_messages reducer
  把 reminder 持久化为对话历史，被 agent 当作"用户新输入"导致死循环
- CC 二进制里的 `isMeta: true` 标记在 LangChain 没对等概念，所以不能写进 state
- **不能依赖 SkillsMiddleware 的 state['skills_metadata']**：那个字段被
  PrivateStateAttr 标注，仅 SkillsMiddleware 自己可见，其他 middleware 读不到
- 自己扫描 skills 目录加载 metadata，与 SkillsMiddleware 解耦
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage


_SKILL_LISTING_TEMPLATE = """<system-reminder>
The following skills are available for use with the qa_invoke_skill tool:

{skill_list}

When a skill's description matches the user's current request, this is a BLOCKING REQUIREMENT: invoke the relevant qa_invoke_skill tool BEFORE generating any other response or calling any other tool about the task.

NEVER mention a skill without actually calling qa_invoke_skill.
Do not invoke a skill that is already running.
</system-reminder>"""


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_skill_frontmatter(skill_md_path: Path) -> dict[str, str] | None:
    """简易 SKILL.md frontmatter 解析（只取 name + description，不依赖 yaml 包）"""
    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None
    fm = m.group(1)
    name = ""
    desc_lines: list[str] = []
    in_desc = False
    for line in fm.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
            in_desc = False
        elif line.startswith("description:"):
            desc_lines = [line.split(":", 1)[1].strip()]
            in_desc = True
        elif in_desc and (line.startswith("  ") or line.startswith("\t") or line == ""):
            desc_lines.append(line.strip())
        elif ":" in line and not line.startswith(" "):
            in_desc = False
    description = " ".join(s for s in desc_lines if s).strip()
    if not name or not description:
        return None
    return {"name": name, "description": description}


def _load_skills_from_dir(skills_dir: Path) -> list[dict[str, str]]:
    """扫 skills_dir/*/SKILL.md 返回 metadata 列表"""
    out: list[dict[str, str]] = []
    if not skills_dir.exists() or not skills_dir.is_dir():
        return out
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        meta = _parse_skill_frontmatter(skill_md)
        if meta:
            out.append(meta)
    return out


def _format_skill_list(skills_metadata: list[dict[str, str]]) -> str:
    if not skills_metadata:
        return "(no skills loaded)"
    lines = []
    for skill in skills_metadata:
        name = skill.get("name", "")
        description = skill.get("description", "")
        lines.append(f"- **{name}**: {description}")
    return "\n".join(lines)


def _has_recent_reminder(messages: list) -> bool:
    """检查是否最近 4 条消息内已有 skill reminder（避免重复堆积）"""
    recent = messages[-4:] if len(messages) > 4 else messages
    for msg in recent:
        content = getattr(msg, "content", "") or ""
        if isinstance(content, str) and "<system-reminder>" in content and "qa_invoke_skill tool" in content:
            return True
    return False


class PerTurnSkillReminderMiddleware(AgentMiddleware):
    """Inject skill listing as a HumanMessage in each ModelRequest.

    Mirrors Claude Code's `skill_listing` attachment mechanism: instead of
    relying on the model to recall the system prompt skill listing, send a
    fresh per-turn reminder as a user-role message. Critical: only modify
    the per-call ModelRequest.messages list, **never** write back to state
    (that would cause the reminder to be treated as user input and trigger
    infinite loops).
    """

    def __init__(self, skills_dir: str | Path) -> None:
        self._skills_dir = Path(skills_dir)
        self._cached_metadata: list[dict[str, str]] | None = None

    def _get_metadata(self) -> list[dict[str, str]]:
        if self._cached_metadata is None:
            self._cached_metadata = _load_skills_from_dir(self._skills_dir)
        return self._cached_metadata

    def _build_messages_with_reminder(
        self, request: ModelRequest
    ) -> list:
        """返回插入了 reminder 的 messages 副本（不修改原列表）"""
        skills_metadata = self._get_metadata()
        if not skills_metadata:
            return list(request.messages)

        if _has_recent_reminder(request.messages):
            return list(request.messages)

        skill_list = _format_skill_list(skills_metadata)
        reminder = HumanMessage(
            content=_SKILL_LISTING_TEMPLATE.format(skill_list=skill_list)
        )

        # 在最后一条 user message 之前插入 reminder（让它紧贴当前 turn 的用户输入）
        new_msgs = list(request.messages)
        insert_at = len(new_msgs)
        for i in range(len(new_msgs) - 1, -1, -1):
            if isinstance(new_msgs[i], HumanMessage):
                insert_at = i
                break
        new_msgs.insert(insert_at, reminder)
        return new_msgs

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        new_messages = self._build_messages_with_reminder(request)
        modified = request.override(messages=new_messages)
        return handler(modified)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        new_messages = self._build_messages_with_reminder(request)
        modified = request.override(messages=new_messages)
        return await handler(modified)


__all__ = ["PerTurnSkillReminderMiddleware"]


