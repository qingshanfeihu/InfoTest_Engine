"""review_gate 节点：评审场景的硬闸。

触发信号：主 agent 调过 invoke_skill('test-list-review')
检测目标：invoke_skill(skill='review-verification') 是否被调过 +
  返回的 ToolMessage content 含 VERDICT: + LEVEL: 行
重路由：注入 HumanMessage 提示，state 走 pending → 回 qa_node 重试
retry 上限 2，超限走 failed 写错误 final_answer
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

def review_gate(state: dict[str, Any]) -> dict[str, Any]:
    """review 硬闸节点。

    intent 不是评审场景 → 直接 passed（透传）。
    评审场景 → 检查 verifier 是否真调过 + 给了 VERDICT。
    没调 / 没 VERDICT → 注入提示重路由 qa_node，retry 上限 2。
    """
    msgs = state.get("messages") or []

    if not _has_invoked_review_skill(msgs):
        return {"gate_status": "passed"}

    if _has_verifier_call_with_verdict(msgs):
        return {"gate_status": "passed"}

    retry = (state.get("gate_retry_count") or 0) + 1
    if retry > 2:
        msg = (
            "[gate] 已重试 2 次仍未调 invoke_skill(skill='review-verification') "
            "+ 返回 VERDICT/LEVEL，强制终止。请检查 SKILL.md 是否包含调用指令。"
        )
        logger.warning(msg)
        return {
            "gate_status": "failed",
            "gate_missing_reason": "review-verification 未调用或缺 VERDICT 行",
            "final_answer": msg,
        }

    inject_text = (
        f"[review_gate] You MUST call invoke_skill(skill='review-verification', brief=<full draft>) "
        f"and wait for VERDICT + LEVEL lines before producing the final review. "
        f"Without an explicit VERDICT from the verifier, no review report is "
        f"allowed. After it returns, do NOT call any more tools or add findings. "
        f"Call invoke_skill now. (重试 {retry}/2)"
    )
    return {
        "gate_retry_count": retry,
        "gate_status": "pending",
        "messages": [HumanMessage(content=inject_text)],
    }

def _has_invoked_review_skill(msgs: list) -> bool:
    """触发信号：主 agent 是否调过 invoke_skill('test-list-review')."""
    for m in msgs:
        if not isinstance(m, AIMessage):
            continue
        for tc in (m.tool_calls or []):
            name = (tc.get("name") or "")
            args = tc.get("args") or {}
            if name == "invoke_skill" and args.get("skill") == "test-list-review":
                return True
    return False

def _has_verifier_call_with_verdict(msgs: list) -> bool:
    """检测 invoke_skill(skill='review-verification') + ToolMessage 含 VERDICT."""
    target_tool_use_id = None
    for m in reversed(msgs):
        if not isinstance(m, AIMessage):
            continue
        for tc in (m.tool_calls or []):
            if tc.get("name") != "invoke_skill":
                continue
            args = tc.get("args") or {}
            if args.get("skill") != "review-verification":
                continue
            target_tool_use_id = tc.get("id")
            break
        if target_tool_use_id:
            break

    if not target_tool_use_id:
        return False

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

__all__ = ["review_gate"]
