"""消息序列消毒 middleware(2026-07-05,dongkl 重测轮取证)。

事故:ask_user 类工具调用被 turn 截断后,checkpoint 历史里留下「带 tool_calls 的
AIMessage 后面没有对应 ToolMessage」——OpenAI 兼容供应商对这种序列一律 400
(An assistant message with 'tool_calls' must be followed by tool messages…),
错误被上层吞成「零响应」,会话从此每轮 400、发消息救不回(死锁态)。

修复:每次模型调用前扫描消息副本,给悬空的 tool_call 现场补一条合成 ToolMessage
(标注被截断,LLM 可据此决定重发)。与 loop_guard 同款纪律:只改本次调用的消息
视图,不写回 state——checkpoint 原样,消毒是幂等的每轮前处理。
``IST_MSG_SANITIZE=0`` 关。
"""

from __future__ import annotations

import logging
import os
from typing import Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)

logger = logging.getLogger(__name__)

_STUB = ("[工具调用被会话截断,未产生结果。这是框架补的占位回应——"
         "该调用没有执行,如果它仍然必要,重新发起。]")


def _enabled() -> bool:
    return (os.environ.get("IST_MSG_SANITIZE") or "1").strip().lower() not in ("0", "false", "no")


def sanitize_messages(messages: list) -> list:
    """返回消毒后的列表;无悬空时原对象原样返回(零开销路径)。

    规则(对齐 OpenAI 序列约束):AIMessage.tool_calls 里的每个 id,必须在
    **下一段连续的 tool 消息**里有对应回应;缺的现场补合成 ToolMessage。
    """
    out = None
    i = 0
    n = len(messages)
    while i < n:
        m = messages[i]
        calls = getattr(m, "tool_calls", None) or []
        if getattr(m, "type", "") != "ai" or not calls:
            i += 1
            continue
        answered = set()
        j = i + 1
        while j < n and getattr(messages[j], "type", "") == "tool":
            tcid = getattr(messages[j], "tool_call_id", None)
            if tcid:
                answered.add(tcid)
            j += 1
        missing = [c for c in calls
                   if str(c.get("id") if isinstance(c, dict) else getattr(c, "id", "")) not in answered]
        if missing:
            from langchain_core.messages import ToolMessage
            if out is None:
                out = list(messages)
            stubs = []
            for c in missing:
                cid = str(c.get("id") if isinstance(c, dict) else getattr(c, "id", "")) or "unknown"
                cname = str((c.get("name") if isinstance(c, dict) else getattr(c, "name", "")) or "tool")
                stubs.append(ToolMessage(content=_STUB, name=cname, tool_call_id=cid))
            # 插进 out(注意 out 与 messages 同长时索引一致;多轮插入用偏移)
            offset = len(out) - n
            insert_at = j + offset
            out[insert_at:insert_at] = stubs
            logger.warning("message_sanitize: 补 %d 条悬空 tool_call 回应(idx=%d)", len(stubs), i)
        i = j if j > i + 1 else i + 1
    return out if out is not None else messages


class MessageSanitizeMiddleware(AgentMiddleware):
    """悬空 tool_calls 消毒——防截断历史把会话锁死在供应商 400。"""

    def _fixed(self, request: ModelRequest) -> ModelRequest:
        if not _enabled():
            return request
        try:
            msgs = list(getattr(request, "messages", None) or [])
            out = sanitize_messages(msgs)
            if out is msgs:
                return request
            return request.override(messages=out)
        except Exception:  # noqa: BLE001 — 消毒绝不挂主流程
            logger.debug("message_sanitize 失败(放行原文)", exc_info=True)
            return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._fixed(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._fixed(request))
