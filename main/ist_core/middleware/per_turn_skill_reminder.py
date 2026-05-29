"""Per-turn skill listing injection middleware.

为什么需要这个 middleware：
- deepagents 0.5.9 的 SkillsMiddleware 把 skill listing 拼到 system prompt 末尾，
  对大部分对话模型效果良好，但某些模型对 system prompt 末尾的指令跟随性较弱，
  可能会忽略 "BLOCKING REQUIREMENT" 等强约束。
- 采用的做法：把 skill listing 作为 user/human-role meta 消息（system-reminder 标签包裹）每轮注入，
  离当前 reasoning context 最近，所有模型对此的注意力权重都极高。

实现要点：
- 必须用 wrap_model_call hook 改 ModelRequest.messages（**不持久化到 state**）
- 不能用 before_model 返回 {"messages": [...]}，那会通过 add_messages reducer
  把 reminder 持久化为对话历史，被 agent 当作"用户新输入"导致死循环
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
    """简易 SKILL.md frontmatter 解析（提取 name / description / when_to_use，
    不依赖 yaml 包）。
    字段；listing 暴露 ``when_to_use`` 让 LLM 看到 trigger / SKIP 条件，避免
    通用 QA 误调 skill。
    """
    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None
    fm = m.group(1)

    
    name = ""
    description_lines: list[str] = []
    when_to_use_lines: list[str] = []
    cur_field: str | None = None

    for line in fm.splitlines():
        
        if line and not line.startswith((" ", "\t", "-")) and ":" in line:
            key, _, after = line.partition(":")
            key = key.strip()
            value = after.strip()
            if key == "name":
                name = value
                cur_field = None
            elif key == "description":
                description_lines = [value] if value else []
                cur_field = "description" if not value else None
            elif key == "when_to_use":
                when_to_use_lines = [value] if value and value != "|" else []
                cur_field = "when_to_use" if (not value or value == "|") else None
            else:
                cur_field = None
        elif cur_field == "description" and (line.startswith((" ", "\t")) or line == ""):
            description_lines.append(line.strip())
        elif cur_field == "when_to_use" and (line.startswith((" ", "\t")) or line == ""):
            when_to_use_lines.append(line.strip())

    description = " ".join(s for s in description_lines if s).strip()
    when_to_use = " ".join(s for s in when_to_use_lines if s).strip()

    context = "inline"
    user_invocable = "true"
    disable_model_invocation = "false"
    for line in fm.splitlines():
        if line and not line.startswith((" ", "\t", "-")) and ":" in line:
            key, _, after = line.partition(":")
            key = key.strip().lower()
            value = after.strip().lower()
            if key == "context":
                context = value or "inline"
            elif key == "user-invocable":
                user_invocable = value or "true"
            elif key == "disable-model-invocation":
                disable_model_invocation = value or "false"

    if not name or not description:
        return None
    return {
        "name": name,
        "description": description,
        "when_to_use": when_to_use,
        "context": context,
        "user-invocable": user_invocable,
        "disable-model-invocation": disable_model_invocation,
    }


def _skill_eligible_for_listing(meta: dict[str, str]) -> bool:
    """处理 user-invocable / disable-model-invocation 语义：

    - user-invocable: false → 仅用户菜单不显示，**模型 listing 仍可见**
      "仅本智能体可调用此 skill" — 用于 background knowledge / sub-skill
    - disable-model-invocation: true → 模型 listing 完全不可见

    注意：listing 过滤只看 disable-model-invocation；
    user-invocable 由 TUI `/skill` 命令的用户菜单层控制。
    """
    disable_invoke = (meta.get("disable-model-invocation") or "false").strip().lower()
    if disable_invoke in {"true", "yes", "1", "on"}:
        return False
    return True


def _load_skills_from_dir(skills_dir: Path) -> list[dict[str, str]]:
    """扫 skills_dir/*/SKILL.md，仅返回可经 qa_invoke_skill 调用的 inline skill."""
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
        if meta and _skill_eligible_for_listing(meta):
            out.append(meta)
    return out

def _format_skill_list(skills_metadata: list[dict[str, str]]) -> str:
    if not skills_metadata:
        return "(no skills loaded)"
    lines = []
    for skill in skills_metadata:
        name = skill.get("name", "")
        description = skill.get("description", "")
        when_to_use = skill.get("when_to_use", "")
        lines.append(f"- **{name}**: {description}")
        if when_to_use:
            
            
            
            lines.append(f"  _When to use_: {when_to_use}")
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

    Instead of relying on the model to recall the system prompt skill listing,
    send a fresh per-turn reminder as a user-role message. 
    Critical: only modify the per-call ModelRequest.messages list, **never** write 
    back to state (that would cause the reminder to be treated as user input and 
    trigger infinite loops).
    """

    def __init__(self, skills_dir: str | Path) -> None:
        self._skills_dir = Path(skills_dir)
        self._cached_metadata: list[dict[str, str]] | None = None

    def _get_metadata(self) -> list[dict[str, str]]:
        if self._cached_metadata is None:
            self._cached_metadata = _load_skills_from_dir(self._skills_dir)
        from main.ist_core.skills.state import (
            is_listed_to_model,
            is_listed_with_description,
        )
        out: list[dict[str, str]] = []
        for s in self._cached_metadata:
            name = s["name"]
            if not is_listed_to_model(name):
                continue
            
            if not is_listed_with_description(name):
                out.append({
                    "name": name,
                    "description": "",
                    "when_to_use": "",
                })
            else:
                out.append(s)
        return out

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
        new_messages = _inject_output_style(new_messages)
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


def _inject_output_style(messages: list) -> list:
    """注入 Output Style prompt。

    仅当用户通过 /style 切换到非 default 风格时才注入。
    注入位置：messages 开头（system-reminder 格式）。
    """
    try:
        from main.ist_core.output_styles import get_active_style_prompt
        style_prompt = get_active_style_prompt()
        if not style_prompt:
            return messages
        from langchain_core.messages import HumanMessage
        style_msg = HumanMessage(
            content=f"<system-reminder>\n{style_prompt}\n</system-reminder>"
        )
        return [style_msg] + messages
    except Exception:  # noqa: BLE001
        return messages

