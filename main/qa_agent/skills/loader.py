"""Skill Loader — 自动发现 SKILL.md 并构建 subagent。

仿 cc-haha 的 skill 发现机制：扫描 skills/ 目录下所有 SKILL.md，
解析 frontmatter，`context: fork` 的自动构建 CompiledSubAgent。

后续加新 fork skill 只需要加一个 SKILL.md 文件，不需要改 Python 代码。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent

_MODEL_MAP = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
}

_TOOL_REGISTRY: dict[str, Any] = {}


def _get_tool_registry() -> dict[str, Any]:
    """延迟加载工具注册表——包含所有可能被 fork skill 使用的工具。"""
    if not _TOOL_REGISTRY:
        from main.qa_agent.tools.deepagent import (
            qa_deepagent_grep,
            qa_deepagent_ls,
            qa_deepagent_read_file,
        )
        _TOOL_REGISTRY.update({
            "qa_deepagent_read_file": qa_deepagent_read_file,
            "qa_deepagent_grep": qa_deepagent_grep,
            "qa_deepagent_ls": qa_deepagent_ls,
        })
        try:
            from main.qa_agent.tools.deepagent import qa_bash, qa_exec
            _TOOL_REGISTRY["qa_bash"] = qa_bash
            _TOOL_REGISTRY["qa_exec"] = qa_exec
        except ImportError:
            pass
        try:
            from main.qa_agent.tools.web import web_bug_search
            _TOOL_REGISTRY["web_bug_search"] = web_bug_search
        except ImportError:
            pass
        try:
            from main.qa_agent.tools.footprint import qa_footprint_lookup
            _TOOL_REGISTRY["qa_footprint_lookup"] = qa_footprint_lookup
        except ImportError:
            pass
    return _TOOL_REGISTRY


def _parse_skill_md(path: Path) -> dict[str, Any] | None:
    """解析 SKILL.md，返回 {frontmatter, body} 或 None。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        logger.warning("Failed to parse frontmatter: %s", path)
        return None
    return {"frontmatter": fm, "body": parts[2].strip()}


def _resolve_tools(allowed_tools: list[str]) -> list[Any]:
    """从 frontmatter allowed-tools 列表解析实际工具对象。"""
    registry = _get_tool_registry()
    tools = []
    for name in allowed_tools:
        base_name = name.split("(")[0].strip()
        if base_name in registry:
            tools.append(registry[base_name])
    return tools


def _build_fork_subagent(name: str, fm: dict, body: str) -> dict[str, Any]:
    """从 SKILL.md frontmatter + body 构建 CompiledSubAgent dict。

    仿 cc-haha fork 执行流程：
    - skill body → system_prompt（行为约束）
    - 调用时 description → HumanMessage（具体任务）
    - allowed-tools → 工具白名单
    - model → 模型选择
    - recursion-limit → 从 frontmatter 读取（默认 200）
    - inherit-parent-prompt → 是否继承通用约束段（默认 false）
    """
    from langchain.agents import create_agent

    from main.qa_agent.agents._llm import build_agent_chat_model, qa_agent_tier_model

    model_name = fm.get("model", "opus")
    model_tier = _MODEL_MAP.get(model_name, model_name)
    model = build_agent_chat_model(model=qa_agent_tier_model(model_tier))

    allowed = fm.get("allowed-tools", [])
    if isinstance(allowed, str):
        allowed = [t.strip() for t in allowed.split(",")]
    tools = _resolve_tools(allowed)

    # 是否继承通用约束段（verifier 需要，其他 fork skill 可能不需要）
    if fm.get("inherit-parent-prompt", False):
        from main.qa_agent.agents._prompt import build_verifier_inherited_sections
        full_prompt = build_verifier_inherited_sections() + "\n\n---\n\n" + body
    else:
        full_prompt = body

    recursion_limit = int(fm.get("recursion-limit", 200))

    runnable = create_agent(
        model,
        system_prompt=full_prompt,
        tools=tools,
        name=name,
    ).with_config({"recursion_limit": recursion_limit})

    description = fm.get("description", f"Fork skill: {name}")

    return {
        "name": name,
        "description": description,
        "runnable": runnable,
    }


def load_fork_skills() -> list[dict[str, Any]]:
    """扫描 skills/ 目录，返回所有 context: fork 的 subagent 列表。

    后续加新 fork skill 只需要在 skills/ 下加一个目录 + SKILL.md，
    不需要改任何 Python 代码。
    """
    subagents = []
    for skill_dir in _SKILLS_DIR.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        parsed = _parse_skill_md(skill_file)
        if parsed is None:
            continue
        fm = parsed["frontmatter"]
        if fm.get("context") != "fork":
            continue
        name = fm.get("name", skill_dir.name)
        try:
            sa = _build_fork_subagent(name, fm, parsed["body"])
            subagents.append(sa)
            logger.info("Loaded fork skill: %s", name)
        except Exception:
            logger.exception("Failed to build fork skill: %s", name)
    return subagents
