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
import re
import uuid
from typing import Any

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from main.ist_core.state import IstCoreState

logger = logging.getLogger(__name__)





_MAIN_AGENT: Any | None = None

def _get_main_agent():
    global _MAIN_AGENT
    if _MAIN_AGENT is None:
        from main.ist_core.agents.main_agent import build_main_agent

        _MAIN_AGENT = build_main_agent()
    return _MAIN_AGENT





def normalize_input(state: IstCoreState) -> dict[str, Any]:
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





class _MainAgentProgressHandler(BaseCallbackHandler):
    """把 main_agent 的 LLM 输出 / 工具调用转发到全局 EventBus。

    LangChain ``agent.invoke()`` 是同步阻塞的——上层 ``astream_events``
    看不到内部 LLM token / tool_call 事件。这个 callback handler 直接调
    ``main.ist_core.events.get_default_bus()`` 把进度事件 emit 出去，
    TUI sink 能即时消费。
    """

    def __init__(self) -> None:
        self._chat_idx = 0
        self._tool_idx = 0
        self._tool_name_stack: list[str] = []
        self._seen_tool_run_ids: set[str] = set()
        import time as _t

        self._t0 = _t.monotonic()

    def _emit_to_bus(self, kind: str, *, payload: dict[str, Any] | None = None,
                    tags: dict[str, Any] | None = None,
                    usage: dict[str, Any] | None = None) -> None:
        try:
            from main.ist_core.events import get_default_bus

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
        
        if agent_name and agent_name not in {"main_agent", ""}:
            tags["parent_subagent"] = agent_name
            if getattr(self, "_current_task_tool_use_id", ""):
                tags["parent_tool_use_id"] = self._current_task_tool_use_id
        return tags

    
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
                    
                    
                    
                    if not thinking_text:
                        rc = add.get("reasoning_content") or add.get("reasoning")
                        if isinstance(rc, str) and rc.strip():
                            thinking_text = rc
                    
                    um = getattr(msg, "usage_metadata", None) or {}
                    if isinstance(um, dict):
                        usage = um
                if not text:
                    text = getattr(first, "text", "") or ""
            
            if not usage:
                llm_out = getattr(response, "llm_output", None) or {}
                tu = llm_out.get("token_usage") or llm_out.get("usage") or {}
                if isinstance(tu, dict):
                    usage = tu
        except Exception:  # noqa: BLE001
            text = ""
        text = (text or "").strip()
        
        sub_tags = self._subagent_tags(kwargs)

        
        if usage:
            self._emit_to_bus(
                "llm_end",
                payload={"name": "usage_only"},
                tags=sub_tags or None,
                usage=usage,
            )
        
        if thinking_text:
            self._emit_to_bus(
                "info",
                payload={"name": "thinking_block", "thinking": thinking_text},
                tags=sub_tags or None,
            )
        
        
        
        
        
        
        if has_tool_calls:
            content = text if text else "[Calling tools]"
            self._emit_to_bus(
                "llm_end",
                payload={"name": "thought", "content": content},
                tags=sub_tags or None,
            )
        elif text:
            
            
            
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

        
        
        run_id = str(kwargs.get("run_id") or "")
        if run_id in self._seen_tool_run_ids:
            return
        if run_id:
            self._seen_tool_run_ids.add(run_id)

        self._tool_name_stack.append(name)
        cap = 4000 if name in ("write_todos", "task") else 400

        
        
        meta = kwargs.get("metadata") or {}
        agent_name = meta.get("lc_agent_name") or ""
        is_main_agent_event = not agent_name or agent_name == "main_agent"
        if name == "task" and is_main_agent_event:
            self._current_task_tool_use_id = run_id
        elif name == "qa_invoke_skill" and is_main_agent_event:
            
            if "review-verification" in (input_str or "") or "context: fork" in (input_str or ""):
                self._current_task_tool_use_id = run_id

        tags = self._subagent_tags(kwargs, base_tags={"name": name})
        
        
        
        if run_id:
            tags["lc_tool_run_id"] = run_id
        self._emit_to_bus(
            "tool_call",
            payload={"name": name, "input": {"raw": (input_str or "")[:cap]}},
            tags=tags,
        )

    def _pop_tool_name(self) -> str:
        return self._tool_name_stack.pop() if self._tool_name_stack else ""

    def on_tool_end(self, output, **kwargs) -> None:  # noqa: D401, ANN001
        from langgraph.types import Command  # noqa: PLC0415

        
        run_id = str(kwargs.get("run_id") or "")
        if run_id and run_id not in self._seen_tool_run_ids:
            
            return
        
        self._seen_tool_run_ids.discard(run_id)

        tool_name = self._pop_tool_name()
        if isinstance(output, Command):
            
            update = getattr(output, "update", None) or {}
            if "todos" in update:
                todos = update["todos"]
                
                self._emit_to_bus(
                    "todo_list",
                    payload={"todos": todos if isinstance(todos, list) else []},
                )
                text = ""
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

        
        meta = kwargs.get("metadata") or {}
        agent_name = meta.get("lc_agent_name") or ""
        is_main_agent_event = not agent_name or agent_name == "main_agent"
        if tool_name in ("task", "qa_invoke_skill") and is_main_agent_event:
            self._current_task_tool_use_id = ""

        tags = self._subagent_tags(kwargs, base_tags={"name": tool_name})
        if run_id:
            tags["lc_tool_run_id"] = run_id
        self._emit_to_bus(
            "tool_result",
            payload={"name": tool_name, "output": text},
            tags=tags,
        )

    def on_tool_error(self, error, **kwargs) -> None:  # noqa: D401, ANN001
        
        
        run_id = str(kwargs.get("run_id") or "")
        if run_id and run_id not in self._seen_tool_run_ids:
            return
        self._seen_tool_run_ids.discard(run_id)

        tool_name = self._pop_tool_name()

        meta = kwargs.get("metadata") or {}
        agent_name = meta.get("lc_agent_name") or ""
        is_main_agent_event = not agent_name or agent_name == "main_agent"
        if tool_name in ("task", "qa_invoke_skill") and is_main_agent_event:
            self._current_task_tool_use_id = ""

        tags = self._subagent_tags(kwargs, base_tags={"name": tool_name})
        if run_id:
            tags["lc_tool_run_id"] = run_id
        self._emit_to_bus(
            "tool_result",
            payload={"name": tool_name, "output": f"error: {error}"},
            tags=tags,
        )





