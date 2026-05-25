"""Main QA agent using the phase-one generic read-only tool surface."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from main.qa_agent.agents._llm import build_agent_chat_model
from main.qa_agent.agents._prompt import build_system_prompt
from main.qa_agent.tools.deepagent import (
    qa_deepagent_edit_file,
    qa_deepagent_glob,
    qa_deepagent_grep,
    qa_deepagent_ls,
    qa_deepagent_read_file,
    qa_deepagent_write_file,
)
from main.qa_agent.tools.deepagent.exec_tools import qa_bash, qa_exec
from main.qa_agent.tools.knowledge.web_bug_search import web_bug_search
from main.qa_agent.tools.knowledge.footprint_lookup import qa_footprint_lookup
from main.qa_agent.tools.skills import qa_invoke_skill, qa_sanity_check
from main.qa_agent.tools.ask_user import qa_ask_user

logger = logging.getLogger(__name__)

_SKILLS_DIR = str(Path(__file__).resolve().parents[1] / "skills")


def _default_generic_tools() -> list[Any]:
    return [
        qa_deepagent_ls,
        qa_deepagent_glob,
        qa_deepagent_grep,
        qa_deepagent_read_file,
        qa_deepagent_write_file,
        qa_deepagent_edit_file,
        # Stage 4: cluade.md 验收依赖的统计/解析能力（受白名单沙箱保护）
        qa_exec,
        qa_bash,
        # web_bug_search：按 ticket id 查 bug/story 详情（本地优先，远端 Playwright 兜底）
        web_bug_search,
        # qa_footprint_lookup：查询 footprint 知识树（评审/对话中获取已积累的 CLI 命令知识）
        qa_footprint_lookup,
        # qa_invoke_skill：仿 Claude Code 的 Skill tool 调用机制（BLOCKING REQUIREMENT
        # 措辞），让 LLM 把"读 SKILL.md"当 tool_call 触发，而非依赖自觉
        qa_invoke_skill,
        # qa_sanity_check：test-case-review skill 的字面自检 tool
        qa_sanity_check,
        # qa_ask_user：仿 Claude Code 的 AskUserQuestion——P0/P1 不确定时让用户决策
        qa_ask_user,
    ]


def build_main_agent(**kwargs: Any):
    """Build the phase-one main agent.

    By default this mounts only generic read-only exploration tools and a clean
    system prompt. Callers may pass a complete ``system_prompt`` or an
    ``extra_prompt``/``skill_prompt`` string explicitly; no repository skill is
    loaded implicitly on the main path.
    """
    model = kwargs.pop("model", None) or build_agent_chat_model()
    tools = kwargs.pop("tools", None) or _default_generic_tools()

    from main.qa_agent.tools._shared.metadata import attach_tool_metadata as _attach_md  # noqa: PLC0415

    tools = [_attach_md(t) for t in tools]

    user_system_prompt = kwargs.pop("system_prompt", None)
    extra_prompt = kwargs.pop("extra_prompt", None) or kwargs.pop("skill_prompt", None)
    if user_system_prompt is not None:
        system_prompt = str(user_system_prompt)
    else:
        tool_names = [getattr(t, "name", "") for t in tools]
        system_prompt = build_system_prompt(tools=tool_names)
    if extra_prompt:
        system_prompt = system_prompt + "\n\n# Additional Instructions\n" + str(extra_prompt).strip()

    try:
        from deepagents import create_deep_agent  # type: ignore[import-not-found]
    except ImportError as exc:
        logger.warning("deepagents 未安装，回退到 create_react_agent: %s", exc)
        return _build_fallback_react_agent(model=model, tools=tools, system_prompt=system_prompt)

    try:
        from deepagents.middleware import summarization_middleware  # type: ignore[import-not-found]

        middleware = kwargs.pop("middleware", None)
        if middleware is None:
            middleware = [summarization_middleware(max_tokens=28000)]
    except ImportError:
        middleware = kwargs.pop("middleware", None) or []

    backend_kwarg: dict[str, Any] = {}
    try:
        from deepagents.backends.filesystem import FilesystemBackend  # type: ignore[import-not-found]
        from deepagents.middleware._tool_exclusion import _ToolExclusionMiddleware  # type: ignore[import-not-found]

        project_root = Path(__file__).resolve().parents[3]
        backend = FilesystemBackend(
            root_dir=str(project_root),
            virtual_mode=True,
            max_file_size_mb=10,
        )
        backend_kwarg["backend"] = backend
        middleware = [
            *middleware,
            _ToolExclusionMiddleware(
                excluded={
                    "write_file",
                    "edit_file",
                    "execute",
                    "read_file",
                    "ls",
                    "glob",
                    "grep",
                }
            ),
        ]

        # SkillsMiddleware: 负责从磁盘加载 skill metadata 到 state（before_agent
        # 阶段一次性扫描），并在 system prompt 末尾注入 skill 列表（用于 Claude 类
        # 模型的 progressive disclosure）
        try:
            from deepagents.middleware.skills import SkillsMiddleware  # type: ignore[import-not-found]

            skills_mw = SkillsMiddleware(
                backend=backend,
                sources=[(_SKILLS_DIR, "IST-Core")],
            )
            middleware.append(skills_mw)
        except Exception as skills_exc:  # noqa: BLE001
            logger.info("SkillsMiddleware 不可用: %s", skills_exc)

        # PerTurnSkillReminderMiddleware: 仿 Claude Code skill_listing attachment
        # 机制——在每轮 before_model 把 skill listing 作为 user-role
        # <system-reminder> 注入对话，离当前 reasoning context 最近，让 qwen 等
        # 非 Anthropic 模型也能稳定遵守 BLOCKING REQUIREMENT
        try:
            from main.qa_agent.middleware.per_turn_skill_reminder import (
                PerTurnSkillReminderMiddleware,
            )

            middleware.append(PerTurnSkillReminderMiddleware(skills_dir=_SKILLS_DIR))
        except Exception as exc:  # noqa: BLE001
            logger.info("PerTurnSkillReminderMiddleware 不可用: %s", exc)

        # 三层记忆子系统（通用回调架构 + 评审场景适配）：
        # - MemoryInjectionMiddleware: 按 query_extractor / key_resolvers 检索注入
        # - MemoryWriteMiddleware: 按 finalizer 检测任务结束后蒸馏写入
        # - AGENTS.md 仍由 deepagents 内置 MemoryMiddleware 处理
        memory_extras: dict[str, Any] = {}
        try:
            from main.qa_agent import memory as _memory

            if _memory.is_enabled():
                _mem_backend_factory = _memory.make_memory_backend_factory()
                _mem_backend = _memory.build_memory_backend()
                backend_kwarg["backend"] = _mem_backend_factory
                _store = _memory.MemoryStore(_mem_backend, _memory.get_default_root())
                try:
                    _store.sync_agents_md_to_backend()
                except Exception as sync_exc:
                    logger.debug("sync AGENTS.md to backend 失败: %s", sync_exc)

                memory_extras["memory"] = _memory.get_memory_sources()
                memory_extras["store"] = _memory.get_default_store()

                # 评审场景：挂评审 adapter 回调
                _query_ext = None
                _key_res = None
                _finalizer = None
                try:
                    import importlib.util as _ilu
                    _adapter_path = os.path.join(
                        os.path.dirname(__file__), "..", "skills",
                        "test-case-review", "memory_adapter.py"
                    )
                    _spec = _ilu.spec_from_file_location("_review_adapter", _adapter_path)
                    if _spec and _spec.loader:
                        _mod = _ilu.module_from_spec(_spec)
                        _spec.loader.exec_module(_mod)
                        _query_ext = _mod.review_query_extractor
                        _key_res = _mod.review_key_resolvers
                        _finalizer = _mod.review_finalizer
                except Exception as adapter_exc:
                    logger.debug("评审 memory_adapter 加载失败: %s", adapter_exc)

                middleware.append(
                    _memory.MemoryInjectionMiddleware(
                        _store, _query_ext, _key_res, max_items=5
                    )
                )
                middleware.append(
                    _memory.MemoryWriteMiddleware(_store, _finalizer)
                )
                logger.info("memory subsystem 启用 (通用回调架构): root=%s",
                            _memory.get_default_root())
        except Exception as exc:  # noqa: BLE001
            logger.info("memory subsystem 不可用，沿用原 FilesystemBackend: %s", exc)

    except ImportError as exc:
        logger.info("deepagents filesystem/exclusion middleware 不可用，使用显式 qa_deepagent_* 工具: %s", exc)

    # Explore sub-agent（全局通用，跟 qa_ls/qa_grep 同级）
    # 任何 skill 都能通过 task(subagent_type="explore", description="...") 调用
    # 只传内置 FilesystemMiddleware 做不到的工具，避免重复
    subagents_kwarg: dict[str, Any] = {}
    try:
        from main.qa_agent.agents._llm import build_explore_model

        _EXPLORE_SYSTEM_PROMPT = (
            "你是一个只读检索代理。根据任务描述查找信息并返回结构化证据。\n"
            "只做检索，不做判断。返回：文件路径 + 行号 + 内容摘录。\n"
            "找不到就说\"未找到\"。"
        )

        # 只传 FilesystemMiddleware 不提供的工具
        # FilesystemMiddleware 自动提供：ls, glob, grep, read_file
        _explore_only_tools = [
            t for t in tools
            if getattr(t, "name", "") in ("web_bug_search", "qa_sanity_check")
        ]

        explore_subagent: dict[str, Any] = {
            "name": "explore",
            "description": (
                "通用只读检索代理。给它明确的搜索任务，返回结构化结果。"
                "适合：跨多文件搜索、读取文档片段、执行 sanity_check。"
                "不适合：评审判断、生成报告、简单单次查询（直接用 grep）。"
            ),
            "system_prompt": _EXPLORE_SYSTEM_PROMPT,
            "tools": _explore_only_tools,
            "model": build_explore_model(),
        }
        subagents_kwarg["subagents"] = [explore_subagent]
        logger.info("Explore sub-agent 已注册 (tools=%s)", [t.name for t in _explore_only_tools])
    except Exception as explore_exc:  # noqa: BLE001
        logger.info("Explore sub-agent 注册失败: %s", explore_exc)

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        interrupt_on=_resolve_interrupt_on(),
        **backend_kwarg,
        **memory_extras,
        **kwargs,
    )


def _resolve_interrupt_on() -> dict[str, Any] | None:
    """从 ``QA_AGENT_INTERRUPT_ON`` 解析 deepagents interrupt_on 配置。

    格式：逗号分隔工具名（全部走 ``True`` = 允许 approve/edit/reject/respond）。
    例：``QA_AGENT_INTERRUPT_ON=web_bug_search,qa_exec``。

    默认空——即所有工具自动批准。打开 interrupt_on 会让 graph 在指定工具调用
    前暂停，需要 TUI 实现 ``HumanInterrupt`` 决策的渲染（基础设施 bridge.py
    已有 resume_with 接 ``Command(resume=...)``）。
    """
    import os as _os

    raw = (_os.environ.get("QA_AGENT_INTERRUPT_ON") or "").strip()
    if not raw:
        return None
    tool_names = [t.strip() for t in raw.split(",") if t.strip()]
    if not tool_names:
        return None
    return {name: True for name in tool_names}


def _build_fallback_react_agent(*, model, tools, system_prompt: str):
    """Fallback for environments without deepagents."""
    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "既无 deepagents 也无 langgraph.prebuilt.create_react_agent，无法构造 IST-Core。"
        ) from exc

    return create_react_agent(
        model=model,
        tools=tools,
        prompt=system_prompt,
    )
