"""review_gate 节点：评审场景的硬闸（仿 cc-haha hookHelpers.ts 的 Stop hook）.

cc-haha 设计（已读 ``utils/hooks/hookHelpers.ts:70-83`` +
``query/stopHooks.ts:257-267``）::

    addFunctionHook(
        setAppState, sessionId, 'Stop', '',
        messages => hasSuccessfulToolCall(messages, SYNTHETIC_OUTPUT_TOOL_NAME),
        "You MUST call the tool to complete this request. Call this tool now.",
        { timeout: 5000 },
    )

    // stopHooks.ts:257-267：callback 返回 false → 包成 userMessage 推回 messages
    if (result.blockingError) {
        const userMessage = createUserMessage({
            content: getStopHookMessage(result.blockingError),
            isMeta: true,
        })
        blockingErrors.push(userMessage)
        yield userMessage
    }

InfoTest_Engine 落地（LangGraph 等价物）：
- 触发信号：检查主 agent 是否调过 ``qa_invoke_skill('test-case-review')``
  （比 intent 推断更可靠——LLM 已经决定走 review skill 才检查）
- 检测目标：``task(subagent_type='review-verification')`` 是否被调过 +
  返回的 ToolMessage content 含 ``VERDICT:`` + ``LEVEL:`` 行
- 重路由：注入 HumanMessage 提示，state 走 ``pending`` → 回 qa_node 重试
- retry 上限 2，超限走 ``failed`` 写错误 final_answer，**不抛异常**
  （仿 ``stopHooks.ts:456-472`` catch + warning）
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)


def review_gate(state: dict[str, Any]) -> dict[str, Any]:
    """review 硬闸节点。

    ``intent`` 不是评审场景 → 直接 passed（透传）。
    评审场景 → 检查 verifier 是否真调过 + 给了 VERDICT。
    没调 / 没 VERDICT → 注入提示重路由 qa_node，retry 上限 2。
    """
    msgs = state.get("messages") or []

    # 触发信号：主 agent 是否调过 qa_invoke_skill('test-case-review')？
    # 没调过 = 不是评审场景，gate 不激活。
    if not _has_invoked_review_skill(msgs):
        return {"gate_status": "passed"}

    # 评审场景：必须调过 task(review-verification) 且 ToolMessage 含 VERDICT/LEVEL
    if _has_verifier_call_with_verdict(msgs):
        return {"gate_status": "passed"}

    retry = (state.get("gate_retry_count") or 0) + 1
    if retry > 2:
        # 重试上限到——写错误 final_answer 走 finalize（不抛异常，仿 cc-haha
        # stopHooks.ts:456-472 catch + warning）。
        msg = (
            "[gate] 已重试 2 次仍未调 task(subagent_type='review-verification') "
            "+ 返回 VERDICT/LEVEL，强制终止。请检查 SKILL.md 是否包含调用指令、"
            "或主 agent prompt 是否传了完整 brief。"
        )
        logger.warning(msg)
        return {
            "gate_status": "failed",
            "gate_missing_reason": "review-verification 未调用或缺 VERDICT 行",
            "final_answer": msg,
        }

    inject_text = (
        f"[review_gate] You MUST spawn task(subagent_type='review-verification') "
        f"and wait for VERDICT + LEVEL lines before producing the final review. "
        f"Without an explicit VERDICT from the verifier, no review report is "
        f"allowed. Call task now. (重试 {retry}/2)"
    )
    return {
        "gate_retry_count": retry,
        "gate_status": "pending",
        "messages": [HumanMessage(content=inject_text)],
    }


def _has_invoked_review_skill(msgs: list) -> bool:
    """触发信号：扫 messages 看主 agent 是否调过 qa_invoke_skill('test-case-review').

    cc-haha 对照：``utils/messages.ts:4719-4759`` ``hasSuccessfulToolCall(name)``
    模式——只看 tool name 不校验 tool_result 内容。这里也是只看 tool_call args
    不校验 SKILL.md 返回了啥。
    """
    for m in msgs:
        if not isinstance(m, AIMessage):
            continue
        for tc in (m.tool_calls or []):
            name = (tc.get("name") or "")
            args = tc.get("args") or {}
            if name == "qa_invoke_skill" and args.get("skill") == "test-case-review":
                return True
    return False


def _has_verifier_call_with_verdict(msgs: list) -> bool:
    """检测 task(subagent_type='review-verification') 调用 + ToolMessage 含 VERDICT.

    已读 deepagents ``subagents.py:413-418`` 核实：task 工具返回
    ``Command(messages=[ToolMessage(content, tool_call_id)])``，主 agent
    看到的就是这条 ToolMessage，content 是 verifier 最后 AIMessage 的 text。

    流程（仿 cc-haha hasSuccessfulToolCall）：
    1. 倒序找 AIMessage tool_calls 含 ``subagent_type='review-verification'``
    2. 校验 task description（brief）非空且含证据关键字
    3. 找对应 ToolMessage（tool_call_id 匹配），校验 is_error 不为 true
    4. content 含 ``VERDICT:`` + ``LEVEL:``
    """
    target_tool_use_id = None
    for m in reversed(msgs):
        if not isinstance(m, AIMessage):
            continue
        for tc in (m.tool_calls or []):
            if tc.get("name") != "task":
                continue
            args = tc.get("args") or {}
            if args.get("subagent_type") != "review-verification":
                continue
            # 避免 LLM 用空 brief 走过场——description 必须含证据字段
            description = args.get("description") or ""
            if not _looks_like_real_brief(description):
                continue
            target_tool_use_id = tc.get("id")
            break
        if target_tool_use_id:
            break

    if not target_tool_use_id:
        return False

    # 找对应 ToolMessage
    for m in reversed(msgs):
        if not isinstance(m, ToolMessage):
            continue
        if getattr(m, "tool_call_id", None) != target_tool_use_id:
            continue
        if getattr(m, "status", None) == "error":
            return False
        content = m.content if isinstance(m.content, str) else str(m.content)
        return "VERDICT:" in content and "LEVEL:" in content
    return False


def _looks_like_real_brief(description: str) -> bool:
    """避免主 agent 用空 brief 走过场。

    description 必须含证据 / 草稿关键字段。经验值：长度 ≥ 200 字 +
    至少 2 个关键字段 token。

    这是 InfoTest_Engine 自创防御——cc-haha 的 ``description`` 字段没有
    类似校验（cc-haha 靠 Opus 4.7 服从度），qwen / deepseek 服从度低需要
    工程兜底。
    """
    if len(description) < 200:
        return False
    required_tokens = ("test_case_file", "bug_id", "draft_findings")
    matched = sum(1 for tok in required_tokens if tok in description)
    return matched >= 2


__all__ = ["review_gate"]
