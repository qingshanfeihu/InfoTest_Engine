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

from main.ist_core.resilience import is_transient_error
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






def extract_llm_usage(response) -> dict:
    """从 LLMResult 提取 usage(usage_metadata + llm_output 的 cache 字段合并)。

    usage_metadata 有 input/output/total 但缺 cache;response.llm_output.token_usage
    有 DeepSeek 顶层 prompt_cache_hit/miss_tokens 或 OpenAI prompt_tokens_details.cached_tokens。
    这是主 agent(IstCallback)与 fork(loader._ForkUsageTally)共用的唯一口径——
    每次 LLM 调用即时取 API 返回的真实计量,与供应商官方统计同源。
    """
    usage: dict = {}
    try:
        gens = getattr(response, "generations", None) or []
        if gens and gens[0]:
            msg = getattr(gens[0][0], "message", None)
            um = getattr(msg, "usage_metadata", None)
            if isinstance(um, dict):
                usage = dict(um)
        llm_out = getattr(response, "llm_output", None) or {}
        raw = llm_out.get("token_usage") or llm_out.get("usage") or {}
        if isinstance(raw, dict) and raw:
            if not usage:
                usage = dict(raw)
            for k in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                if k in raw and k not in usage:
                    usage[k] = raw[k]
            if "prompt_cache_hit_tokens" not in usage:
                ptd = raw.get("prompt_tokens_details") or {}
                cached = ptd.get("cached_tokens")
                if isinstance(cached, int) and cached > 0:
                    usage["prompt_cache_hit_tokens"] = cached
                    prompt_total = usage.get("input_tokens") or raw.get("prompt_tokens") or 0
                    usage["prompt_cache_miss_tokens"] = max(prompt_total - cached, 0)
    except Exception:  # noqa: BLE001
        pass
    return usage


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
        # run_id → fork agent 名。LangChain 只在 *_start 回调传 metadata,end/error 不传,
        # 所以 fork 判定必须在 on_chat_model_start 记账、on_llm_end 查账——直接在 end 里
        # 调 _subagent_tags 恒判不出 fork(2026-07-02 实证:fork usage 因此全量误发
        # usage_only 进主计数,footer 显示恰为真实消耗的 2 倍)。
        self._fork_llm_runs: dict[str, str] = {}
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

        - ``parent_subagent``: 子 agent 名（如 "review-verifier"）
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
        # fork 子 agent 的 LLM 开始 → 向 EventBus 发 phase 事件，
        # 驱动 footer busy 行显示"接收/处理中"(实时状态、非累加)。
        # 不发 usage_only(累加归 _FORK_TOKENS、避开双重计数)。
        try:
            sub_tags = self._subagent_tags(kwargs)
            if sub_tags.get("parent_subagent"):
                rid = str(kwargs.get("run_id") or "")
                if rid:
                    self._fork_llm_runs[rid] = sub_tags["parent_subagent"]
                self._emit_to_bus(
                    "llm_start",
                    tags=sub_tags or None,
                )
        except Exception:  # noqa: BLE001
            pass

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
                    
                if not text:
                    text = getattr(first, "text", "") or ""

            usage = extract_llm_usage(response)
        except Exception:  # noqa: BLE001
            text = ""
        text = (text or "").strip()

        sub_tags = self._subagent_tags(kwargs)
        # end 回调的 kwargs 不带 metadata → 上面判不出 fork;用 start 时记的账本补全。
        rid = str(kwargs.get("run_id") or "")
        if not sub_tags.get("parent_subagent"):
            fork_name = self._fork_llm_runs.pop(rid, "")
            if fork_name:
                sub_tags["parent_subagent"] = fork_name
                if getattr(self, "_current_task_tool_use_id", ""):
                    sub_tags.setdefault("parent_tool_use_id", self._current_task_tool_use_id)
        else:
            self._fork_llm_runs.pop(rid, None)

        # fork 子 agent 的 usage 不发 EventBus（reducer 会跳过），直接写 _FORK_TOKENS。
        # 主 agent 的 usage 正常发 EventBus——usage_only 是主 agent usage 的唯一权威源;
        # astream_events 的 on_chat_model_end 也可能带同一份 usage(qa_node async 化后
        # 该路径重新可见),reducer 端只认 usage_only,防双计。
        if usage:
            if sub_tags.get("parent_subagent"):
                # fork 的 usage 由 loader._ForkUsageTally(fork invoke 显式挂载)统一收集
                # ——此处不再累计(contextvar 传播使本回调也能看到 fork 调用,双计过)。
                # 本分支只负责「不发 usage_only」,防 fork 用量灌进主计数。
                pass
            else:
                self._emit_to_bus(
                    "llm_end",
                    payload={"name": "usage_only"},
                    tags=sub_tags or None,
                    usage=usage,
                )
        
        if thinking_text:
            # fork 的 thinking 块不向 EventBus 发 info(避免与主 transcript 混淆，
            # 实际 fork thinking 由 fastlog/evidence 行承载)。
            if not sub_tags.get("parent_subagent"):
                self._emit_to_bus(
                    "info",
                    payload={"name": "thinking_block", "thinking": thinking_text},
                    tags=sub_tags or None,
                )
        
        
        
        
        
        
        if has_tool_calls:
            if sub_tags.get("parent_subagent"):
                # fork 的 tool_call thought 不入主 transcript;仅发空 llm_end 清 phase
                self._emit_to_bus(
                    "llm_end",
                    payload={"name": "fork_done"},
                    tags=sub_tags or None,
                )
            else:
                content = text if text else "[Calling tools]"
                self._emit_to_bus(
                    "llm_end",
                    payload={"name": "thought", "content": content},
                    tags=sub_tags or None,
                )
        elif text:
            if sub_tags.get("parent_subagent"):
                # fork 的最终 thought 不入主 transcript(由 fastlog 承载);
                # 仅发空 llm_end 让 reducer 清 phase，避免 footer 永远卡 thinking。
                self._emit_to_bus(
                    "llm_end",
                    payload={"name": "fork_done"},
                    tags=sub_tags or None,
                )
            else:
                self._emit_to_bus(
                    "llm_end",
                    payload={"name": "final_thought", "content": text},
                    tags=sub_tags or None,
                )

    def on_llm_error(self, error, **kwargs) -> None:  # noqa: D401, ANN001
        # 失败的调用没有 on_llm_end,清掉账本条目防泄漏。
        self._fork_llm_runs.pop(str(kwargs.get("run_id") or ""), None)

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
        elif name == "invoke_skill" and is_main_agent_event:
            
            if "review-verifier" in (input_str or "") or "context: fork" in (input_str or ""):
                self._current_task_tool_use_id = run_id

        tags = self._subagent_tags(kwargs, base_tags={"name": name})



        if run_id:
            tags["lc_tool_run_id"] = run_id
        # durable 主 agent 活动日志（治长跑卡住时主 agent 时间线不可见的盲区）。
        # 只记主 agent 自身的 tool_call；子 agent fork 已有 fork_status.jsonl。
        if is_main_agent_event:
            try:
                from main.ist_core.resilience import record_main_activity
                record_main_activity("tool_start", tool_name=name,
                                     detail=(input_str or "")[:150])
            except Exception:  # noqa: BLE001
                pass
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
        if tool_name in ("task", "invoke_skill") and is_main_agent_event:
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
        if tool_name in ("task", "invoke_skill") and is_main_agent_event:
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
    # Langfuse 链路追踪(2026-07-09 替代 LangSmith 全局自动 tracing):env 门控,
    # 未启用返回 None。主 agent 是主链路,缺它则整条对话不进 Langfuse。
    from main.ist_core.observability import get_langfuse_handler
    _lf = get_langfuse_handler()
    _extra_cbs = [handler] + ([_lf] if _lf else [])

    if config is None:
        merged_config: RunnableConfig = {
            "callbacks": _extra_cbs,
            "recursion_limit": 300,
        }
    else:
        existing_cbs = list(config.get("callbacks") or [])
        merged_config = {
            **config,
            "callbacks": existing_cbs + _extra_cbs,


            "recursion_limit": max(config.get("recursion_limit") or 0, 300),
        }

    try:
        result = agent.invoke(agent_input, config=merged_config)
    except Exception as exc:  # noqa: BLE001
        if is_transient_error(exc):
            raise  # 传播到 bridge 层统一处理，不吞掉让 agent 有机会重试
        logger.exception("qa_node 调用 MainAgent 失败: %s", exc)
        return {"final_answer": f"[error] {exc}", "messages": [AIMessage(content=f"错误: {exc}")]}

    messages = result.get("messages") or []
    answer = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            answer = msg.content if isinstance(msg.content, str) else str(msg.content)
            break
    return {"messages": messages, "final_answer": answer}





