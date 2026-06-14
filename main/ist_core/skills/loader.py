"""Skill + Subagent Loader.

Skills (skills/<name>/SKILL.md):
  - inline: 返回 body 注入主对话
  - fork: SKILL.md body 渲染后作为 HumanMessage 传给 agent: 引用的 subagent

Subagents (agents/<name>.md):
  - frontmatter: name, description, tools, model
  - markdown body = system_prompt（容器行为约束）

后续加新 fork skill 只需写 SKILL.md + 引用已注册的 subagent。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent
_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"

_MODEL_MAP = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
}

_TOOL_REGISTRY: dict[str, Any] = {}
_SUBAGENT_RUNNABLE_CACHE: dict[str, Any] = {}


def _get_tool_registry() -> dict[str, Any]:
    """延迟加载工具注册表——包含所有可能被 fork skill 使用的工具。"""
    if not _TOOL_REGISTRY:
        from main.ist_core.tools.deepagent import (
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
            from main.ist_core.tools.deepagent import qa_bash, qa_exec
            _TOOL_REGISTRY["qa_bash"] = qa_bash
            _TOOL_REGISTRY["qa_exec"] = qa_exec
        except ImportError:
            pass
        try:
            from main.ist_core.tools.device import qa_restapi, qa_ssh
            _TOOL_REGISTRY["qa_ssh"] = qa_ssh
            _TOOL_REGISTRY["qa_restapi"] = qa_restapi
        except ImportError:
            pass
        try:
            from main.ist_core.tools.knowledge.web_bug_search import web_bug_search
            _TOOL_REGISTRY["web_bug_search"] = web_bug_search
        except ImportError:
            pass
        try:
            from main.ist_core.tools.knowledge.footprint_lookup import (
                qa_footprint_lookup,
            )

            _TOOL_REGISTRY["qa_footprint_lookup"] = qa_footprint_lookup
        except ImportError:
            pass
        # 厨房角色 tools（cook-case/verify-case/review-case 子 agent 用）
        try:
            from main.ist_core.tools.device import (
                qa_emit_xlsx,
                qa_probe_show,
                qa_run_case,
            )
            _TOOL_REGISTRY["qa_emit_xlsx"] = qa_emit_xlsx
            _TOOL_REGISTRY["qa_run_case"] = qa_run_case
            _TOOL_REGISTRY["qa_probe_show"] = qa_probe_show
        except ImportError:
            pass
        try:
            from main.ist_core.tools.device.kitchen_tools import (
                qa_confidence_score,
                qa_lookup_pattern,
            )
            _TOOL_REGISTRY["qa_lookup_pattern"] = qa_lookup_pattern
            _TOOL_REGISTRY["qa_confidence_score"] = qa_confidence_score
        except ImportError:
            pass
    return _TOOL_REGISTRY


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """解析 frontmatter 布尔值（true/yes/1/on）。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "on"}
    return default


def skill_disable_model_invocation(fm: dict[str, Any]) -> bool:
    """``disable-model-invocation: true`` → 禁止主 agent 经 ``qa_invoke_skill`` 加载。"""
    return _coerce_bool(fm.get("disable-model-invocation"))


def read_skill_frontmatter(skill_md_path: Path) -> dict[str, Any] | None:
    """读取 SKILL.md frontmatter dict；解析失败返回 None。"""
    parsed = _parse_skill_md(skill_md_path)
    return parsed["frontmatter"] if parsed else None


def _parse_skill_md(path: Path) -> dict[str, Any] | None:
    """解析 SKILL.md / subagent .md，返回 {frontmatter, body} 或 None。"""
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


def _resolve_tools(allowed: list[str] | str) -> list[Any]:
    """从 frontmatter tools / allowed-tools 解析实际工具对象。

    支持两种格式：
    - 列表：["tool_a", "tool_b(path/*)"]
    - 字符串：逗号或空格分隔，"tool_a, tool_b" 或 "tool_a tool_b"
    """
    registry = _get_tool_registry()
    if isinstance(allowed, str):
        
        
        items = [t.strip() for t in allowed.replace(",", " ").split() if t.strip()]
    else:
        items = list(allowed or [])

    tools = []
    for name in items:
        base_name = name.split("(")[0].strip()
        if base_name in registry:
            tools.append(registry[base_name])
    return tools







def load_subagent(name: str) -> dict[str, Any] | None:
    """从 main/ist_core/agents/<name>.md 加载 subagent 定义。

    其结构设计设计：
    - frontmatter: name, description, tools, model（可选）
    - markdown body = system_prompt

    IST-Core 扩展字段：
    - inherit-parent-prompt: bool — 是否在 body 前 prepend 主 agent 的反偷懒约束块
      （Read-Only / Evidence Discipline / Reading-vs-Verification / Faithful Reporting）

    Returns:
        {name, description, system_prompt, tools_spec, model} 或 None（不存在/解析失败）
    """
    md_path = _AGENTS_DIR / f"{name}.md"
    if not md_path.exists():
        return None

    parsed = _parse_skill_md(md_path)
    if parsed is None:
        return None

    fm = parsed["frontmatter"]
    body = parsed["body"]

    
    if _coerce_bool(fm.get("inherit-parent-prompt"), default=False):
        try:
            from main.ist_core.agents._prompt import build_verifier_inherited_sections
            body = build_verifier_inherited_sections() + "\n\n---\n\n" + body
        except Exception:  # noqa: BLE001
            logger.exception("Failed to prepend verifier inherited sections for %s", name)

    return {
        "name": fm.get("name", name),
        "description": fm.get("description", ""),
        "system_prompt": body,
        "tools_spec": fm.get("tools") or fm.get("allowed-tools") or [],
        "model": fm.get("model", "opus"),
    }


