"""Main QA agent using the phase-one generic read-only tool surface."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from main.ist_core.agents import _llm
from main.ist_core.agents._prompt import build_system_prompt
from main.ist_core.tools.deepagent import (
    fs_edit,
    fs_glob,
    fs_grep,
    fs_ls,
    fs_read,
    fs_write,
)
from main.ist_core.tools.deepagent.exec_tools import run_shell, run_python
from main.ist_core.tools.device import dev_rest, dev_ssh, dev_run_case, dev_probe, dev_init_device
from main.ist_core.tools.device import (
    dev_run_batch,
    dev_run_batch_digest,  # 整份上机 + 逐 case 四层归因 + 明细落 workspace，回精简摘要(不 offload)
    compile_attribute,
    submit_attribution,
    compile_emit,  # main-orchestrated 兜底单 case；worker 主路也用
    compile_user_decision,  # 欠定拍板落机读约束文件（锚取台账,不手抄）
    compile_engine_run,  # V6:一句话跑整条编译闭环(状态机图,断点续跑)
    compile_prep,  # main-orchestrated：解析脑图→manifest（含意图族聚类,族摊销路由）
    compile_skeleton,  # 族摊销:取族首成品的配置骨架,族内 brief 复用
    compile_writeback,  # 闭环:上机真PASS写回先例库(ρ_k增长)
    compile_emit_merged,  # main-orchestrated：合并各 case 单 xlsx 打包
    compile_fanout,  # main-orchestrated 真并发：N 个 case 一次 fan-out 独立 worker（reflow/批量重编，替代逐个 invoke_skill 串行）
    compile_grade_extract,  # main-orchestrated：合并前确定性自查 suspect（grade 之外的第二道闸）
    compile_pipeline,
    compile_runtime_slots,
    compile_runtime_fill,
)
from main.ist_core.tools.knowledge.kb_bug_search import kb_bug_search
from main.ist_core.tools.knowledge.footprint_lookup import kb_footprint
from main.ist_core.tools.knowledge.memory_search import kb_memory_search
from main.ist_core.tools.knowledge.footprint_writeback import compile_footprint_writeback
from main.ist_core.tools.skills import invoke_skill
from main.ist_core.tools.skills.agent_define import agent_define
from main.ist_core.tools.skills.file_server import qa_file_server
from main.ist_core.tools.ask_user import ask_user
from main.ist_core.tools.memory_tool import remember

logger = logging.getLogger(__name__)

_SKILLS_DIR = str(Path(__file__).resolve().parents[1] / "skills")

def _default_generic_tools() -> list[Any]:
    return [
        fs_ls,
        fs_glob,
        fs_grep,
        fs_read,
        fs_write,
        fs_edit,
        
        run_python,
        run_shell,
        dev_ssh,
        dev_rest,
        dev_run_case,
        dev_probe,
        dev_init_device,

        # 编译/上机：主 agent 只编排不手搓——编译机器（compile_prep/fanout/emit/
        # emit_merged/precedent/score）下放到 compile_pipeline 内部 + draft/grade fork，
        # 主 agent 仅调 compile_pipeline 一次；ist-verify 上机验证链用下面这组。
        dev_run_batch,
        dev_run_batch_digest,   # 整份上机 + 逐 case 归因 + 明细落 workspace，回精简分类摘要（推荐：大结果不 offload、可直接看分类）
        compile_attribute,   # 上机 fail 四层归因（单 case；digest 已内置批量归因）
        submit_attribution,  # 归因结论落盘 last_run.json（瞬态/冻结跨轮护栏与缺陷候选汇总靠它）
        compile_pipeline,  # 确定性编译流水线（保留当 fallback）
        compile_emit,  # main-orchestrated 兜底单 case
        compile_prep,  # main-orchestrated：解析脑图→manifest（含意图族聚类,族摊销路由）
        compile_user_decision,  # 欠定拍板落机读约束文件（锚取台账,不手抄）
        compile_engine_run,  # V6:一句话跑整条编译闭环(状态机图,断点续跑)
    compile_skeleton,  # 族摊销:取族首成品的配置骨架,族内 brief 复用
    compile_writeback,  # 闭环:上机真PASS写回先例库(ρ_k增长)
        compile_emit_merged,  # main-orchestrated：合并各 case 单 xlsx 打包
        compile_fanout,  # main-orchestrated 真并发：一次派发 N 个独立 worker（批量重编/reflow，替代逐个 invoke_skill 串行）
        compile_grade_extract,  # main-orchestrated：合并前确定性自查（grade 之外第二道闸，防放水）
        compile_runtime_slots,  # 列 <RUNTIME> 待回填槽位
        compile_runtime_fill,  # 上机真实值锁死回填（不反复改）
        compile_footprint_writeback,  # 真 PASS 的 G 段文法写回 footprint（verify 步7 自演化 ρ_k）

        kb_bug_search,

        kb_footprint,
        kb_memory_search,  # 长期记忆拉式检索(BM25;推注入之外的主动回忆通道)


        invoke_skill,
        agent_define,  # D:按 B2 骨架自主生成临时子 agent(现有 skill 不覆盖的子流程)

        qa_file_server,

        ask_user,
        remember,

    ]

def build_main_agent(**kwargs: Any):
    """Build the phase-one main agent.

    By default this mounts only generic read-only exploration tools and a clean
    system prompt. Callers may pass a complete ``system_prompt`` or an
    ``extra_prompt``/``skill_prompt`` string explicitly; no repository skill is
    loaded implicitly on the main path.
    """
    model = kwargs.pop("model", None) or _llm.build_agent_chat_model()
    tools = kwargs.pop("tools", None) or _default_generic_tools()

    from main.ist_core.tools._shared.metadata import attach_tool_metadata as _attach_md  # noqa: PLC0415

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

    # 上下文压缩由 create_deep_agent **无条件自动挂载**的 create_summarization_middleware
    # 提供(fraction 阈值 + 撤出历史落 runtime 的 /conversation_history/<thread>.md 可回读
    # + 溢出兜底)。勿再往 middleware 里传自建摘要实例——会与默认双摘要。
    # (2026-07-05 修正:旧代码 import summarization_middleware(max_tokens=28000),该名在
    # deepagents 0.5.9 不存在,静默走 except——28k 配置从未生效过,属死代码,已删。)
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

        
        
        
        # 不挂 deepagents 原生 SkillsMiddleware：它把 skill listing 拼到 system prompt 末尾，
        # 且教模型用 read_file 读 SKILL.md 全文——但本项目用 _ToolExclusionMiddleware 屏蔽了
        # read_file，那条指令是死指令，且与自研 PerTurnSkillReminderMiddleware（教用 invoke_skill）
        # 双路重复注入、互相矛盾。skill listing 由下面的 per_turn middleware 单路负责；
        # 本项目 skill 执行走 invoke_skill + loader.execute_fork_skill，不依赖 state['skills_metadata']。
        # 详见 docs/skill_progressive_disclosure_fix.md。


        
        
        
        try:
            from main.ist_core.middleware.per_turn_skill_reminder import (
                PerTurnSkillReminderMiddleware,
            )

            middleware.append(PerTurnSkillReminderMiddleware(skills_dir=_SKILLS_DIR))
        except Exception as exc:  # noqa: BLE001
            logger.info("PerTurnSkillReminderMiddleware 不可用: %s", exc)




        try:
            from main.ist_core.middleware.loop_guard import LoopGuardMiddleware

            middleware.append(LoopGuardMiddleware())
        except Exception as exc:  # noqa: BLE001
            logger.info("LoopGuardMiddleware 不可用: %s", exc)

        # 消息序列消毒:悬空 tool_calls(截断历史)补合成 ToolMessage——否则供应商
        # 每轮 400,会话死锁在「零响应」(2026-07-05 dongkl 重测实证)。IST_MSG_SANITIZE=0 关。
        try:
            from main.ist_core.middleware.message_sanitize import MessageSanitizeMiddleware

            middleware.append(MessageSanitizeMiddleware())
        except Exception as exc:  # noqa: BLE001
            logger.info("MessageSanitizeMiddleware 不可用: %s", exc)

        # 工具渐进披露(C2):按会话激活域过滤 request.tools,基础组常驻、
                # compile/device 组按激活给。默认开(对照轮验收后翻,IST_TOOL_GATING_ENABLED=0 关)。
        try:
            from main.ist_core.middleware.tool_gating import ToolGatingMiddleware

            middleware.append(ToolGatingMiddleware())
        except Exception as exc:  # noqa: BLE001
            logger.info("ToolGatingMiddleware 不可用: %s", exc)

        # 工具结果剪枝(MiMo-Code prune 移植):摘要之前的零成本上下文释放——
        # 旧工具结果保头 160 字符+剪枝标记,最近 2 轮/invoke_skill/ask_user 受保护。
        # IST_PRUNE_TOOL_OUTPUTS=0 关;预算 IST_PRUNE_PROTECT_CHARS(默认 15 万字符)。
        try:
            from main.ist_core.middleware.tool_result_prune import ToolResultPruneMiddleware

            middleware.append(ToolResultPruneMiddleware())
        except Exception as exc:  # noqa: BLE001
            logger.info("ToolResultPruneMiddleware 不可用: %s", exc)

        # 工具结果统一信封(坑1 修复):全部工具返回包 <tool_result name= status=>,
        # 数据面 XML 在横切层一次解决(单工具手改只覆盖了 3/36 且 fork 全漏)。
        # IST_TOOL_ENVELOPE=0 关。
        try:
            from main.ist_core.middleware.tool_envelope import ToolEnvelopeMiddleware

            middleware.append(ToolEnvelopeMiddleware())
        except Exception as exc:  # noqa: BLE001
            logger.info("ToolEnvelopeMiddleware 不可用: %s", exc)

        
        
        
        
        memory_extras: dict[str, Any] = {}
        try:
            from main.ist_core import memory as _memory

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

                
                _query_ext = None
                _key_res = None
                _finalizer = None
                try:
                    import importlib.util as _ilu
                    _adapter_path = os.path.join(
                        os.path.dirname(__file__), "..", "skills",
                        "test-list-review", "memory_adapter.py"
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
        logger.info("deepagents filesystem/exclusion middleware 不可用，使用显式 fs_* 工具: %s", exc)

    
    
    
    
    
    
    
    
    subagents_kwarg: dict[str, Any] = {}
    subagents_list: list[dict[str, Any]] = []

    
    try:
        from main.ist_core.agents._llm import build_explore_model

        _EXPLORE_SYSTEM_PROMPT = (
            "You are a read-only research agent for IST-Core. Given the "
            "task description, use available tools to find information and "
            "return structured evidence. Complete the task fully—don't "
            "gold-plate, but don't leave it half-done.\n"
            "\n"
            "When you complete the task, respond with a concise report "
            "covering what was found and any key findings — the caller "
            "(main agent) will relay this to the user, so it only needs "
            "the essentials.\n"
            "\n"
            "Output format:\n"
            "- Cite evidence with file paths + line numbers + brief excerpts.\n"
            "- Distinguish what you read from what you inferred.\n"
            "- If you didn't find something, say \"未找到\"——don't invent it.\n"
            "\n"
            "Boundaries:\n"
            "- Read-only: do not write/edit/delete files; do not run code.\n"
            "- Stay inside knowledge/data/ and workspace/ sandbox roots.\n"
            "- 中文用户场景：reply in Chinese (中文)."
        )

        
        
        _explore_only_tools = [
            t for t in tools
            if getattr(t, "name", "") in ("kb_bug_search",)
        ]

        explore_subagent: dict[str, Any] = {
            "name": "explore",
            "description": (
                "通用只读检索代理。给它明确的搜索任务，返回结构化结果。"
                "适合：跨多文件搜索、读取文档片段。"
                "不适合：评审判断、生成报告、简单单次查询（直接用 grep）。"
            ),
            "system_prompt": _EXPLORE_SYSTEM_PROMPT,
            "tools": _explore_only_tools,
            "model": build_explore_model(),
        }
        subagents_list.append(explore_subagent)
        logger.info("Explore sub-agent 已注册 (tools=%s)", [t.name for t in _explore_only_tools])
    except Exception as explore_exc:  # noqa: BLE001
        logger.warning("Explore sub-agent 注册失败: %s", explore_exc)

    
    

    if subagents_list:
        subagents_kwarg["subagents"] = subagents_list

    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        interrupt_on=_resolve_interrupt_on(),
        **backend_kwarg,
        **memory_extras,
        **subagents_kwarg,
        **kwargs,
    )

def _resolve_interrupt_on() -> dict[str, Any] | None:
    """从 ``IST_INTERRUPT_ON`` 解析 deepagents interrupt_on 配置。

    格式：逗号分隔工具名（全部走 ``True`` = 允许 approve/edit/reject/respond）。
    例：``IST_INTERRUPT_ON=kb_bug_search,run_python``。

    默认空——即所有工具自动批准。打开 interrupt_on 会让 graph 在指定工具调用
    前暂停，需要 TUI 实现 ``HumanInterrupt`` 决策的渲染（基础设施 bridge.py
    已有 resume_with 接 ``Command(resume=...)``）。
    """
    import os as _os

    raw = (_os.environ.get("IST_INTERRUPT_ON") or "").strip()
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