async def _qa_node_async(state: IstCoreState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """qa_node 的 async 包装——TUI 的 astream_events(async)走这条。

    把同步阻塞的 qa_node 用 to_thread 挪到工作线程、让出 event loop。否则 langgraph 1.2.6
    把同步 node 内联占死 loop 线程(RunnableCallable.ainvoke 无 afunc 时直接同步跑),
    AsyncSqliteSaver.put_writes 的 run_coroutine_threadsafe(...).result() 就会同步等一个
    被自己占死的 loop -> main-orchestrated 长 turn 死锁。
    runner.py 的 sync graph.invoke 仍走同步 qa_node(RunnableCallable 按 sync/async 自动分派)。
    """
    return await asyncio.to_thread(qa_node, state, config)


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
    from main.ist_core.nodes.goal_gate import goal_gate
    from main.ist_core.nodes.review_gate import review_gate

    g = StateGraph(IstCoreState)
    g.add_node("normalize_input", normalize_input)
    from langgraph.utils.runnable import RunnableCallable
    # RunnableCallable(同步 qa_node, 异步 _qa_node_async)：runner.py 的 sync graph.invoke
    # 走同步版；TUI 的 astream_events(async) 走异步版(to_thread 让出 loop,避免 async
    # AsyncSqliteSaver 死锁)。否则纯 async node 会让 sync invoke 抛 "No synchronous function"。
    g.add_node("qa_node", RunnableCallable(qa_node, _qa_node_async))
    g.add_node("review_gate", review_gate)
    g.add_node("goal_gate", goal_gate)
    g.add_node("finalize", finalize)

    g.add_edge(START, "normalize_input")
    g.add_edge("normalize_input", "qa_node")
    g.add_edge("qa_node", "review_gate")

    # review_gate passed → 进 goal_gate（/goal 自治循环闸；无 goal 时透传到 finalize）。
    g.add_conditional_edges(
        "review_gate",
        lambda s: s.get("gate_status", "passed"),
        {
            "passed": "goal_gate",
            "pending": "qa_node",
            "failed": "finalize",
        },
    )
    # goal_gate：达成/无目标/超上限 → finalize；未达成 → 注入反馈回 qa_node 继续。
    g.add_conditional_edges(
        "goal_gate",
        lambda s: s.get("goal_status", "inactive"),
        {
            "inactive": "finalize",
            "met": "finalize",
            "exhausted": "finalize",
            "unmet": "qa_node",
        },
    )
    g.add_edge("finalize", END)

    compile_kwargs: dict[str, Any] = {}
    if checkpointer is True:
        compile_kwargs["checkpointer"] = _make_checkpointer(mode=checkpointer_mode)
    elif checkpointer not in (False, None):
        compile_kwargs["checkpointer"] = checkpointer

    return g.compile(**compile_kwargs)