def qa_node(state: IstCoreState, config: RunnableConfig | None = None) -> dict[str, Any]:
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
            "recursion_limit": 300,
        }
    else:
        existing_cbs = list(config.get("callbacks") or [])
        merged_config = {
            **config,
            "callbacks": existing_cbs + [handler],


            "recursion_limit": max(config.get("recursion_limit") or 0, 300),
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





def finalize(state: IstCoreState) -> dict[str, Any]:
    """Finalize 节点：写最终 final_answer.

    Fork skill 设计：
    - fork agent 的完整 result 只通过 ToolResult 传给主 agent
    - 主 agent 自己负责把内容复述给用户
    - finalize 不再代替主 agent 展示 fork 内容（移除工程兜底）

    通用场景下：直接透传 state.final_answer，仅做 VERDICT/LEVEL 行剥离。
    """
    answer = state.get("final_answer") or ""

    
    answer = _strip_verdict_lines(answer)
    return {"final_answer": answer}



_VERDICT_LEVEL_LINE_RE = re.compile(
    r"^[ \t]*\*{0,2}(?:VERDICT|LEVEL)\*{0,2}:?\s*.*$",
    re.MULTILINE,
)


def _strip_verdict_lines(text: str) -> str:
    """从最终输出中剥离 VERDICT:/LEVEL: 行（gate 检测已在 ToolMessage 层完成）。"""
    if not text:
        return text
    stripped = _VERDICT_LEVEL_LINE_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()






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

def build_ist_core_graph(
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
    from main.ist_core.nodes.review_gate import review_gate

    g = StateGraph(IstCoreState)
    g.add_node("normalize_input", normalize_input)
    g.add_node("qa_node", qa_node)
    g.add_node("review_gate", review_gate)
    g.add_node("finalize", finalize)

    g.add_edge(START, "normalize_input")
    g.add_edge("normalize_input", "qa_node")
    
    g.add_edge("qa_node", "review_gate")
    
    
    
    
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
