"""IST-Core 顶层 LangGraph StateGraph 装配。

节点：

    START -> normalize_input -> qa_node -> finalize -> END

v1 主线只有一个 ``qa_node``，把用户 query 透传给通用 main_agent 处理；
``main_agent`` 内部由 deepagents 框架做 ReAct 循环 + 工具调用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from main.qa_agent.state import QaAgentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent 延迟构造（避免 import graph 即触发 deepagents 初始化）
# ---------------------------------------------------------------------------

_MAIN_AGENT: Any | None = None

def _get_main_agent():
    global _MAIN_AGENT
    if _MAIN_AGENT is None:
        from main.qa_agent.agents.main_agent import build_main_agent

        _MAIN_AGENT = build_main_agent()
    return _MAIN_AGENT

# ---------------------------------------------------------------------------
# Node: normalize_input
# ---------------------------------------------------------------------------

def normalize_input(state: QaAgentState) -> dict[str, Any]:
    """把用户输入归一化到 ``state.normalized_input``。

    支持两种入参形态：
      - ``user_input`` 是字符串 -> 直接当 query
      - ``user_input`` 是 dict（结构化 review JSON 等）-> 透传
    """
    user_input = state.get("user_input")
    if isinstance(user_input, str):
        return {"normalized_input": {"query": user_input.strip(), "intent": "knowledge"}}
    if isinstance(user_input, dict):
        return {"normalized_input": user_input}
    return {"normalized_input": {"query": "", "intent": "knowledge"}}

def _extract_latest_user_text(messages: list[Any]) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            c = getattr(msg, "content", "")
            return c if isinstance(c, str) else str(c)
    return ""

# ---------------------------------------------------------------------------
# 进度 handler：把 main_agent 内部 LLM / 工具调用转发到 EventBus
# ---------------------------------------------------------------------------

class _MainAgentProgressHandler(BaseCallbackHandler):
    """把 main_agent 的 LLM 输出 / 工具调用转发到全局 EventBus。

    LangChain ``agent.invoke()`` 是同步阻塞的——上层 ``astream_events``
    看不到内部 LLM token / tool_call 事件。这个 callback handler 直接调
    ``main.qa_agent.events.get_default_bus()`` 把进度事件 emit 出去，
    TUI sink 能即时消费。
    """

    def __init__(self) -> None:
        self._chat_idx = 0
        self._tool_idx = 0
        self._tool_name_stack: list[str] = []
        import time as _t

        self._t0 = _t.monotonic()

    def _emit_to_bus(self, kind: str, *, payload: dict[str, Any] | None = None,
                    tags: dict[str, Any] | None = None,
                    usage: dict[str, Any] | None = None) -> None:
        try:
            from main.qa_agent.events import get_default_bus

            bus = get_default_bus()
            bus.emit(kind, payload=payload, tags=tags, usage=usage)
        except Exception:  # noqa: BLE001
            pass

    def _subagent_tags(self, kwargs: dict, base_tags: dict | None = None) -> dict:
        """从 LangChain callback kwargs 抽 subagent 标识，合并到 base_tags.

        LangChain 默认把 callback 传播给子 chain（subagent）；通过
        ``metadata.lc_agent_name`` 区分主 / 子事件。

        - ``parent_subagent``: 子 agent 名（如 "review-verification"）
        - ``parent_tool_use_id``: 主 agent 调 task 工具时的 run_id，
          所有该 subagent 内部事件挂到这个 id 下，TUI 据此把子事件渲染到
          对应 SubAgentTaskMessage 容器内。
        """
        tags = dict(base_tags or {})
        meta = kwargs.get("metadata") or {}
        agent_name = meta.get("lc_agent_name") or ""
        # main_agent / 空字符串 = 主 agent；其他都是 subagent
        if agent_name and agent_name not in {"main_agent", ""}:
            tags["parent_subagent"] = agent_name
            if getattr(self, "_current_task_tool_use_id", ""):
                tags["parent_tool_use_id"] = self._current_task_tool_use_id
        return tags

    # --- LangChain callbacks --------------------------------------------------
    def on_chat_model_start(self, *args, **kwargs) -> None:  # noqa: D401, ANN002
        self._chat_idx += 1

    def on_llm_end(self, response, **kwargs) -> None:  # noqa: D401, ANN001
        """LangChain 唯一的 LLM 结束 callback（chat + completion 都走这条）.

        参考 langchain_core/callbacks/base.py:90 + 156-157：
        ``on_chat_model_start`` 和 ``on_llm_end`` 是 chat model 调用的标准回调对——
        不存在 ``on_chat_model_end``。
        """
        text = ""
        thinking_text = ""
        has_tool_calls = False
        usage: dict[str, int] = {}
        try:
            gens = getattr(response, "generations", None) or []
            if gens and gens[0]:
                first = gens[0][0]
                msg = getattr(first, "message", None)
                if msg is not None:
                    c = getattr(msg, "content", "")
                    # Anthropic 兼容端点常返回 list[dict] 多 content block
                    # （含 ``{"type":"text","text":...}`` 和 ``{"type":"tool_use",...}``），
                    # 只抽 text 块拼成纯文本，避免把 Python repr 当成解释行渲染。
                    # ``{"type":"thinking","thinking":...}`` 块单独 emit thinking 事件。
                    if isinstance(c, str):
                        text = c
                    elif isinstance(c, list):
                        parts = []
                        thinking_parts = []
                        for block in c:
                            if isinstance(block, dict):
                                btype = block.get("type")
                                if btype == "text":
                                    t = block.get("text") or ""
                                    if t:
                                        parts.append(t)
                                elif btype == "thinking":
                                    th = block.get("thinking") or ""
                                    if th:
                                        thinking_parts.append(th)
                            elif isinstance(block, str):
                                parts.append(block)
                        text = "\n".join(parts)
                        thinking_text = "\n".join(thinking_parts)
                    else:
                        text = str(c)
                    tc = getattr(msg, "tool_calls", None) or []
                    add = getattr(msg, "additional_kwargs", None) or {}
                    has_tool_calls = bool(tc) or bool(add.get("tool_calls"))
                    # OpenAI 兼容端点（DashScope qwen3.6 + enable_thinking=True）
                    # 把 reasoning 放在 additional_kwargs['reasoning_content']，
                    # 不在 content list 里。这里兜底一次。
                    if not thinking_text:
                        rc = add.get("reasoning_content") or add.get("reasoning")
                        if isinstance(rc, str) and rc.strip():
                            thinking_text = rc
                    # LangChain BaseMessage.usage_metadata: {input_tokens, output_tokens, total_tokens}
                    um = getattr(msg, "usage_metadata", None) or {}
                    if isinstance(um, dict):
                        usage = um
                if not text:
                    text = getattr(first, "text", "") or ""
            # 兜底：response.llm_output["token_usage"]
            if not usage:
                llm_out = getattr(response, "llm_output", None) or {}
                tu = llm_out.get("token_usage") or llm_out.get("usage") or {}
                if isinstance(tu, dict):
                    usage = tu
        except Exception:  # noqa: BLE001
            text = ""
        text = (text or "").strip()
        # 计算 subagent tag —— LLM 事件也按 subagent 区分
        sub_tags = self._subagent_tags(kwargs)

        # 1. usage 单独发（让 TUI footer 实时累加 token）
        if usage:
            self._emit_to_bus(
                "llm_end",
                payload={"name": "usage_only"},
                tags=sub_tags or None,
                usage=usage,
            )
        # 2. thinking block 单独发（TUI 渲染成 ∴ Thinking）
        if thinking_text:
            self._emit_to_bus(
                "info",
                payload={"name": "thinking_block", "thinking": thinking_text},
                tags=sub_tags or None,
            )
        # 3. 中间步骤的 LLM 解释（带 tool_calls 的 thought）
        # - 有文本 + 有 tool_calls：打印 AI 的解释段
        # - 无文本 + 有 tool_calls：打印 ``[Calling tools]`` 占位
        # - 有文本 + 无 tool_calls：最终答案——也 emit 给 TUI 实时显示
        #   （仿业界 agent 框架流式渲染：每段 LLM text 都直接显示给用户，
        #    不留到 finalize，让用户看到主 agent 自己的收尾段）
        if has_tool_calls:
            content = text if text else "[Calling tools]"
            self._emit_to_bus(
                "llm_end",
                payload={"name": "thought", "content": content},
                tags=sub_tags or None,
            )
        elif text:
            # 无 tool_calls 的最终答案段：emit 一条 final_thought 给 TUI 渲染
            # （TUI sink 当 AIFinalMessage 显示）。注意：finalize 节点仍可能
            # 用 subagent ToolMessage 替代 state.final_answer（评审兜底场景）。
            self._emit_to_bus(
                "llm_end",
                payload={"name": "final_thought", "content": text},
                tags=sub_tags or None,
            )

    def on_tool_start(self, serialized, input_str, **kwargs) -> None:  # noqa: D401, ANN001
        self._tool_idx += 1
        name = ""
        if isinstance(serialized, dict):
            name = serialized.get("name", "") or ""
        self._tool_name_stack.append(name)
        cap = 4000 if name in ("write_todos", "task") else 400

        # 主 agent 调 task 工具时记录 run_id 当 parent_tool_use_id；
        # 之后 subagent 内部事件挂到这个 id 下（仿业界 createProgressMessage 设计）。
        meta = kwargs.get("metadata") or {}
        agent_name = meta.get("lc_agent_name") or ""
        is_main_agent_event = not agent_name or agent_name == "main_agent"
        if name == "task" and is_main_agent_event:
            run_id = kwargs.get("run_id")
            self._current_task_tool_use_id = str(run_id) if run_id else ""

        tags = self._subagent_tags(kwargs, base_tags={"name": name})
        self._emit_to_bus(
            "tool_call",
            payload={"name": name, "input": {"raw": (input_str or "")[:cap]}},
            tags=tags,
        )

    def _pop_tool_name(self) -> str:
        return self._tool_name_stack.pop() if self._tool_name_stack else ""

    def on_tool_end(self, output, **kwargs) -> None:  # noqa: D401, ANN001
        from langgraph.types import Command  # noqa: PLC0415

        tool_name = self._pop_tool_name()
        if isinstance(output, Command):
            # write_todos 等工具返回 Command 做 state update，不是用户可见输出
            update = getattr(output, "update", None) or {}
            if "todos" in update:
                todos = update["todos"]
                summary = "; ".join(
                    f"[{t.get('status', '?')}] {t.get('content', '')[:60]}"
                    for t in (todos if isinstance(todos, list) else [])
                )
                text = f"plan updated: {summary}" if summary else "plan updated"
            else:
                text = "state updated"
        elif hasattr(output, "content"):
            try:
                inner = output.content
                text = inner if isinstance(inner, str) else str(inner)
            except Exception:
                text = str(output)
        else:
            text = output if isinstance(output, str) else str(output)

        # 主 agent 的 task 工具收尾后清空 task tool_use_id
        meta = kwargs.get("metadata") or {}
        agent_name = meta.get("lc_agent_name") or ""
        is_main_agent_event = not agent_name or agent_name == "main_agent"
        if tool_name == "task" and is_main_agent_event:
            self._current_task_tool_use_id = ""

        tags = self._subagent_tags(kwargs, base_tags={"name": tool_name})
        self._emit_to_bus(
            "tool_result",
            payload={"name": tool_name, "output": text},
            tags=tags,
        )

    def on_tool_error(self, error, **kwargs) -> None:  # noqa: D401, ANN001
        tool_name = self._pop_tool_name()
        self._emit_to_bus(
            "tool_result",
            payload={"name": tool_name, "output": f"error: {error}"},
            tags={"name": tool_name},
        )

# ---------------------------------------------------------------------------
# Node: qa_node
# ---------------------------------------------------------------------------

def qa_node(state: QaAgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """把完整对话历史传给 main_agent，支持多轮交互。

    策略：
    - 优先使用 ``state.messages`` 完整历史
    - 回退：``normalized_input.query`` 单轮包装
    - ``config`` 透传给 main_agent
    - 注入 ``_MainAgentProgressHandler`` 把每条 AI 输出 / 工具调用转发到 EventBus
    """
    agent = _get_main_agent()
    incoming_messages = state.get("messages") or []
    intent = (state.get("normalized_input") or {}).get("intent") or "knowledge"

    if incoming_messages:
        agent_input = {"messages": list(incoming_messages)}
    else:
        query = (state.get("normalized_input") or {}).get("query") or ""
        base_messages: list[Any] = [HumanMessage(content=f"[intent={intent}] {query}")]
        agent_input = {"messages": base_messages}

    handler = _MainAgentProgressHandler()

    if config is None:
        merged_config: RunnableConfig = {
            "callbacks": [handler],
            "recursion_limit": 100,
        }
    else:
        existing_cbs = list(config.get("callbacks") or [])
        merged_config = {
            **config,
            "callbacks": existing_cbs + [handler],
            # 评审场景：主 agent ReAct 循环 + verifier subagent 内部循环
            # 都需要充足 recursion 预算。默认 25 不够；100 经验值。
            "recursion_limit": max(config.get("recursion_limit") or 0, 100),
        }

    try:
        result = agent.invoke(agent_input, config=merged_config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("qa_node 调用 MainAgent 失败: %s", exc)
        return {"final_answer": f"[error] {exc}", "messages": [AIMessage(content=f"错误: {exc}")]}

    messages = result.get("messages") or []
    answer = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            answer = msg.content if isinstance(msg.content, str) else str(msg.content)
            break
    return {"messages": messages, "final_answer": answer}

# ---------------------------------------------------------------------------
# Node: finalize
# ---------------------------------------------------------------------------

def finalize(state: QaAgentState) -> dict[str, Any]:
    """Finalize 节点：写最终 final_answer.

    Skill 场景兜底：当 review_gate 等"硬闸节点"判定 passed 且 messages 中
    存在 verifier subagent 的 ToolMessage（含 VERDICT/LEVEL）时，**强制把
    它当 final_answer 主体**。原因：runner CLI 模式只输出 final_answer，
    用户看不到中间 ToolMessage 内容；某些 LLM 在长上下文下会把 9000+ 字
    subagent 报告压成 15 字总结，工程层必须兜底保证用户能看到完整报告。

    通用场景下（gate_status != passed 或没有 verifier ToolMessage）：保持原
    行为，透传 state.final_answer。

    避免重复：如果主 agent 自己已经复述了完整 verifier 内容（含 VERDICT/LEVEL
    且长度 ≥ 1500 字），认为主 agent 已经把 verifier 输出转述给用户，不再
    前置 verifier ToolMessage，只用主 agent 的 final_answer。这样 TUI 上
    用户看到 [TUI 渲染 verifier ToolMessage] + [TUI 渲染主 agent 收尾文本] +
    [final_answer] 三段不会重复——final_answer 直接就是主 agent 的版本。
    """
    answer = state.get("final_answer") or ""

    if state.get("gate_status") == "passed":
        verifier_content = _extract_subagent_report(
            state.get("messages") or [],
            subagent_type="review-verification",
        )
        if verifier_content:
            # 检测主 agent 是否已自己复述了完整 verifier 内容
            agent_already_relayed = (
                len(answer) >= 1500
                and "VERDICT" in answer
                and "LEVEL" in answer
            )
            if agent_already_relayed:
                # 主 agent 自己写了完整复述——不要再前置 verifier，避免双倍内容
                pass
            else:
                # 主 agent 没复述（如 "评审完成" 15 字总结）——工程兜底前置
                # verifier 完整内容
                prefix = ""
                if answer and len(answer) > 50 and "VERDICT" not in answer:
                    prefix = answer + "\n\n---\n\n"
                answer = prefix + verifier_content

    return {"final_answer": answer}

def _extract_subagent_report(msgs: list, *, subagent_type: str) -> str:
    """从 messages 倒序找指定 subagent 的 ToolMessage 内容.

    在 deepagents task 工具语义下，主 agent 调 ``task(subagent_type=X)``
    后 subagent 返回的 ToolMessage 含 ``tool_call_id`` 关联到对应 AIMessage
    的 tool_calls。本函数倒序找到最近一次该 subagent 类型的调用，返回
    ToolMessage content（要求含 ``VERDICT:`` + ``LEVEL:`` 行）。

    用途：finalize 节点把判定类 subagent（评审 verifier 等）报告自动复制为
    final_answer，绕开主 agent 总结环节。
    """
    from langchain_core.messages import AIMessage, ToolMessage

    # 1. 找最近一次 task(subagent_type=X) 的 tool_call_id
    target_tool_use_id = None
    for m in reversed(msgs):
        if not isinstance(m, AIMessage):
            continue
        for tc in (m.tool_calls or []):
            name = tc.get("name") if isinstance(tc, dict) else None
            args = tc.get("args") if isinstance(tc, dict) else None
            if name != "task" or not isinstance(args, dict):
                continue
            if args.get("subagent_type") != subagent_type:
                continue
            target_tool_use_id = tc.get("id")
            break
        if target_tool_use_id:
            break

    if not target_tool_use_id:
        return ""

    # 2. 找对应的 ToolMessage
    for m in reversed(msgs):
        if not isinstance(m, ToolMessage):
            continue
        if getattr(m, "tool_call_id", None) != target_tool_use_id:
            continue
        if getattr(m, "status", None) == "error":
            return ""
        content = m.content if isinstance(m.content, str) else str(m.content)
        if "VERDICT:" in content and "LEVEL:" in content:
            return content
    return ""

# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def _open_async_sqlite_checkpointer(sqlite_path: str) -> Any:
    """``astream_events`` / ``ainvoke`` 需要 AsyncSqliteSaver（非同步 SqliteSaver）。

    必须在 event loop 未运行时调用（graph build 阶段），
    后续 ainvoke/astream_events 会复用同一 loop。
    """
    import aiosqlite  # type: ignore[import-not-found]
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore[import-not-found]

    async def _open() -> Any:
        conn = await aiosqlite.connect(sqlite_path)
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.commit()
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        return saver

    loop = asyncio.get_event_loop()
    if loop.is_running():
        raise RuntimeError(
            "无法在已运行的 event loop 内同步构造 AsyncSqliteSaver；"
            "请在 event loop 启动前 build graph。"
        )
    return loop.run_until_complete(_open())

def _open_sync_sqlite_checkpointer(sqlite_path: str) -> Any:
    """同步 ``SqliteSaver``，用于 ``graph.invoke()`` 同步调用路径。

    LangGraph 契约：从主线程同步调 AsyncSqliteSaver 会因事件循环 +
    asyncio.Lock 互锁僵持（aio.py:164 抛 InvalidStateError）。同步路径必须用
    threading.Lock + 同步 sqlite3.Connection 的 SqliteSaver。
    """
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-not-found]

    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver

def _make_checkpointer(mode: str = "async"):
    """三级降级：Postgres -> SQLite -> InMemorySaver。

    ``mode``:
      - ``"async"``（默认，TUI / langgraph dev / astream_events）：SQLite 用 AsyncSqliteSaver
      - ``"sync"``（runner.py print 模式 / graph.invoke）：SQLite 用同步 SqliteSaver

    Postgres 与 InMemory 的实现 sync/async 通用，无需分支。
    """
    postgres_dsn = (
        os.environ.get("IST_POSTGRES_CHECKPOINT_DSN")
        or os.environ.get("LANGGRAPH_POSTGRES_DSN")
        or ""
    ).strip()
    if postgres_dsn:
        try:
            import psycopg  # type: ignore[import-not-found]
            from psycopg.rows import dict_row  # type: ignore[import-not-found]
            from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore[import-not-found]

            if postgres_dsn.startswith("postgresql+psycopg://"):
                postgres_dsn = "postgresql://" + postgres_dsn.split("://", 1)[1]
            conn = psycopg.connect(
                postgres_dsn,
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
            )
            saver = PostgresSaver(conn)
            if (os.environ.get("IST_POSTGRES_CHECKPOINT_SETUP") or "1").lower() not in {"0", "false", "no"}:
                saver.setup()
            return saver
        except Exception as exc:  # noqa: BLE001
            logger.warning("PostgresSaver 初始化失败，降级本地 checkpointer: %s", exc)

    sqlite_path = (os.environ.get("IST_SQLITE_PATH") or "").strip()
    if sqlite_path:
        try:
            if mode == "sync":
                return _open_sync_sqlite_checkpointer(sqlite_path)
            return _open_async_sqlite_checkpointer(sqlite_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQLite checkpointer (%s) 初始化失败，降级 InMemorySaver: %s", mode, exc)

    from langgraph.checkpoint.memory import InMemorySaver

    return InMemorySaver()

def build_qa_agent_graph(
    *,
    checkpointer: Any | bool = True,
    store: Any | bool = True,
    checkpointer_mode: str = "async",
):
    """构造 IST-Core v1 主图。

    ``checkpointer_mode`` 决定默认 checkpointer 工厂走 sync 还是 async 路径
    （仅在 ``checkpointer is True`` 时生效）。runner.py print 模式必须传
    ``"sync"``，TUI / langgraph dev / streaming 走默认 ``"async"``。
    """
    from main.qa_agent.nodes.review_gate import review_gate

    g = StateGraph(QaAgentState)
    g.add_node("normalize_input", normalize_input)
    g.add_node("qa_node", qa_node)
    g.add_node("review_gate", review_gate)
    g.add_node("finalize", finalize)

    g.add_edge(START, "normalize_input")
    g.add_edge("normalize_input", "qa_node")
    # qa_node → review_gate 检查评审硬闸
    g.add_edge("qa_node", "review_gate")
    # review_gate 三态：
    # - passed: 走 finalize（评审场景验证通过 / 非评审场景透传）
    # - pending: 重路由回 qa_node 让主 agent 重试调 verifier
    # - failed: 重试上限到，写错误 final_answer 后走 finalize
    g.add_conditional_edges(
        "review_gate",
        lambda s: s.get("gate_status", "passed"),
        {
            "passed": "finalize",
            "pending": "qa_node",
            "failed": "finalize",
        },
    )
    g.add_edge("finalize", END)

    compile_kwargs: dict[str, Any] = {}
    if checkpointer is True:
        compile_kwargs["checkpointer"] = _make_checkpointer(mode=checkpointer_mode)
    elif checkpointer not in (False, None):
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)
