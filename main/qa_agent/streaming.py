"""``astream_events(version="v2")`` -> ``QaAgentEvent`` 适配层。

对应原计划 §16.2 "LangGraph + LangChain v1 统一接入"。

实现要点：
- 只消费事件，不修改 Graph
- LangGraph 原生事件类型 -> QaAgentEvent kind 映射表：
    on_chain_start / on_chain_end   -> node_start / node_end
    on_tool_start / on_tool_end     -> tool_call / tool_result
    on_chat_model_start / _stream / _end -> llm_start / llm_token / llm_end
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Iterable

from main.qa_agent.events import EventBus, QaAgentEvent, reset_default_bus

logger = logging.getLogger(__name__)


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
    if "input" in data:
        payload["input"] = _safe_str(data["input"])[:500]
    if "output" in data:
        # 注：node_end 的 output 不截断——TUI 需要完整 final_answer 才能渲染 AI 消息
        # （agent.invoke 同步调用不发 token stream；TUI 靠 node_end output 兜底）
        payload["output"] = _safe_str(data["output"])
        # 顺便把 output 解析的 final_answer 单独抽出来，sink 优先用这个
        out = data["output"]
        if isinstance(out, dict):
            ans = out.get("final_answer")
            if isinstance(ans, str) and ans.strip():
                payload["final_answer"] = ans
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
    """异步驱动 Graph、把 LangChain 事件翻译成 ``QaAgentEvent``。返回最终 state。"""
    bus = bus or reset_default_bus(run_id=uuid.uuid4().hex[:12])
    bus.emit("run_start", payload={"config": {"thread_id": (config or {}).get("configurable", {}).get("thread_id")}})

    final_state: dict[str, Any] = {}
    try:
        async for ev in graph.astream_events(initial_state, config=config, version="v2"):
            lc_kind = ev.get("event") or ""
            mapped = _KIND_MAP.get(lc_kind, "info")
            tags = {"lc_event": lc_kind, "name": ev.get("name") or ""}
            metadata = ev.get("metadata") or {}
            if "langgraph_node" in metadata:
                tags["node"] = metadata["langgraph_node"]
            usage = None
            data = ev.get("data") or {}
            if "output" in data and hasattr(data["output"], "usage_metadata"):
                usage = getattr(data["output"], "usage_metadata", None)
            payload = _to_event_payload(ev)
            if lc_kind == "on_custom_event":
                custom_payload = data.get("chunk") or data.get("input") or data.get("output") or {}
                if isinstance(custom_payload, dict) and isinstance(custom_payload.get("progress"), dict):
                    payload = custom_payload["progress"]
                    event_name = payload.get("event")
                    if isinstance(event_name, str):
                        tags["progress_event"] = event_name
                        # 已知 reviewer 风格的语义事件 -> 直接映射
                        if event_name in {"phase_marker", "evidence_added", "finding_emitted"}:
                            mapped = event_name
                        # main_agent 的 LangChain callback 转发的工具/思考事件 -> 同样路由到
                        # tool_call / tool_result / info（让 TUI sink 像看真 stream 一样消费）
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
                            # AI 中间步思考 -> llm_end 风格的整段消息，TUI 渲染成 AIFinalMessage
                            mapped = "llm_end"
                            payload = {"name": "thought", "content": payload.get("content", "")}
                        elif event_name == "run_start":
                            mapped = "info"
                            payload = {"info_text": ""}  # 不渲染 run_start
                        elif event_name == "run_end":
                            mapped = "info"
                            payload = {"info_text": ""}
                        elif event_name == "run_error":
                            mapped = "error"
                            payload = {"error": payload.get("message", "")}
            bus.emit(mapped, payload=payload, tags=tags, usage=usage)

            # astream_events v2 不会自动返回 final state；用 last on_chain_end（root）的 output 兜底
            if lc_kind == "on_chain_end" and (ev.get("name") in ("LangGraph", "agent")):
                out = data.get("output")
                if isinstance(out, dict):
                    final_state = out
    except Exception as exc:  # noqa: BLE001
        bus.emit("error", payload={"error": str(exc)})
        raise
    finally:
        bus.emit("run_end", payload={})

    # 兜底：如果没抓到 root output，再同步 invoke 一次
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
    sinks: Iterable[Callable[[QaAgentEvent], None]] = (),
) -> dict[str, Any]:
    """同步入口：运行 Graph、订阅事件到 sinks、返回最终 state。"""
    bus = reset_default_bus(run_id=uuid.uuid4().hex[:12])
    for sink in sinks:
        bus.subscribe(sink)

    try:
        return asyncio.run(astream_to_bus(graph, initial_state, config=config, bus=bus))
    except RuntimeError:
        # 已有 event loop（如 Jupyter）-> 同步回退
        logger.warning("已有事件循环，退回到同步 invoke")
        return graph.invoke(initial_state, config)
