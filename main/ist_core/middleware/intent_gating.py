r"""Intent-based tool gating middleware.

在 ToolGatingMiddleware 之后运行，根据用户意图进一步过滤工具列表。
两层过滤叠加：ToolGating（能力域）→ IntentGating（意图 + 置信度）。

三档策略：
- confidence ≥ 0.80：正常 intent 过滤（高置信度）
- 0.50 ≤ confidence < 0.80：保守模式（只保留读/查询工具）
- confidence < 0.50：回退 CHAT 工具集（意图不确定）

默认关。``IST_INTENT_GATING_ENABLED=1`` 开启。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return (os.environ.get("IST_INTENT_GATING_ENABLED") or "0").strip().lower() in (
        "1", "true", "yes",
    )


def _get_last_user_message(messages: list) -> str:
    """从消息列表提取最后一条用户消息文本。"""
    for m in reversed(messages or []):
        mtype = getattr(m, "type", "")
        if mtype == "human":
            content = getattr(m, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, str):
                        return part
                    if isinstance(part, dict) and part.get("type") == "text":
                        return part.get("text", "")
    return ""


class IntentToolGatingMiddleware(AgentMiddleware):
    """根据用户意图 + 置信度动态过滤工具列表。

    三档策略：
    - 高置信度 (≥0.80)：正常 intent 工具过滤
    - 中置信度 [0.50, 0.80)：保守模式，只保留读/查询工具
    - 低置信度 (<0.50)：回退 CHAT 工具集
    """

    def __init__(self) -> None:
        from .intent_router import IntentRouter, Intent
        from .runtime_permission import RuntimeToolPermission

        self._router = IntentRouter()
        self._permission = RuntimeToolPermission()
        self._Intent = Intent

    def _filtered(self, request: ModelRequest) -> ModelRequest:
        if not _enabled():
            return request
        try:
            messages = list(getattr(request, "messages", None) or [])
            user_msg = _get_last_user_message(messages)
            if not user_msg:
                return request

            result = self._router.classify(user_msg)
            if not request.tools:
                return request

            high_threshold = self._router.confidence_threshold_high()
            medium_threshold = self._router.confidence_threshold_medium()

            # 三档策略
            if result.confidence >= high_threshold:
                # 高置信度：正常 intent 过滤
                filtered = self._permission.filter_tools(
                    tools=request.tools,
                    intent=result.intent,
                    agent_type="main",
                )
                strategy = f"intent={result.intent.value}"
            elif result.confidence >= medium_threshold:
                # 中置信度：保守模式
                filtered = self._permission.filter_tools_conservative(
                    tools=request.tools,
                )
                strategy = f"conservative(intent_guess={result.intent.value})"
            else:
                # 低置信度：回退 CHAT 工具集
                filtered = self._permission.filter_tools(
                    tools=request.tools,
                    intent=self._Intent.CHAT,
                    agent_type="main",
                )
                strategy = "fallback_chat"

            if not filtered:
                logger.warning(
                    "IntentGating: %s 过滤后无工具，保留全量 (confidence=%.2f)",
                    strategy, result.confidence,
                )
                return request

            if len(filtered) < len(request.tools):
                logger.info(
                    "IntentGating: %s 保留 %d/%d 工具 (confidence=%.2f, rule=%s)",
                    strategy, len(filtered), len(request.tools),
                    result.confidence, result.matched_rule,
                )

            return request.override(tools=filtered)
        except Exception:
            logger.debug("IntentGating 过滤失败(放行全量)", exc_info=True)
            return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._filtered(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._filtered(request))
