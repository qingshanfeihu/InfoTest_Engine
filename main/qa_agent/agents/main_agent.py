"""Main QA agent using the phase-one generic read-only tool surface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from main.qa_agent.agents._llm import build_agent_chat_model
from main.qa_agent.agents._prompt import build_system_prompt
from main.qa_agent.tools.deepagent import (
    qa_deepagent_glob,
    qa_deepagent_grep,
    qa_deepagent_ls,
    qa_deepagent_read_file,
)
from main.qa_agent.tools.deepagent.exec_tools import qa_bash, qa_exec
from main.qa_agent.tools.knowledge.web_bug_search import web_bug_search

logger = logging.getLogger(__name__)


def _default_generic_tools() -> list[Any]:
    return [
        qa_deepagent_ls,
        qa_deepagent_glob,
        qa_deepagent_grep,
        qa_deepagent_read_file,
        # Stage 4: cluade.md 验收依赖的统计/解析能力（受白名单沙箱保护）
        qa_exec,
        qa_bash,
        # web_bug_search：按 ticket id 查 bug/story 详情（本地优先，远端 Playwright 兜底）
        web_bug_search,
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
        backend_kwarg["backend"] = FilesystemBackend(
            root_dir=str(project_root),
            virtual_mode=True,
            max_file_size_mb=10,
        )
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
    except ImportError as exc:
        logger.info("deepagents filesystem/exclusion middleware 不可用，使用显式 qa_deepagent_* 工具: %s", exc)

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        **backend_kwarg,
        **kwargs,
    )


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
