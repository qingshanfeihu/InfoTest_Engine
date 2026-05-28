"""TUI 单源 reducer —— 把 ``QaAgentEvent`` 流翻译成 ``MessageSnapshot``。

事件流的"翻译者"，所有 UI 状态都从这里派生。设计要点：

1. **同帧原子性**：``_on_llm_end`` 同一次调用内 ``_streaming_text=None`` +
   ``_messages.append(...)`` 连续完成，``_notify`` 只在 dispatch 末尾调一次——
   订阅者拿到的 snapshot 永远一致，不会撞到中间态（atomic: no gap, no
   duplication）。

2. **keyed reconciliation**：每个 message 的 uuid = ``f"{run_id}:{seq}"``，UI
   端按 uuid in-place 更新 TextNode（Transcript 实现）。

3. **subagent 扁平挂载**：parent_subagent tag 命中的事件不再嵌套到容器子树，
   而是写到 message.parent_tool_use_id，由 UI 渲染时折叠。这样事件乱序也无所谓。

4. **拆双源**：``streaming.py`` 里 final_answer 透传删除后，TUI 路径只通过
   ``llm_end name=thought / final_thought`` 进 messages，``node_end.final_answer``
   不再投递。CLI runner 仍直读 ``state["final_answer"]``，不受影响。

5. **status 状态**：run_start/run_end/run_error 统一更新 ``_status``，UI 端
   据此切 footer / spinner。
"""

from __future__ import annotations

import logging
import threading
from types import MappingProxyType
from typing import Any, Callable, Mapping

from main.qa_agent.events import QaAgentEvent
from main.qa_agent.tui.message_model import (
    BLOCK_EVIDENCE,
    BLOCK_FINDING,
    BLOCK_HIL_DECISION,
    BLOCK_HIL_REQUEST,
    BLOCK_PHASE_MARKER,
    BLOCK_THINKING,
    BLOCK_TODO_LIST,
    BLOCK_TOOL_USE,
    ContentBlock,
    Message,
    MessageSnapshot,
    append_content_block,
    make_assistant_message,
    make_payload_block,
    make_system_message,
    make_text_block,
    make_thinking_block,
    make_tool_result_block,
    make_tool_use_block,
    make_user_message,
    make_uuid,
    replace_content_block,
)

logger = logging.getLogger(__name__)


_HIL_REQUEST_KEYS = ("findings", "draft_answer", "reason")


