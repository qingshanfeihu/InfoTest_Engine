"""TUI 单源数据模型 —— messages[] / streamingText。

设计原则：

1. **Message** 是 conversation 的最小单元，按 ``uuid`` 做 keyed reconciliation。

2. **ContentBlock** 联合多种 block type（text / tool_use / tool_result / thinking
   及 IST-Core 特有的 phase_marker / evidence / finding / todo_list / hil_*），
   sub-agent 内部事件靠 ``parent_tool_use_id`` 扁平挂载。

3. **MessageSnapshot** 是 reducer 一次性输出的不可变状态——``frozen=True`` +
   ``tuple[...]``，确保 UI 端读到的永远是一致快照，不会撞到中间态。

把这层模型独立成 module 而不是塞回 events.py：events 是底层传输协议（kind/seq/ts），
message_model 是 UI 渲染契约，两者解耦避免后续 sink 重构互相牵扯。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


_EMPTY_MAP: Mapping[str, Any] = MappingProxyType({})






BLOCK_TEXT = "text"

BLOCK_THINKING = "thinking"

BLOCK_TOOL_USE = "tool_use"

BLOCK_TOOL_RESULT = "tool_result"

BLOCK_PHASE_MARKER = "phase_marker"

BLOCK_EVIDENCE = "evidence"
BLOCK_FINDING = "finding"

BLOCK_TODO_LIST = "todo_list"

BLOCK_HIL_REQUEST = "hil_request"
BLOCK_HIL_DECISION = "hil_decision"

BLOCK_ASK_USER = "ask_user"


@dataclass(frozen=True)
class ContentBlock:
    """统一 ContentBlock —— 字段并集，按 ``type`` 取值。

    所有 dict / list 字段必须传入只读 ``MappingProxyType`` 包装，否则 frozen 不一致。
    用 ``make_text_block`` / ``make_tool_use_block`` 等工厂函数构造比直接 dataclass
    构造更安全。
    """

    type: str
    
    text: str = ""
    thinking: str = ""
    
    tool_use_id: str = ""
    name: str = ""
    input: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_MAP)
    status: str = ""
    
    output: str = ""
    is_error: bool = False
    
    payload: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_MAP)


@dataclass(frozen=True)
class Message:
    """对话最小单元。

    - ``uuid``: ``f"{run_id}:{seq}"`` 由 reducer 生成；同 uuid 二次出现 = in-place
      更新（keyed reconciliation）。
    - ``role``: "user" / "assistant" / "system"。phase_marker / evidence / finding
      等非对话事件统一归 ``system``。
    - ``parent_tool_use_id``: subagent 内部事件挂载——主 agent 调 ``task`` tool 时
      reducer 记录 tool_use_id，后续带 ``parent_subagent`` tag 的事件写到这个字段，
      Transcript 渲染时按它折叠成子树。
    """

    uuid: str
    role: str
    content: tuple[ContentBlock, ...]
    timestamp: str = ""
    parent_tool_use_id: str = ""
    subagent_type: str = ""


@dataclass(frozen=True)
class MessageSnapshot:
    """Reducer 一次性输出的不可变状态。

    UI 订阅者拿到这个对象就能完整渲染当前 transcript——不需要回调里再去 reducer
    取数。``frozen=True + tuple`` 确保跨线程投递时不会撞到中间态。
    """

    messages: tuple[Message, ...]
    streaming_text: str | None = None
    streaming_tool_uses: tuple[ContentBlock, ...] = ()
    status: str = "idle"
    usage: Mapping[str, int] = field(default_factory=lambda: _EMPTY_MAP)
    llm_phase: str = ""
    output_token_count: int = 0
    run_end_info: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_MAP)







def make_uuid(run_id: str, seq: int | str) -> str:
    """生成 message uuid。

    格式 ``{run_id}:{seq}``——只要在一次 run 内保证唯一即可。run_id 由 EventBus
    单调，seq 由 itertools.count 单调，组合天然唯一。
    """
    return f"{run_id}:{seq}"


def make_text_block(text: str) -> ContentBlock:
    return ContentBlock(type=BLOCK_TEXT, text=text)


def make_thinking_block(thinking: str) -> ContentBlock:
    return ContentBlock(type=BLOCK_THINKING, thinking=thinking)


def make_tool_use_block(
    *,
    tool_use_id: str,
    name: str,
    input: Mapping[str, Any] | dict[str, Any] | None = None,
    status: str = "running",
) -> ContentBlock:
    return ContentBlock(
        type=BLOCK_TOOL_USE,
        tool_use_id=tool_use_id,
        name=name,
        input=MappingProxyType(dict(input or {})),
        status=status,
    )


def make_tool_result_block(
    *,
    tool_use_id: str,
    output: str,
    is_error: bool = False,
    name: str = "",
) -> ContentBlock:
    return ContentBlock(
        type=BLOCK_TOOL_RESULT,
        tool_use_id=tool_use_id,
        output=output,
        is_error=is_error,
        name=name,
    )


def make_payload_block(
    type: str,
    payload: Mapping[str, Any] | dict[str, Any] | None = None,
) -> ContentBlock:
    return ContentBlock(
        type=type,
        payload=MappingProxyType(dict(payload or {})),
    )


def make_assistant_message(
    *,
    uuid: str,
    content: ContentBlock | list[ContentBlock] | tuple[ContentBlock, ...],
    timestamp: str = "",
    parent_tool_use_id: str = "",
    subagent_type: str = "",
) -> Message:
    if isinstance(content, ContentBlock):
        content_tuple: tuple[ContentBlock, ...] = (content,)
    else:
        content_tuple = tuple(content)
    return Message(
        uuid=uuid,
        role="assistant",
        content=content_tuple,
        timestamp=timestamp,
        parent_tool_use_id=parent_tool_use_id,
        subagent_type=subagent_type,
    )


def make_user_message(
    *,
    uuid: str,
    content: ContentBlock | list[ContentBlock] | tuple[ContentBlock, ...],
    timestamp: str = "",
    parent_tool_use_id: str = "",
) -> Message:
    if isinstance(content, ContentBlock):
        content_tuple: tuple[ContentBlock, ...] = (content,)
    else:
        content_tuple = tuple(content)
    return Message(
        uuid=uuid,
        role="user",
        content=content_tuple,
        timestamp=timestamp,
        parent_tool_use_id=parent_tool_use_id,
    )


def make_system_message(
    *,
    uuid: str,
    content: ContentBlock | list[ContentBlock] | tuple[ContentBlock, ...],
    timestamp: str = "",
) -> Message:
    if isinstance(content, ContentBlock):
        content_tuple: tuple[ContentBlock, ...] = (content,)
    else:
        content_tuple = tuple(content)
    return Message(
        uuid=uuid,
        role="system",
        content=content_tuple,
        timestamp=timestamp,
    )







def replace_content_block(
    msg: Message, *, predicate, new_block: ContentBlock
) -> Message:
    """构造新 Message，把 content 中 predicate(block) 命中的位置替换为 new_block。

    用于 tool_use 状态切换 running → done：拿到原 message 后用本函数生成新 tuple，
    再整体替换 reducer._messages 对应位置。frozen dataclass 的标准用法。
    """
    new_content: list[ContentBlock] = []
    for block in msg.content:
        if predicate(block):
            new_content.append(new_block)
        else:
            new_content.append(block)
    return Message(
        uuid=msg.uuid,
        role=msg.role,
        content=tuple(new_content),
        timestamp=msg.timestamp,
        parent_tool_use_id=msg.parent_tool_use_id,
        subagent_type=msg.subagent_type,
    )


def append_content_block(msg: Message, block: ContentBlock) -> Message:
    """在 message.content 末尾追加 block，返回新 frozen Message。"""
    return Message(
        uuid=msg.uuid,
        role=msg.role,
        content=msg.content + (block,),
        timestamp=msg.timestamp,
        parent_tool_use_id=msg.parent_tool_use_id,
        subagent_type=msg.subagent_type,
    )


__all__ = [
    "ContentBlock",
    "Message",
    "MessageSnapshot",
    "BLOCK_TEXT",
    "BLOCK_THINKING",
    "BLOCK_TOOL_USE",
    "BLOCK_TOOL_RESULT",
    "BLOCK_PHASE_MARKER",
    "BLOCK_EVIDENCE",
    "BLOCK_FINDING",
    "BLOCK_TODO_LIST",
    "BLOCK_HIL_REQUEST",
    "BLOCK_HIL_DECISION",
    "BLOCK_ASK_USER",
    "make_uuid",
    "make_text_block",
    "make_thinking_block",
    "make_tool_use_block",
    "make_tool_result_block",
    "make_payload_block",
    "make_assistant_message",
    "make_user_message",
    "make_system_message",
    "replace_content_block",
    "append_content_block",
]
