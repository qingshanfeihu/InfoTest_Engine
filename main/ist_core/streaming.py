"""``astream_events(version="v2")`` -> ``IstCoreEvent`` 适配层。

对应原计划 §16.2 "LangGraph + LangChain v1 统一接入"。

实现要点：
- 只消费事件，不修改 Graph
- LangGraph 原生事件类型 -> IstCoreEvent kind 映射表：
    on_chain_start / on_chain_end   -> node_start / node_end
    on_tool_start                   -> tool_call（唯一 tool_call 源）
    on_chat_model_start / _stream / _end -> llm_start / llm_token / llm_end
- on_tool_end 不在此处映射（_to_event_payload 的 output 是 str(obj) 粗粒度；
  _MainAgentProgressHandler.on_tool_end 提供精确 output + write_todos todo_list）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from typing import Any, Callable, Iterable

from main.ist_core.events import EventBus, IstCoreEvent, reset_default_bus

logger = logging.getLogger(__name__)


def _trigger_token_aggregation() -> None:
    """每个 run 结束后后台聚合当天 token。（ON CONFLICT upsert，幂等、低开销）"""
    try:
        from datetime import date, datetime, timezone
        from main.ist_core.auth.token_aggregator import aggregate_daily_tokens

        today = datetime.now(timezone.utc).date()
        threading.Thread(
            target=aggregate_daily_tokens,
            args=(today,),
            name="token-agg",
            daemon=True,
        ).start()
    except Exception:
        logger.debug("token 自动聚合触发失败", exc_info=True)


_KIND_MAP: dict[str, str] = {
    "on_chain_start": "node_start",
    "on_chain_end": "node_end",
    "on_tool_start": "tool_call",
    "on_tool_end": "tool_result",
    "on_chat_model_start": "llm_start",
    "on_chat_model_stream": "llm_token",
    "on_chat_model_end": "llm_end",
    "on_prompt_start": "info",
    "on_prompt_end": "info",
    "on_custom_event": "info",
}


def _to_event_payload(lc_event: dict[str, Any]) -> dict[str, Any]:
    name = lc_event.get("name") or ""
    data = lc_event.get("data") or {}
    payload: dict[str, Any] = {"name": name}
    if "chunk" in data:
        chunk = data["chunk"]
        content = getattr(chunk, "content", None)
        if content is None and isinstance(chunk, dict):
            content = chunk.get("content")
        if isinstance(content, str):
            payload["content"] = content
        # reasoning_content（思考增量）：mimo 深度思考期以此逐步返回，content 为空。
        # 抽出来让 reducer 识别「思考相位」（footer 显示真实 think 状态）+ 逐字渲染。
        ak = getattr(chunk, "additional_kwargs", None)
        if ak is None and isinstance(chunk, dict):
            ak = chunk.get("additional_kwargs")
        if isinstance(ak, dict):
            rc = ak.get("reasoning_content")
            if isinstance(rc, str) and rc:
                payload["reasoning"] = rc
    if "input" in data:
        payload["input"] = _safe_str(data["input"])[:500]
    if "output" in data:
        
        
        
        
        
        
        
        payload["output"] = _safe_str(data["output"])
    return payload


def _safe_str(obj: Any) -> str:
    try:
        if hasattr(obj, "content"):
            return str(obj.content)
        return str(obj)
    except Exception:  # noqa: BLE001
        return "<unrepr>"


async def astream_to_bus(
    graph: Any,
    initial_state: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    bus: EventBus | None = None,
) -> dict[str, Any]:
    """异步驱动 Graph、把 LangChain 事件翻译成 ``IstCoreEvent``。返回最终 state。"""
    bus = bus or reset_default_bus(run_id=uuid.uuid4().hex[:12])

    user_input = ""
    if isinstance(initial_state, dict):
        messages = initial_state.get("messages", [])
        if messages:
            last_msg = messages[-1]
            if hasattr(last_msg, "content"):
                user_input = str(last_msg.content) if last_msg.content else ""
            elif isinstance(last_msg, dict):
                user_input = str(last_msg.get("content", ""))

    thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
    bus.emit("run_start", payload={
        "config": {"thread_id": thread_id},
        "user_input": user_input,
    }, tags={"configurable_thread_id": thread_id})

    final_state: dict[str, Any] = {}
    try:
        _agen = graph.astream_events(initial_state, config=config, version="v2")
        # 死挂 / 内容静默兜底交给 langchain-openai 内置的底层 stream_chunk_timeout(默认 120s,
        # env LANGCHAIN_OPENAI_STREAM_CHUNK_TIMEOUT_S):它在 SSE parsed-chunk 层计时,SDK 内部消费
        # keepalive 注释、不当 chunk,因此能正确区分 keepalive 与真内容静默,触发时抛
        # StreamChunkTimeoutError(asyncio.TimeoutError 子类)由下方 except Exception 接住、不致永久挂。
        # 不再手搓上层"事件间隔"idle 守卫:它基于 astream_events 上层事件计时,而 mimo 深度思考期端点
        # 在底层周期性吐空 delta chunk(<120s),这些 chunk 在 _convert_chunk_to_generation_chunk 因
        # delta 为空被丢成 None、不上抛 on_chat_model_stream 事件 → 上层"零事件"被误判 stall
        # (实测精确 300s 误杀长思考,亦会误伤 ist-verify 上机长跑等单步长耗时)。职责收口到官方底层 timer。
        while True:
            try:
                ev = await _agen.__anext__()
            except StopAsyncIteration:
                break
            lc_kind = ev.get("event") or ""
            mapped = _KIND_MAP.get(lc_kind, "info")
            tags = {"lc_event": lc_kind, "name": ev.get("name") or ""}
            metadata = ev.get("metadata") or {}
            if "langgraph_node" in metadata:
                tags["node"] = metadata["langgraph_node"]
            # fork 子 agent 标识：callback handler 通过 _subagent_tags 设置，
            # astream_events 通过 metadata.lc_agent_name 传递。reducer 据此
            # 跳过 fork usage（避免与 _FORK_TOKENS 双重计数）。
            lc_agent = metadata.get("lc_agent_name") or ""
            if lc_agent and lc_agent not in ("main_agent", ""):
                tags["parent_subagent"] = lc_agent
            usage = None
            data = ev.get("data") or {}
            if "output" in data and hasattr(data["output"], "usage_metadata"):
                um = getattr(data["output"], "usage_metadata", None)
                if isinstance(um, dict):
                    usage = dict(um)
                
                rmeta = getattr(data["output"], "response_metadata", None) or {}
                raw = rmeta.get("token_usage") or rmeta.get("usage") or {}
                if isinstance(raw, dict):
                    if usage is None:
                        usage = {}
                    # DeepSeek: 顶层 prompt_cache_hit_tokens / prompt_cache_miss_tokens
                    for k in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                        if k in raw and k not in usage:
                            usage[k] = raw[k]
                    # MiMo / OpenAI 标准: prompt_tokens_details.cached_tokens
                    if "prompt_cache_hit_tokens" not in usage:
                        ptd = raw.get("prompt_tokens_details") or {}
                        cached = ptd.get("cached_tokens")
                        if isinstance(cached, int) and cached > 0:
                            usage["prompt_cache_hit_tokens"] = cached
                            prompt_total = usage.get("input_tokens") or raw.get("prompt_tokens") or 0
                            usage["prompt_cache_miss_tokens"] = max(prompt_total - cached, 0)
                if usage == {}:
                    usage = None
            payload = _to_event_payload(ev)
            # 从 usage_metadata / response_metadata 提取真实模型名(如 mimo-v2.5-pro)，
            # 注入 payload.model_name——两 sink 都从此读取，拿 LC 类名(ChatOpenAI)没用。
            _output_obj = data.get("output") if isinstance(data, dict) else None
            if _output_obj is not None:
                rmeta = getattr(_output_obj, "response_metadata", None) or {}
                _real_model = rmeta.get("model_name") or ""
                if not _real_model and isinstance(usage, dict):
                    _real_model = usage.get("model_name", "")
                if not _real_model and hasattr(_output_obj, "name"):
                    _real_model = str(getattr(_output_obj, "name", ""))
                if _real_model:
                    payload["model_name"] = _real_model
            if lc_kind == "on_custom_event":
                custom_payload = data.get("chunk") or data.get("input") or data.get("output") or {}
                if isinstance(custom_payload, dict) and isinstance(custom_payload.get("progress"), dict):
                    payload = custom_payload["progress"]
                    event_name = payload.get("event")
                    if isinstance(event_name, str):
                        tags["progress_event"] = event_name
                        
                        if event_name in {"phase_marker", "evidence_added", "finding_emitted"}:
                            mapped = event_name
                        
                        
                        elif event_name == "tool_start":
                            mapped = "tool_call"
                            tool_name = payload.get("tool_name") or ""
                            tags["name"] = tool_name
                            input_preview = payload.get("input_preview") or ""
                            payload = {"name": tool_name, "input": {"raw": input_preview}}
                        elif event_name == "tool_end":
                            mapped = "tool_result"
                            tool_name = payload.get("tool_name") or ""
                            tags["name"] = tool_name
                            output_preview = payload.get("output_preview") or payload.get("output") or ""
                            payload = {"name": tool_name, "output": output_preview}
                        elif event_name == "thought":
                            
                            mapped = "llm_end"
                            payload = {"name": "thought", "content": payload.get("content", "")}
                        elif event_name == "run_start":
                            mapped = "info"
                            payload = {"info_text": ""}
                        elif event_name == "run_end":
                            mapped = "info"
                            payload = {"info_text": ""}
                        elif event_name == "run_error":
                            mapped = "error"
                            payload = {"error": payload.get("message", "")}
            bus.emit(mapped, payload=payload, tags=tags, usage=usage)

            
            if lc_kind == "on_chain_end" and (ev.get("name") in ("LangGraph", "agent")):
                out = data.get("output")
                if isinstance(out, dict):
                    final_state = out
    except Exception as exc:  # noqa: BLE001
        bus.emit("error", payload={"error": str(exc)})
        raise
    finally:
        bus.emit("run_end", payload={})

    
    if not final_state:
        try:
            final_state = graph.invoke(initial_state, config)
        except Exception as exc:  # noqa: BLE001
            logger.warning("final invoke 兜底失败: %s", exc)
    return final_state


def stream_and_collect(
    graph: Any,
    initial_state: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    sinks: Iterable[Callable[[IstCoreEvent], None]] = (),
) -> dict[str, Any]:
    """同步入口：运行 Graph、订阅事件到 sinks、返回最终 state。"""
    bus = reset_default_bus(run_id=uuid.uuid4().hex[:12])
    for sink in sinks:
        bus.subscribe(sink)
    # 注入会话上下文到 bus default_tags（审计 sink 用）
    import os as _os
    _session_user = _os.environ.get("IST_SSH_USER", "").strip()
    _session_id = _os.environ.get("IST_AUTH_SESSION_ID", "").strip()
    _conversation_id = _os.environ.get("IST_CONVERSATION_ID", "").strip()
    if _session_user or _session_id:
        _thread_id = (config or {}).get("configurable", {}).get("thread_id", "")
        bus.set_default_tags({
            "session_user": _session_user,
            "session_id": _session_id,
            "conversation_id": _conversation_id,
            "thread_id": _thread_id,
        })
    # 自动注册 PgAuditSink（第四个 Sink：CLI / JSONL / LangSmith / Audit）
    try:
        from main.ist_core.sinks.pg_sink import PgAuditSink
        bus.subscribe(PgAuditSink())
    except Exception as exc:
        logger.debug("PgAuditSink 注册失败（审计日志禁用）: %s", exc)
    # 自动注册 DialogueCollector（第五个 Sink：对话业务持久存储）
    if _session_user and _session_id and _conversation_id:
        try:
            from main.ist_core.sinks.dialog_sink import DialogueCollector
            dialog_collector = DialogueCollector(
                username=_session_user,
                session_id=_session_id,
                conversation_id=_conversation_id,
            )
            bus.subscribe(dialog_collector)
        except Exception as exc:
            logger.debug("DialogueCollector 注册失败: %s", exc)
    # 自动注册 TraceCollector（对话轮次 trace 聚合写入）
    try:
        from main.ist_core.sinks.trace_collector import TraceCollector
        bus.subscribe(TraceCollector())
    except Exception as exc:
        logger.debug("TraceCollector 注册失败: %s", exc)

    try:
        return asyncio.run(astream_to_bus(graph, initial_state, config=config, bus=bus))
    except RuntimeError:

        logger.warning("已有事件循环，退回到同步 invoke")
        return graph.invoke(initial_state, config)
    finally:
        # 每个 run 结束后后台聚合一次当天 token（ON CONFLICT upsert，幂等、低开销）
        _trigger_token_aggregation()
