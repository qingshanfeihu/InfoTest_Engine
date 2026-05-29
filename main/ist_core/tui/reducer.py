"""TUI 单源 reducer —— 把 ``IstCoreEvent`` 流翻译成 ``MessageSnapshot``。

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

from main.ist_core.events import IstCoreEvent
from main.ist_core.tui.message_model import (
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





_FORK_SKILLS_CACHE: set[str] | None = None


def _get_fork_skill_names() -> set[str]:
    """运行时发现所有 context: fork 的 skill name（带缓存）。

    空集合不缓存——避免 import 时机过早扫描失败导致永久失效。
    """
    global _FORK_SKILLS_CACHE
    if _FORK_SKILLS_CACHE:
        return _FORK_SKILLS_CACHE
    names: set[str] = set()
    try:
        from pathlib import Path
        from main.ist_core.skills.loader import _parse_skill_md
        skills_dir = Path(__file__).resolve().parents[1] / "skills"
        if skills_dir.is_dir():
            for child in skills_dir.iterdir():
                if not child.is_dir():
                    continue
                skill_md = child / "SKILL.md"
                if not skill_md.exists():
                    continue
                parsed = _parse_skill_md(skill_md)
                if parsed and (parsed["frontmatter"].get("context") or "").strip().lower() == "fork":
                    name = parsed["frontmatter"].get("name") or child.name
                    names.add(name)
    except Exception:  # noqa: BLE001
        pass
    if names:
        _FORK_SKILLS_CACHE = names
    return names


def _is_fork_skill_invocation(input_dict: Mapping[str, Any]) -> bool:
    """检查 qa_invoke_skill 调用是否是 fork skill。

    优先看 input 里 skill 字段（含 raw 字符串包装）。
    """
    if not isinstance(input_dict, Mapping):
        return False
    skill_name = input_dict.get("skill") or ""
    if not skill_name and "raw" in input_dict:
        
        import re
        m = re.search(r"['\"]?skill['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", str(input_dict["raw"]))
        if m:
            skill_name = m.group(1)
    if not isinstance(skill_name, str) or not skill_name:
        return False
    return skill_name in _get_fork_skill_names()


class MessageReducer:
    """订阅 IstCoreEvent → 输出 MessageSnapshot。

    线程模型：bridge 后台线程同步调用 ``dispatch``；订阅回调在同一线程内执行，
    UI 层在回调里负责跨线程投递（``app.call_from_thread``）。reducer 自身不
    关心线程切换。
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._streaming_text: str | None = None
        self._status: str = "idle"
        self._usage: dict[str, int] = {}
        self._llm_phase: str = ""
        self._output_token_count: int = 0

        
        
        
        self._inflight_tool_use_ids: list[str] = []

        
        
        self._tool_run_id_map: dict[str, str] = {}

        
        
        self._subagent_parent_stack: list[str] = []

        self._listeners: list[Callable[[MessageSnapshot], None]] = []
        self._lock = threading.Lock()

    

    def subscribe(self, cb: Callable[[MessageSnapshot], None]) -> None:
        self._listeners.append(cb)

    def snapshot(self) -> MessageSnapshot:
        return MessageSnapshot(
            messages=tuple(self._messages),
            streaming_text=self._streaming_text,
            status=self._status,
            usage=MappingProxyType(dict(self._usage)),
            llm_phase=self._llm_phase,
            output_token_count=self._output_token_count,
        )

    def reset(self) -> None:
        with self._lock:
            self._messages.clear()
            self._streaming_text = None
            self._status = "idle"
            self._usage.clear()
            self._llm_phase = ""
            self._output_token_count = 0
            self._inflight_tool_use_ids.clear()
            self._tool_run_id_map.clear()
            self._subagent_parent_stack.clear()
        self._notify()

    def set_run_status(self, status: str) -> None:
        """外部（bridge）通知 run 完成 / 失败。dispatch 流末尾的 status 切换。"""
        with self._lock:
            self._status = status
        self._notify()

    def dispatch(self, event: IstCoreEvent) -> None:
        kind = event.get("kind") or ""
        try:
            with self._lock:
                self._handle(kind, event)
        except Exception:  # noqa: BLE001
            logger.exception("MessageReducer dispatch error: kind=%s", kind)
        self._notify()

    

    def _handle(self, kind: str, event: IstCoreEvent) -> None:
        if kind == "run_start":
            self._status = "running"
            self._llm_phase = "input"
            self._output_token_count = 0
        elif kind == "run_end":
            self._status = "done"
            self._llm_phase = ""
            self._output_token_count = 0
        elif kind == "run_error":
            self._status = "error"
            self._llm_phase = ""
            self._output_token_count = 0
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
            self._on_llm_start()
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
        elif kind == "todo_list":
            self._on_todo_list(event)
        elif kind == "hil_request":
            self._on_hil_request(event)
        elif kind == "hil_response":
            self._on_hil_response(event)
        

    

    def _on_llm_start(self) -> None:
        """模型调用开始：footer 显示 input 阶段（尚无流式输出 token）。"""
        self._llm_phase = "input"
        self._output_token_count = 0

    def _on_token(self, event: IstCoreEvent) -> None:
        content = (event.get("payload") or {}).get("content") or ""
        if not isinstance(content, str) or not content:
            return
        self._llm_phase = "output"
        self._output_token_count += max(1, len(content) // 4)
        if self._streaming_text is None:
            self._streaming_text = content
        else:
            self._streaming_text = self._streaming_text + content

    

    def _on_llm_end(self, event: IstCoreEvent) -> None:
        payload = event.get("payload") or {}
        name = payload.get("name") or ""
        usage = event.get("usage")
        if isinstance(usage, dict):
            self._merge_usage(usage)

        
        if name == "usage_only":
            return

        content = payload.get("content") or ""
        if not isinstance(content, str):
            content = str(content)

        
        
        if not content or content == "[Calling tools]":
            
            self._streaming_text = None
            self._llm_phase = ""
            self._output_token_count = 0
            return

        
        self._streaming_text = None
        self._llm_phase = ""
        self._output_token_count = 0

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

    

    def _on_tool_call(self, event: IstCoreEvent) -> None:
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

        
        
        msg = make_assistant_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
            parent_tool_use_id=parent_tool_use_id,
            subagent_type=subagent_type,
        )
        self._messages.append(msg)
        self._inflight_tool_use_ids.append(tool_use_id)

        
        
        lc_tool_run_id = tags.get("lc_tool_run_id") or ""
        if lc_tool_run_id:
            self._tool_run_id_map[lc_tool_run_id] = tool_use_id

        
        
        
        if tool_name == "task" and not parent_tool_use_id:
            self._subagent_parent_stack.append(tool_use_id)
        elif (
            tool_name == "qa_invoke_skill"
            and not parent_tool_use_id
            and _is_fork_skill_invocation(input_dict)
        ):
            self._subagent_parent_stack.append(tool_use_id)

    def _on_tool_result(self, event: IstCoreEvent) -> None:
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        tags = event.get("tags") or {}
        payload = event.get("payload") or {}
        tool_name = tags.get("name") or payload.get("name") or ""
        output = payload.get("output") or ""
        if not isinstance(output, str):
            output = str(output)

        
        
        lc_tool_run_id = tags.get("lc_tool_run_id") or ""
        tool_use_id = ""
        if lc_tool_run_id and lc_tool_run_id in self._tool_run_id_map:
            tool_use_id = self._tool_run_id_map.pop(lc_tool_run_id)
            
            if tool_use_id in self._inflight_tool_use_ids:
                self._inflight_tool_use_ids.remove(tool_use_id)
        elif self._inflight_tool_use_ids:
            tool_use_id = self._inflight_tool_use_ids.pop(0)

        
        if tool_use_id:
            self._update_tool_use_status(tool_use_id, status="done")

        
        
        if tool_name in ("task", "qa_invoke_skill") and self._subagent_parent_stack:
            if self._subagent_parent_stack[-1] == tool_use_id:
                self._subagent_parent_stack.pop()
            elif tool_use_id in self._subagent_parent_stack:
                self._subagent_parent_stack.remove(tool_use_id)

        parent_tool_use_id = self._current_subagent_parent(event)
        subagent_type = tags.get("parent_subagent") or ""

        block = make_tool_result_block(tool_use_id=tool_use_id, output=output, name=tool_name)
        msg = make_user_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
            parent_tool_use_id=parent_tool_use_id,
        )
        
        
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

    

    def _on_info(self, event: IstCoreEvent) -> None:
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
        

    

    def _on_payload_block(self, event: IstCoreEvent, block_type: str) -> None:
        payload = event.get("payload") or {}
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""

        
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

    

    def _on_todo_list(self, event: IstCoreEvent) -> None:
        payload = event.get("payload") or {}
        run_id = event.get("run_id") or ""
        seq = event.get("seq") or 0
        ts = event.get("ts") or ""
        todos = payload.get("todos") or []
        block = make_payload_block(BLOCK_TODO_LIST, {"todos": todos})
        msg = make_system_message(
            uuid=make_uuid(run_id, seq),
            content=block,
            timestamp=ts,
        )
        self._messages.append(msg)

    def _on_hil_request(self, event: IstCoreEvent) -> None:
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

    def _on_hil_response(self, event: IstCoreEvent) -> None:
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

    

    def _on_error(self, event: IstCoreEvent) -> None:
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

    def _on_warn(self, event: IstCoreEvent) -> None:
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

    

    def _current_subagent_parent(self, event: IstCoreEvent) -> str:
        """返回当前栈顶 fork tool_use_id（如果在 subagent 内部期间）。

        策略：
        - 优先看事件 tags 的 parent_subagent（LangChain tool callback 传过来）
        - 否则只要栈非空 → 兜底用栈顶（fork 期间所有事件都属于 subagent）
          这覆盖 LangChain 不给 llm_end / info 事件传 metadata 的情况。
        """
        if self._subagent_parent_stack:
            return self._subagent_parent_stack[-1]
        return ""

    def _merge_usage(self, usage: dict[str, Any]) -> None:
        for key in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        ):
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