class MessageReducer:
    """订阅 QaAgentEvent → 输出 MessageSnapshot。

    线程模型：bridge 后台线程同步调用 ``dispatch``；订阅回调在同一线程内执行，
    UI 层在回调里负责跨线程投递（``app.call_from_thread``）。reducer 自身不
    关心线程切换。
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._streaming_text: str | None = None
        self._status: str = "idle"
        self._usage: dict[str, int] = {}

        # tool_use_id 索引：tool_call 时记 tool_use_id，tool_result 时回查。
        # 命中点是同一 ``run_id:seq``（LangChain on_tool_start/on_tool_end 成对）。
        self._inflight_tool_use_ids: list[str] = []

        # subagent task tool_use_id 栈：主 agent 调 ``task`` tool 时入栈，
        # task 工具结束时出栈。带 ``parent_subagent`` tag 的事件挂到栈顶 id 下。
        self._subagent_parent_stack: list[str] = []

        self._listeners: list[Callable[[MessageSnapshot], None]] = []
        self._lock = threading.Lock()

    # -- Public API ----------------------------------------------------------

    def subscribe(self, cb: Callable[[MessageSnapshot], None]) -> None:
        self._listeners.append(cb)

    def snapshot(self) -> MessageSnapshot:
        return MessageSnapshot(
            messages=tuple(self._messages),
            streaming_text=self._streaming_text,
            status=self._status,
            usage=MappingProxyType(dict(self._usage)),
        )

    def reset(self) -> None:
        with self._lock:
            self._messages.clear()
            self._streaming_text = None
            self._status = "idle"
            self._usage.clear()
            self._inflight_tool_use_ids.clear()
            self._subagent_parent_stack.clear()
        self._notify()

    def set_run_status(self, status: str) -> None:
        """外部（bridge）通知 run 完成 / 失败。dispatch 流末尾的 status 切换。"""
        with self._lock:
            self._status = status
        self._notify()

    def dispatch(self, event: QaAgentEvent) -> None:
        kind = event.get("kind") or ""
        try:
            with self._lock:
                self._handle(kind, event)
        except Exception:  # noqa: BLE001
            logger.exception("MessageReducer dispatch error: kind=%s", kind)
        self._notify()

    # -- Internal handler dispatch ------------------------------------------

    def _handle(self, kind: str, event: QaAgentEvent) -> None:
        if kind == "run_start":
            self._status = "running"
        elif kind == "run_end":
            self._status = "done"
        elif kind == "run_error":
            self._status = "error"
            self._on_error(event)
        elif kind == "error":
            self._on_error(event)
        elif kind == "warn":
            self._on_warn(event)
        elif kind == "llm_token":
            self._on_token(event)
        elif kind == "llm_end":
            self._on_llm_end(event)
        elif kind == "llm_start":
            # llm_start 不创建 message；流式靠 _on_token 累加
            pass
        elif kind in ("tool_call", "tool_start"):
            self._on_tool_call(event)
        elif kind in ("tool_result", "tool_end"):
            self._on_tool_result(event)
        elif kind == "info":
            self._on_info(event)
        elif kind == "phase_marker":
            self._on_payload_block(event, BLOCK_PHASE_MARKER)
        elif kind == "evidence_added":
            self._on_payload_block(event, BLOCK_EVIDENCE)
        elif kind in ("finding_emitted", "finding_written"):
            self._on_payload_block(event, BLOCK_FINDING)
        elif kind == "hil_request":
            self._on_hil_request(event)
        elif kind == "hil_response":
            self._on_hil_response(event)
        # node_start / node_end 不入 messages（无对等 UI 事件）

    # -- Token streaming -----------------------------------------------------

    def _on_token(self, event: QaAgentEvent) -> None:
        content = (event.get("payload") or {}).get("content") or ""
        if not isinstance(content, str) or not content:
            return
        if self._streaming_text is None:
            self._streaming_text = content
        else:
            self._streaming_text = self._streaming_text + content

    # -- LLM end (final / intermediate thought) ------------------------------

    def _on_llm_end(self, event: QaAgentEvent) -> None:
        payload = event.get("payload") or {}
        name = payload.get("name") or ""
        usage = event.get("usage")
        if isinstance(usage, dict):
            self._merge_usage(usage)

        # usage_only —— 只累 token，不入 messages
        if name == "usage_only":
            return

        content = payload.get("content") or ""
        if not isinstance(content, str):
            content = str(content)

        # ``thought`` 中 "[Calling tools]" 占位（带 tool_calls 但无文本时 graph emit）
        # 不渲染纯占位文本——会让 UI 出现空 bubble
        if not content or content == "[Calling tools]":
            # 仍要清流式态（ReAct 中间步可能先 stream 文本再带 tool_calls）
            self._streaming_text = None
            return

        # 同帧原子性：清流式态 + push 终态。订阅者只看到一致 snapshot
        self._streaming_text = None

        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        uuid = make_uuid(run_id, seq)
        ts = event.get("ts") or ""

        parent_tool_use_id = self._current_subagent_parent(event)
        subagent_type = (event.get("tags") or {}).get("parent_subagent") or ""

        msg = make_assistant_message(
            uuid=uuid,
            content=make_text_block(content),
            timestamp=ts,
            parent_tool_use_id=parent_tool_use_id,
            subagent_type=subagent_type,
        )
        self._messages.append(msg)

    # -- Tool call / result --------------------------------------------------

    def _on_tool_call(self, event: QaAgentEvent) -> None:
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        tags = event.get("tags") or {}
        payload = event.get("payload") or {}

        tool_name = tags.get("name") or payload.get("name") or ""
        raw_input = payload.get("input") or {}
        if isinstance(raw_input, dict) and "raw" in raw_input and len(raw_input) == 1:
            input_dict: Mapping[str, Any] = raw_input
        elif isinstance(raw_input, dict):
            input_dict = raw_input
        else:
            input_dict = {"raw": str(raw_input)}

        tool_use_id = make_uuid(run_id, seq)
        block = make_tool_use_block(
            tool_use_id=tool_use_id,
            name=tool_name,
            input=input_dict,
            status="running",
        )

        parent_tool_use_id = self._current_subagent_parent(event)
        subagent_type = tags.get("parent_subagent") or ""

        # tool_use block 合并到前一条 assistant message（同 bubble）
        last_msg = self._messages[-1] if self._messages else None
        if (
            last_msg is not None
            and last_msg.role == "assistant"
            and last_msg.parent_tool_use_id == parent_tool_use_id
        ):
            self._messages[-1] = append_content_block(last_msg, block)
        else:
            msg = make_assistant_message(
                uuid=make_uuid(run_id, seq),
                content=block,
                timestamp=ts,
                parent_tool_use_id=parent_tool_use_id,
                subagent_type=subagent_type,
            )
            self._messages.append(msg)
        self._inflight_tool_use_ids.append(tool_use_id)

        # task tool 调用 → 记栈，子事件挂到这个 id 下
        if tool_name == "task" and not parent_tool_use_id:
            self._subagent_parent_stack.append(tool_use_id)

    def _on_tool_result(self, event: QaAgentEvent) -> None:
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        tags = event.get("tags") or {}
        payload = event.get("payload") or {}
        tool_name = tags.get("name") or payload.get("name") or ""
        output = payload.get("output") or ""
        if not isinstance(output, str):
            output = str(output)

        # tool_use_id 配对：FIFO（最早 inflight 的 tool_call 对应当前 tool_result）
        # LangChain on_tool_start/on_tool_end 在同一线程内严格成对，FIFO 正确
        tool_use_id = ""
        if self._inflight_tool_use_ids:
            tool_use_id = self._inflight_tool_use_ids.pop(0)

        # tool_use 块状态切 done
        if tool_use_id:
            self._update_tool_use_status(tool_use_id, status="done")

        # task tool 结束 → 弹栈
        if tool_name == "task" and self._subagent_parent_stack:
            top = self._subagent_parent_stack[-1]
            if top == tool_use_id:
                self._subagent_parent_stack.pop()

        parent_tool_use_id = self._current_subagent_parent(event)
        subagent_type = tags.get("parent_subagent") or ""

        block = make_tool_result_block(tool_use_id=tool_use_id, output=output, name=tool_name)
        msg = make_user_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
            parent_tool_use_id=parent_tool_use_id,
        )
        # subagent 标记 —— user message 没专门字段，复用 parent_tool_use_id
        # 即可（UI 端按 parent_tool_use_id 折叠）
        self._messages.append(msg)

    def _update_tool_use_status(self, tool_use_id: str, *, status: str) -> None:
        """倒序找到含该 tool_use_id 的 message，原位替换 ContentBlock。"""
        for i in range(len(self._messages) - 1, -1, -1):
            msg = self._messages[i]
            for block in msg.content:
                if (
                    block.type == BLOCK_TOOL_USE
                    and block.tool_use_id == tool_use_id
                ):
                    new_block = ContentBlock(
                        type=block.type,
                        tool_use_id=block.tool_use_id,
                        name=block.name,
                        input=block.input,
                        status=status,
                    )
                    self._messages[i] = replace_content_block(
                        msg,
                        predicate=lambda b: (
                            b.type == BLOCK_TOOL_USE
                            and b.tool_use_id == tool_use_id
                        ),
                        new_block=new_block,
                    )
                    return

    # -- Info (thinking_block / generic info) -------------------------------

    def _on_info(self, event: QaAgentEvent) -> None:
        payload = event.get("payload") or {}
        name = payload.get("name") or ""
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        if name == "thinking_block":
            thinking = payload.get("thinking") or ""
            if not thinking:
                return
            parent_tool_use_id = self._current_subagent_parent(event)
            subagent_type = (event.get("tags") or {}).get("parent_subagent") or ""
            msg = make_assistant_message(
                uuid=make_uuid(run_id, seq),
                content=make_thinking_block(thinking),
                timestamp=ts,
                parent_tool_use_id=parent_tool_use_id,
                subagent_type=subagent_type,
            )
            self._messages.append(msg)
        # 其他 info 暂不入 messages（避免噪声；如需可加分支）

    # -- Payload block (phase / evidence / finding) -------------------------

    def _on_payload_block(self, event: QaAgentEvent, block_type: str) -> None:
        payload = event.get("payload") or {}
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""

        # phase_marker 单独处理：payload.phase 直接当字段
        if block_type == BLOCK_PHASE_MARKER:
            phase = payload.get("phase") or payload.get("event") or ""
            block = make_payload_block(BLOCK_PHASE_MARKER, {"phase": phase})
        else:
            block = make_payload_block(block_type, payload)

        msg = make_system_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
        )
        self._messages.append(msg)

    # -- HIL -----------------------------------------------------------------

    def _on_hil_request(self, event: QaAgentEvent) -> None:
        payload = event.get("payload") or {}
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        block = make_payload_block(
            BLOCK_HIL_REQUEST,
            {k: payload.get(k) for k in _HIL_REQUEST_KEYS},
        )
        msg = make_system_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
        )
        self._messages.append(msg)

    def _on_hil_response(self, event: QaAgentEvent) -> None:
        payload = event.get("payload") or {}
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        block = make_payload_block(BLOCK_HIL_DECISION, dict(payload))
        msg = make_system_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
        )
        self._messages.append(msg)

    # -- Error / warn --------------------------------------------------------

    def _on_error(self, event: QaAgentEvent) -> None:
        payload = event.get("payload") or {}
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        text = ""
        if isinstance(payload, dict):
            text = str(payload.get("error") or payload)
        else:
            text = str(payload)
        block = make_payload_block("error", {"text": text})
        msg = make_system_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
        )
        self._messages.append(msg)

    def _on_warn(self, event: QaAgentEvent) -> None:
        payload = event.get("payload") or {}
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        text = str(payload) if not isinstance(payload, dict) else str(payload)
        block = make_payload_block("warn", {"text": text})
        msg = make_system_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
        )
        self._messages.append(msg)

    # -- Helpers -------------------------------------------------------------

    def _current_subagent_parent(self, event: QaAgentEvent) -> str:
        """带 ``parent_subagent`` tag 的事件返回当前栈顶 task tool_use_id。"""
        tags = event.get("tags") or {}
        if tags.get("parent_subagent"):
            if self._subagent_parent_stack:
                return self._subagent_parent_stack[-1]
        return ""

    def _merge_usage(self, usage: dict[str, Any]) -> None:
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            v = usage.get(key)
            if isinstance(v, int):
                self._usage[key] = self._usage.get(key, 0) + v

    def _notify(self) -> None:
        snap = self.snapshot()
        for cb in list(self._listeners):
            try:
                cb(snap)
            except Exception:  # noqa: BLE001
                logger.exception("MessageReducer listener error")


__all__ = ["MessageReducer"]
