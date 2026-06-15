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

import os
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

RULES (BLOCKING REQUIREMENT):
- When a skill matches the user's request, your response MUST invoke that skill via qa_invoke_skill BEFORE doing anything else about the task. Pass the user's raw question/request as the brief — the skill handles all file reading, document lookup, generation, and on-device steps internally.
- This applies at ANY point, not just the first tool_call: if you are about to read files / write scripts / call qa_exec / qa_bash / qa_emit_xlsx to do work that a listed skill covers, STOP and invoke the skill instead. Do NOT hand-roll what a skill already does.
- NEVER mention or describe a skill without actually calling qa_invoke_skill.
- Only skip a skill if the task genuinely falls outside every skill's description, or the user explicitly said not to use one.
</system-reminder>"""

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 渐进披露预算：
# - 单条 description 截断上限（字符）
# - 全局 listing 字符预算；溢出时把溢出的 skill 降级为 name-only（仅列名，不列描述）
# 均可经 env 覆盖。
_PER_SKILL_DESC_CAP = int(os.environ.get("IST_SKILL_DESC_CAP", "250"))
_LISTING_CHAR_BUDGET = int(os.environ.get("IST_SKILL_LISTING_BUDGET", "8000"))

# listing 渲染优先级（数字小=排前=预算紧张时最后被降级）。核心/高频 skill 排前。
# 未列入的默认 50，按名字字母序稳定排列。
_LISTING_PRIORITY = {
    "ist_compile_batch": 0,
    "ist_compile_orchestrate": 0,
    "test-list-review": 0,
    "config-answer": 0,
}


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
    # when_to_use 保留换行：下游 _format_skill_list 靠 split("\n") 找 "Trigger keywords:" 行首
    # 提取触发词。若在此用空格 join 压成一行，行首锚点丢失，触发词永远提取不到。
    when_to_use = "\n".join(when_to_use_lines).strip()

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
    """决定一个 skill 是否进**主 agent 的 listing**（模型每轮看到的清单）。

    只过滤 disable-model-invocation: true（完全不可见，qa_invoke_skill 也拒）。

    **user-invocable: false 仍进 listing**：这类是 fork 子流程（ist_compile_draft/run/grade、
    review-verification），由 inline 编排 skill（ist_compile_orchestrate / test-list-review）的
    body 引导**主 agent** 经 qa_invoke_skill 派发——派发者就是主 agent 本身，故必须对模型可见，
    否则主 agent 按 body 指示调用时找不到。它们只是不进 TUI `/skill` 用户菜单（user-invocable
    语义由菜单层控制）。防"主 agent 越过编排器直调子流程"靠编排 skill 的 body 纪律 + prompt
    引导，不靠从 listing 隐藏（隐藏会连合法派发路径一起切断）。
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

def _truncate(text: str, cap: int) -> str:
    """按字符截断，超出加省略号。"""
    text = (text or "").strip()
    if cap > 0 and len(text) > cap:
        return text[: max(0, cap - 1)].rstrip() + "…"
    return text


def _format_skill_list(skills_metadata: list[dict[str, str]]) -> str:
    """渲染常驻 skill listing（L1 元数据层）。

    渐进披露三道闸：
    1. 每条 description 截断到 _PER_SKILL_DESC_CAP 字符
    2. when_to_use（trigger/SKIP 细则）**不进常驻 listing**——触发该 skill 后
       才从 SKILL.md body 读到，避免每轮重发长触发条件
    3. 全局 _LISTING_CHAR_BUDGET 字符预算：按顺序累加，超预算的 skill 降级为
       name-only（仅列名，不列描述），保证 listing 不随 skill 数量线性膨胀
    """
    if not skills_metadata:
        return "(no skills loaded)"
    # 预算闸按顺序累加，靠后的 skill 先被降级为 name-only。给高频/核心 skill 排前，
    # 保证 8000 预算被未来 skill 暴增挤占时它们的描述最后才丢（当前 skill 数少不触发降级，
    # 此排序是面向未来的兜底，不改变当前输出）。未列入的按字母序保持稳定。
    skills_metadata = sorted(
        skills_metadata, key=lambda s: (_LISTING_PRIORITY.get(s.get("name", ""), 50), s.get("name", ""))
    )
    lines: list[str] = []
    used = 0
    for skill in skills_metadata:
        name = skill.get("name", "")
        description = _truncate(skill.get("description", ""), _PER_SKILL_DESC_CAP)
        when = skill.get("when_to_use", "")
        # 从 when_to_use 提取触发词行（"Trigger keywords:" 或 "Trigger phrases:"，
        # 大小写无关、中英冒号均可）。依赖 _parse_skill_frontmatter 保留了 \n（行首锚点）。
        triggers = ""
        if when:
            for line in when.split("\n"):
                stripped = line.strip()
                if re.match(r"trigger\s+(keywords|phrases)\s*[:：]", stripped, re.I):
                    triggers = re.split(r"[:：]", stripped, 1)[1].strip()
                    break
        if description and triggers:
            entry = f"- **{name}**: {description} [触发: {triggers}]"
        elif description:
            entry = f"- **{name}**: {description}"
        else:
            entry = f"- **{name}**"
        # 全局预算闸：超预算则降级为 name-only
        if _LISTING_CHAR_BUDGET > 0 and used + len(entry) > _LISTING_CHAR_BUDGET:
            entry = f"- **{name}**"
        used += len(entry)
        lines.append(entry)
    return "\n".join(lines)


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

