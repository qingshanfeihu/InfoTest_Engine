r"""Intent → Skill 强制路由中间件。

当 IntentRouter 高置信度识别到特定意图时，注入 system-reminder
强制 agent 调用对应 skill，而不是自行处理。

模式与 PerTurnSkillReminderMiddleware 一致：
- wrap_model_call 修改 ModelRequest.messages（不持久化到 state）
- 注入 system-reminder 标签的 HumanMessage（离 reasoning context 最近）

默认关。``IST_INTENT_ROUTING_ENABLED=1`` 开启。
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
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# Intent → Skill 强制路由表
# 置信度阈值：≥ 此值时注入强制指令
_INTENT_SKILL_ROUTES: dict[str, tuple[str, float]] = {
    "CREATE_DOCUMENT": ("doc-authoring", 0.70),
    "GENERATE_REPORT": ("report-gen", 0.70),
}

# 强制路由指令模板
_ROUTE_DIRECTIVE = """<system-reminder>
INTENT ROUTING DIRECTIVE (BLOCKING REQUIREMENT):
The user's message has been classified as intent: {intent} (confidence: {confidence:.0%}).

You MUST call invoke_skill("{skill}") with the user's full message as the brief — IMMEDIATELY, as your FIRST action.

Do NOT:
- Read files yourself
- Write files yourself
- Run Python/shell yourself
- Answer the question directly
- Do any preparatory work

The skill handles everything internally. Just call invoke_skill and return the result.
</system-reminder>"""


def _enabled() -> bool:
    return (os.environ.get("IST_INTENT_ROUTING_ENABLED") or "0").strip().lower() in (
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


class IntentRoutingMiddleware(AgentMiddleware):
    """Intent → Skill 强制路由。

    高置信度识别到特定意图时，注入 system-reminder 强制 agent 调用对应 skill。
    与 IntentToolGatingMiddleware（工具过滤）互补：一个管工具，一个管行为。
    """

    def __init__(self) -> None:
        from .intent_router import IntentRouter

        self._router = IntentRouter()

    def _maybe_inject(self, request: ModelRequest) -> ModelRequest:
        if not _enabled():
            return request

        try:
            messages = list(getattr(request, "messages", None) or [])
            user_msg = _get_last_user_message(messages)
            if not user_msg:
                return request

            result = self._router.classify(user_msg)

            route = _INTENT_SKILL_ROUTES.get(result.intent.value)
            if not route:
                return request

            skill, threshold = route
            if result.confidence < threshold:
                return request

            # 检查是否已经在 skill 执行中（避免重复注入）
            # 如果最近的 tool_call 已经是 invoke_skill，不注入
            for m in reversed(messages):
                mtype = getattr(m, "type", "")
                if mtype == "ai":
                    for tc in (getattr(m, "tool_calls", None) or []):
                        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                        if name == "invoke_skill":
                            return request  # 已在 skill 中，不注入
                    break

            # 注入强制路由指令
            directive = _ROUTE_DIRECTIVE.format(
                intent=result.intent.value,
                confidence=result.confidence,
                skill=skill,
            )

            new_messages = messages + [HumanMessage(content=directive)]
            logger.info(
                "IntentRouting: intent=%s confidence=%.2f → 强制路由到 skill=%s",
                result.intent.value, result.confidence, skill,
            )
            return request.override(messages=new_messages)

        except Exception:
            logger.debug("IntentRouting 失败(放行)", exc_info=True)
            return request

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._maybe_inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._maybe_inject(request))
