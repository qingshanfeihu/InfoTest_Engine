"""qa_invoke_skill / qa_sanity_check: Skill 相关 tool.

qa_invoke_skill — 仿 Claude Code 的 Skill tool 调用机制
qa_sanity_check — test-case-review skill 的字面自检脚本入口
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


@tool
def qa_sanity_check(target_file: str, bug_severity: str = "") -> str:
    """字面一致性自检——评审测试用例 markdown 时的 Step 6.5 强制工具。

    机械扫描 9 类问题：复制粘贴错位 / 离群标识符 / 字段空值率 / 重复描述与中文叠字 /
    Test Types 标记一致性 / 数值规律性 / Priority 分布 vs BUG 严重度匹配 / CLI help
    占比 / 章节冗余。**用脚本而非 LLM 眼扫**——眼扫无法精确数 277 行的频率分布。

    用法：在 `Step 6.5: 字面一致性自检` 阶段调用本 tool；输入是当前评审用例的
    markdown 路径（相对项目根目录或 knowledge/data/ 子目录皆可）。**强烈建议**
    把 Step 1 web_bug_search 拿到的 `metadata.severity` 作为 bug_severity 参数
    传入，启用 Priority 分布 vs BUG 严重度匹配检查。

    BLOCKING REQUIREMENT for test-case-review skill：评审报告 finalize 前必须
    跑一次本 tool 并把输出映射到 P0/P1 缺口（详见 SKILL.md Step 6.5 + reference/SELF_CHECK.md）。

    Args:
        target_file: 用例 markdown 文件路径。支持以下形式：
            - `knowledge/data/markdown/qa/<file>.md`（相对项目根）
            - `markdown/qa/<file>.md`（相对 knowledge/data/）
            - 绝对路径
        bug_severity: 当前 BUG 的严重度（来自 web_bug_search JSON 的
            ``metadata.severity``，如 "low" / "high"）。可选；不传则跳过
            priority_severity_alignment 检查。

    Returns:
        JSON 字符串，含 9 个 check 子段 + total_issues + total_rows。
        没异常时 `status: success`，否则 `status: issues_found`。
    """
    import sys

    # 路径解析：支持 3 种形式
    p = Path(target_file)
    candidates = [
        p,
        _PROJECT_ROOT / target_file,
        _PROJECT_ROOT / "knowledge" / "data" / target_file,
    ]
    resolved = None
    for c in candidates:
        if c.exists():
            resolved = c
            break
    if resolved is None:
        return json.dumps({
            "status": "error",
            "error": f"file not found: tried {[str(c) for c in candidates]}",
        }, indent=2, ensure_ascii=False)

    # import sanity_check 模块（不走 subprocess，直接 in-process 调）
    script_dir = _SKILLS_DIR / "test-case-review" / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        # 强制 reload 防 import 缓存（agent 多次调时拿到最新版本）
        import importlib
        import sanity_check as _mod  # type: ignore[import-not-found]
        importlib.reload(_mod)
        result = _mod.sanity_check(str(resolved), bug_severity=bug_severity or None)
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": f"sanity_check failed: {exc}"}
    finally:
        if str(script_dir) in sys.path:
            sys.path.remove(str(script_dir))

    return json.dumps(result, indent=2, ensure_ascii=False)
