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
import contextlib
import logging
import os
import time as _time
import uuid
from typing import Any, Callable, Iterable

from main.ist_core.events import EventBus, IstCoreEvent, reset_default_bus

logger = logging.getLogger(__name__)

# ---- idle timeout: 并发 monitor task，不复用 asyncio.wait_for 取消 __anext__() ----

# 节点深度：on_chain_start +1, on_chain_end -1。>0 表示正"在 graph node 内部"同步执行。
# agent.invoke() 同步跑时 astream_events 在图层面零事件——monitor 据此跳过 stall 判定。
_NODE_DEPTH: int = 0

# EventBus 心跳：_MainAgentProgressHandler 在任何线程 emit 事件时更新此时间戳。
# monitor 同时检查 node_depth 和 bus 心跳，双重确认才判定 stall。
_BUS_HEARTBEAT_TS: float = 0.0


def _on_bus_heartbeat(_event: IstCoreEvent) -> None:
    """EventBus 订阅回调：任何事件到达时更新心跳时间戳。"""
    global _BUS_HEARTBEAT_TS
    _BUS_HEARTBEAT_TS = _time.monotonic()


_KIND_MAP: dict[str, str] = {
    "on_chain_start": "node_start",
    "on_chain_end": "node_end",



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





        payload["output"] = _safe_str(data["output"])
    return payload


def _safe_str(obj: Any) -> str:
    try:
        if hasattr(obj, "content"):
            return str(obj.content)
        return str(obj)
    except Exception:  # noqa: BLE001
        return "<unrepr>"


async def _stall_monitor(
    agen: Any,
    idle_timeout: float,
    poll_interval: float,
    bus: EventBus,
) -> None:
    """并发 stall 监控：独立于主事件循环运行，定期检查是否真正 stall。

    与 asyncio.wait_for 方案的关键区别：monitor 是旁路观察者，不取消 __anext__()
    协程（取消会关闭 async generator）。只在确认 stall 时调用 agen.aclose() 通知
    主循环退出——这是 generator 协议的合法关闭方式。
    """
    _ticks: int = 0
    _max_ticks = max(1, int(idle_timeout / poll_interval))
    while True:
        await asyncio.sleep(poll_interval)

        if _NODE_DEPTH > 0:
            _ticks = 0
            continue
        if _time.monotonic() - _BUS_HEARTBEAT_TS < poll_interval + 10.0:
            _ticks = 0
            continue

        _ticks += 1
        if _ticks >= _max_ticks:
            logger.error("stall_monitor: 触发 — 关闭 generator")
            bus.emit("error", payload={"text": "运行超时：graph 事件总线与 LLM 端点均无任何事件，已中断"})
            with contextlib.suppress(Exception):
                await agen.aclose()
            return


async def astream_to_bus(
    graph: Any,
    initial_state: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    bus: EventBus | None = None,
) -> dict[str, Any]:
    """异步驱动 Graph、把 LangChain 事件翻译成 ``IstCoreEvent``。返回最终 state。"""
    bus = bus or reset_default_bus(run_id=uuid.uuid4().hex[:12])
    bus.emit("run_start", payload={"config": {"thread_id": (config or {}).get("configurable", {}).get("thread_id")}})

    final_state: dict[str, Any] = {}
    global _NODE_DEPTH, _BUS_HEARTBEAT_TS
    # 订阅 EventBus 心跳：EventBus 上任何事件都更新 _BUS_HEARTBEAT_TS。
    bus.subscribe(_on_bus_heartbeat)
    _BUS_HEARTBEAT_TS = _time.monotonic()
    _NODE_DEPTH = 0
    _monitor_task: asyncio.Task | None = None
    try:
        _agen = graph.astream_events(initial_state, config=config, version="v2")
        _idle = float(os.environ.get("IST_LLM_IDLE_TIMEOUT") or "300")
        _POLL_INTERVAL = 60.0
        # 启动并发 stall monitor：旁路检查，不参与事件消费，不取消 __anext__()
        _monitor_task = asyncio.ensure_future(
            _stall_monitor(_agen, _idle, _POLL_INTERVAL, bus)
        )
        # 主循环：async for 是最安全的消费方式，不会取消 __anext__()
        async for ev in _agen:
            lc_kind = ev.get("event") or ""
            # 追踪节点深度：on_chain_start 进入 node，on_chain_end 离开 node
            if lc_kind == "on_chain_start":
                _NODE_DEPTH += 1
            elif lc_kind == "on_chain_end":
                _NODE_DEPTH = max(0, _NODE_DEPTH - 1)
            mapped = _KIND_MAP.get(lc_kind, "info")
            tags = {"lc_event": lc_kind, "name": ev.get("name") or ""}
            metadata = ev.get("metadata") or {}
            if "langgraph_node" in metadata:
                tags["node"] = metadata["langgraph_node"]
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
                    for k in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                        if k in raw and k not in usage:
                            usage[k] = raw[k]
                if usage == {}:
                    usage = None
            payload = _to_event_payload(ev)
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
        if _monitor_task is not None and not _monitor_task.done():
            _monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await _monitor_task
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

    try:
        return asyncio.run(astream_to_bus(graph, initial_state, config=config, bus=bus))
    except RuntimeError:

        logger.warning("已有事件循环，退回到同步 invoke")
        return graph.invoke(initial_state, config)