def get_subagent_runnable(name: str) -> Any | None:
    """构建并缓存 subagent 的 LangChain runnable。

    缓存策略：按 name 缓存。如需刷新（如热重载 .md 文件），调 clear_subagent_cache()。
    """
    if name in _SUBAGENT_RUNNABLE_CACHE:
        return _SUBAGENT_RUNNABLE_CACHE[name]

    spec = load_subagent(name)
    if spec is None:
        return None

    try:
        from langchain.agents import create_agent

        from main.ist_core.agents._llm import build_agent_chat_model, ist_core_tier_model

        model_name = spec["model"]
        model_tier = _MODEL_MAP.get(model_name, model_name)
        model = build_agent_chat_model(model=ist_core_tier_model(model_tier))

        tools = _resolve_tools(spec["tools_spec"])

        runnable = create_agent(
            model,
            system_prompt=spec["system_prompt"],
            tools=tools,
            name=spec["name"],
        ).with_config({"recursion_limit": 200})

        _SUBAGENT_RUNNABLE_CACHE[spec["name"]] = runnable
        return runnable
    except Exception:
        logger.exception("Failed to build subagent runnable for %s", name)
        return None


def clear_subagent_cache() -> None:
    """清缓存（测试 / 热重载用）。"""
    _SUBAGENT_RUNNABLE_CACHE.clear()


def list_subagents() -> list[dict[str, str]]:
    """列出 agents/ 目录下所有 subagent 定义文件。"""
    out = []
    if not _AGENTS_DIR.exists():
        return out
    for md_file in sorted(_AGENTS_DIR.glob("*.md")):
        spec = load_subagent(md_file.stem)
        if spec:
            out.append({"name": spec["name"], "description": spec["description"]})
    return out







def execute_fork_skill(skill_name: str, brief: str = "") -> str:
    """执行 fork skill 的定义逻辑。

    流程：
    1. 读 SKILL.md frontmatter，确认 context: fork
    2. 读 agent: 字段，从 agents/ 加载对应 subagent 定义
    3. 渲染 SKILL.md body：替换 $ARGUMENTS 为 brief 内容
    4. 把渲染后的 body 作为 HumanMessage 传给 subagent
       （subagent 的 system_prompt 来自 .md 文件 body，不是 SKILL.md body）
    5. 返回 subagent 最终 AIMessage text

    关键：subagent 的 system_prompt 来自 agents/<agent>.md，SKILL.md body 是任务。
    """
    skill_file = _SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_file.exists():
        return f"ERROR: fork skill {skill_name!r} not found."

    parsed = _parse_skill_md(skill_file)
    if parsed is None:
        return f"ERROR: failed to parse {skill_name}/SKILL.md."

    fm = parsed["frontmatter"]
    if fm.get("context") != "fork":
        return f"ERROR: skill {skill_name!r} is not a fork skill."

    agent_name = (fm.get("agent") or "").strip()
    if not agent_name:
        return (
            f"ERROR: fork skill {skill_name!r} missing required 'agent:' field. "
            f"Fork skills must specify which subagent type "
            f"to use as execution container."
        )

    runnable = get_subagent_runnable(agent_name)
    if runnable is None:
        return (
            f"ERROR: fork skill {skill_name!r} references unknown subagent "
            f"{agent_name!r}. Check main/ist_core/agents/{agent_name}.md."
        )

    rendered_body = _render_skill_body(parsed["body"], brief)

    from langchain_core.messages import HumanMessage

    try:
        result = runnable.invoke({"messages": [HumanMessage(content=rendered_body)]})
    except Exception as exc:
        logger.exception("Fork skill %s execution failed", skill_name)
        return f"ERROR: fork skill {skill_name!r} execution failed: {exc}"

    messages = result.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "content") and getattr(msg, "type", "") == "ai":
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                text_parts = [
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                if text_parts:
                    return "\n".join(text_parts)

    return "ERROR: fork skill returned no text output."


def _render_skill_body(body: str, brief: str) -> str:
    """SKILL.md body 中的 $ARGUMENTS 占位符替换为 brief 内容。

    Fork skill 的 body 用 $ARGUMENTS 引用调用者传入的参数。
    如果 body 不含 $ARGUMENTS，则在末尾追加 brief（兼容性兜底）。
    """
    if "$ARGUMENTS" in body or "${ARGUMENTS}" in body:
        return body.replace("${ARGUMENTS}", brief).replace("$ARGUMENTS", brief)
    if brief:
        return body.rstrip() + "\n\n## Brief from caller\n\n" + brief
    return body


__all__ = [
    "read_skill_frontmatter",
    "skill_disable_model_invocation",
    "load_subagent",
    "get_subagent_runnable",
    "clear_subagent_cache",
    "list_subagents",
    "execute_fork_skill",
]
