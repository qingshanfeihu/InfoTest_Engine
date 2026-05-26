"""qa_invoke_skill: Skill 相关 tool.

qa_invoke_skill — 仿 Claude Code 的 Skill tool 调用机制

NOTE: qa_sanity_check 已废弃（Step 7）。verifier subagent 自发 grep 探索
字面问题，不再依赖机械扫描脚本。历史脚本保留在
``skills/test-case-review/scripts/sanity_check.py`` 供参考但不再注册为 tool。
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"
_PROJECT_ROOT = Path(__file__).resolve().parents[4]


@tool
def qa_invoke_skill(skill: str) -> str:
    """Execute a skill within the main conversation.

    Available skills are listed in the `## Skills System` section of the system
    prompt. Each skill has a name and a description; pass the exact skill name
    here (e.g. `test-case-review`, no leading slash, no path).

    BLOCKING REQUIREMENT: When a skill's description matches the user's
    request, you MUST invoke this tool BEFORE generating any other response
    or calling any other tool about the task. Skipping this tool will cause
    critical instructions, reading orders, and quality checks to be missed.

    Skill 调用流程：
    1. 用户发起请求
    2. 检查系统提示中 `## Skills System` 列出的 skills
    3. 如果某个 skill 的 description 匹配 → 立即调用 qa_invoke_skill(skill="<name>")
    4. 本工具返回 SKILL.md 全文（含详细指令、阅读链、reference 文件路径）
    5. 严格按 SKILL.md 指令执行后续工作

    Args:
        skill: skill 的精确名称（必须与 ## Skills System 列表中的 name 完全一致）

    Returns:
        SKILL.md 的完整 markdown 文本（含 frontmatter 后的 body）。

    Raises:
        FileNotFoundError: skill 不存在或路径不合法。
    """
    if not skill or "/" in skill or ".." in skill or skill.startswith("-"):
        return f"ERROR: invalid skill name {skill!r}; expected a single skill identifier (e.g. 'test-case-review')"

    skill_path = _SKILLS_DIR / skill / "SKILL.md"
    if not skill_path.exists():
        available = sorted(p.name for p in _SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
        return (
            f"ERROR: skill {skill!r} not found at {skill_path}.\n"
            f"Available skills: {', '.join(available) if available else '(none)'}"
        )

    content = skill_path.read_text(encoding="utf-8")
    header = (
        f"# Skill loaded: {skill}\n"
        f"# Path: main/qa_agent/skills/{skill}/SKILL.md\n"
        f"# Reference files (read on demand with qa_deepagent_read_file):\n"
    )
    ref_dir = _SKILLS_DIR / skill / "reference"
    if ref_dir.exists():
        for ref_file in sorted(ref_dir.iterdir()):
            if ref_file.is_file():
                rel = f"main/qa_agent/skills/{skill}/reference/{ref_file.name}"
                header += f"#   - {rel}\n"
    return header + "\n" + content
