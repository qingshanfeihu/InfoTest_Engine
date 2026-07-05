"""invoke_skill: Skill 相关 tool.

invoke_skill — 基于 Skill 文件的辅助工具调用机制

统一处理 inline 和 fork 两种 context：
- inline: 返回 SKILL.md 全文，注入主对话
- fork: 构建独立子代理执行，返回子代理最终输出文本

NOTE: qa_sanity_check 已废弃。verifier subagent 自发 grep 探索
字面问题，不再依赖机械扫描脚本。
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


@tool
def invoke_skill(skill: str, brief: str = "") -> str:
    """Execute a skill within the main conversation.

    Available skills are listed in the `## Skills System` section of the system
    prompt. Each skill has a name and a description; pass the exact skill name
    here (e.g. `test-case-review`, no leading slash, no path).

    BLOCKING REQUIREMENT: When a skill's description matches the user's
    request, you MUST invoke this tool BEFORE generating any other response
    or calling any other tool about the task.

    For fork skills (context: fork), pass the task brief as `brief`. The skill
    runs in an isolated sub-agent and returns its final output text.

    Args:
        skill: skill 的精确名称（必须与 Skills System 列表中的 name 完全一致）
        brief: 可选。对 fork skill 传入完整 brief（证据 + 任务描述）。

    Returns:
        inline skill: SKILL.md 的完整 markdown 文本。
        fork skill: 子代理执行后的最终输出文本。
    """
    if not skill or "/" in skill or ".." in skill or skill.startswith("-"):
        return f"ERROR: invalid skill name {skill!r}; expected a single skill identifier (e.g. 'test-case-review')"

    # 下划线/连字符互通(B1 别名兼容)+ 动态 agent skill(agent_define 产物)兜底
    from main.ist_core.skills.loader import resolve_skill_dirname, skill_md_path
    skill = resolve_skill_dirname(skill)

    skill_path = skill_md_path(skill)
    if not skill_path.exists():
        available = sorted(p.name for p in _SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
        return (
            f"ERROR: skill {skill!r} not found at {skill_path}.\n"
            f"Available skills: {', '.join(available) if available else '(none)'}"
        )

    from main.ist_core.skills.state import is_callable_by_model, get_skill_state

    if not is_callable_by_model(skill):
        return (
            f"ERROR: skill {skill!r} is not callable by model "
            f"(state: {get_skill_state(skill)}). "
            f"Use /skill to change state in .skill_overrides.json."
        )

    from main.ist_core.skills.loader import read_skill_frontmatter, skill_disable_model_invocation

    fm = read_skill_frontmatter(skill_path)

    
    if fm and skill_disable_model_invocation(fm):
        return (
            f"ERROR: skill {skill!r} has disable-model-invocation: true "
            f"in its SKILL.md and cannot be invoked by the model."
        )

    
    if fm and (fm.get("context") or "").strip().lower() == "fork":
        from main.ist_core.skills.loader import execute_fork_skill
        return execute_fork_skill(skill, brief)

    
    # 交互面 XML 分节(2026-07-05):skill 正文是「行为指令」,引用清单是「可按需取的
    # 资源指针」——标签区分角色,LLM 不再从混排文本里猜哪段是指令哪段是数据。
    # (机读面不受影响:本返回只有 LLM 消费。)
    content = skill_path.read_text(encoding="utf-8")
    refs = []
    ref_dir = _SKILLS_DIR / skill / "reference"
    if ref_dir.exists():
        for ref_file in sorted(ref_dir.iterdir()):
            if ref_file.is_file():
                refs.append(f"  - main/ist_core/skills/{skill}/reference/{ref_file.name}")
    parts = [
        f'<skill_content name="{skill}">',
        f"# Skill loaded: {skill}",
        "",
        content.rstrip(),
        "</skill_content>",
    ]
    if refs:
        parts += ["<skill_references note=\"按需 fs_read,不必全读\">", *refs, "</skill_references>"]
    return "\n".join(parts)
