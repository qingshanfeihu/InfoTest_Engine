"""测试 review_gate 节点（Step 4 硬闸节点）.

覆盖场景：
1. 非评审场景（没调过 invoke_skill）→ passed 透传
2. 评审场景 + verifier 没调 → pending 重路由 + retry+1
3. 评审场景 + verifier 调了但无 VERDICT → pending 重路由
4. 评审场景 + verifier 调了 + VERDICT/LEVEL 齐 → passed
5. 重试上限（retry > 2）→ failed 写错误 final_answer
6. 主 agent 用空 brief 走过场（_looks_like_real_brief 校验失败）→ pending

参考实现：``hookHelpers.ts:70-83`` registerStructuredOutputEnforcement
+ ``stopHooks.ts:257-267`` blocking error → userMessage 重路由。
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from main.ist_core.nodes.review_gate import (
    _has_invoked_review_skill,
    _has_verifier_call_with_verdict,
    review_gate,
)







def _make_invoke_skill_msg() -> AIMessage:
    """主 agent 调 invoke_skill('test-list-review') 的 AIMessage."""
    return AIMessage(
        content="我来调 review skill",
        tool_calls=[
            {
                "name": "invoke_skill",
                "args": {"skill": "test-list-review"},
                "id": "skill_call_1",
                "type": "tool_call",
            }
        ],
    )


def _real_brief() -> str:
    """合规的 review-verification brief（含证据字段且 ≥ 200 字）."""
    return (
        "test_case_file: knowledge/data/markdown/qa/121100_cookie.md\n"
        "bug_id: BUG-121100\n"
        "bug_summary: cookie 加密功能新增 enc_name/enc_ip/smode/passwd 参数\n"
        "cli_command: slb mode ircookie\n"
        "evidence_collected: [Phase 1 kb_bug_search 结果, Phase 2 grep product/]\n"
        "draft_findings: [Segment WebUI 100% 重复, smode 缺口, 密码强度负面缺]\n"
        "draft_level: P4\n\n"
        "Independently verify each finding. Try to break my draft."
    )


def _make_verifier_call_msg(brief: str = None, tool_call_id: str = "task_1") -> AIMessage:
    """主 agent 调 invoke_skill('review-verification') 的 AIMessage."""
    return AIMessage(
        content="提交给 verifier",
        tool_calls=[
            {
                "name": "invoke_skill",
                "args": {
                    "skill": "review-verification",
                    "brief": brief if brief is not None else _real_brief(),
                },
                "id": tool_call_id,
                "type": "tool_call",
            }
        ],
    )


def _make_verifier_response(
    has_verdict: bool = True, tool_call_id: str = "task_1"
) -> ToolMessage:
    """verifier 返回的 ToolMessage（task 工具透传 subagent 输出）."""
    if has_verdict:
        content = (
            "### Check 1: smode 缺口\n"
            "**Source:** 草稿 finding #2\n"
            "**Verification command:** grep smode file.md\n"
            "**Output observed:** (no matches)\n"
            "**Result: PASS** (P3, gap confirmed)\n\n"
            "VERDICT: PARTIAL\n"
            "LEVEL: P3"
        )
    else:
        content = "I think the draft is mostly fine, no verdict given."
    return ToolMessage(content=content, tool_call_id=tool_call_id, name="task")







def test_gate_passes_when_no_review_skill_invoked():
    """非评审场景（没调过 invoke_skill）→ passed 透传."""
    state = {"messages": [HumanMessage(content="一般 QA 问题")]}
    result = review_gate(state)
    assert result["gate_status"] == "passed"
    assert "messages" not in result


def test_gate_pending_when_verifier_not_called():
    """评审场景 + verifier 没调 → pending 重路由."""
    msgs = [HumanMessage(content="评审 BUG-121100"), _make_invoke_skill_msg()]
    state = {"messages": msgs}
    result = review_gate(state)
    assert result["gate_status"] == "pending"
    assert result["gate_retry_count"] == 1
    assert "messages" in result
    inject = result["messages"][0]
    assert isinstance(inject, HumanMessage)
    assert "review-verification" in inject.content
    assert "重试 1/2" in inject.content


def test_gate_pending_when_verifier_called_no_verdict():
    """评审场景 + verifier 调了但 ToolMessage 无 VERDICT → pending."""
    msgs = [
        HumanMessage(content="评审 BUG-121100"),
        _make_invoke_skill_msg(),
        _make_verifier_call_msg(),
        _make_verifier_response(has_verdict=False),
    ]
    state = {"messages": msgs}
    result = review_gate(state)
    assert result["gate_status"] == "pending"


def test_gate_passed_when_verifier_returned_verdict():
    """评审场景 + VERDICT/LEVEL 齐 → passed."""
    msgs = [
        HumanMessage(content="评审 BUG-121100"),
        _make_invoke_skill_msg(),
        _make_verifier_call_msg(),
        _make_verifier_response(has_verdict=True),
    ]
    state = {"messages": msgs}
    result = review_gate(state)
    assert result["gate_status"] == "passed"


def test_gate_failed_when_retry_exceeds_limit():
    """重试 > 2 → failed 写错误 final_answer，不抛异常."""
    msgs = [HumanMessage(content="评审 BUG-121100"), _make_invoke_skill_msg()]
    state = {"messages": msgs, "gate_retry_count": 2}
    result = review_gate(state)
    assert result["gate_status"] == "failed"
    assert "已重试 2 次" in result["final_answer"]
    assert "final_answer" in result


def test_gate_passed_with_short_brief_when_verdict_present():
    """主 agent 用短 brief 调 verifier，verifier 仍然给了 VERDICT —— gate 应放行.

    设计修订（实测对齐参考实现 simplify.ts 风格）：review_gate 不校验 brief
    长度——参考实现同类设计同样不校验，且实测发现校验门槛会误拒 verifier
    实际成功的调用。review_gate 的职责仅是确认 verifier 真给了 verdict。

    短 brief 反偷懒靠主 agent system prompt 的 "Writing the prompt for task
    calls" 段约束（参考 tools/AgentTool/prompt.ts），不靠 review_gate。
    """
    empty_brief = "评审 BUG-121100 cookie 用例"
    msgs = [
        HumanMessage(content="评审 BUG-121100"),
        _make_invoke_skill_msg(),
        _make_verifier_call_msg(brief=empty_brief),
        _make_verifier_response(has_verdict=True),
    ]
    state = {"messages": msgs}
    result = review_gate(state)
    
    assert result["gate_status"] == "passed"







def test_has_invoked_review_skill_detects_call():
    msgs = [_make_invoke_skill_msg()]
    assert _has_invoked_review_skill(msgs) is True


def test_has_invoked_review_skill_returns_false_when_skill_is_other():
    msgs = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "invoke_skill",
                    "args": {"skill": "other-skill"},
                    "id": "x",
                    "type": "tool_call",
                }
            ],
        )
    ]
    assert _has_invoked_review_skill(msgs) is False


def test_has_verifier_call_returns_false_when_tool_result_is_error():
    """ToolMessage status='error' 不算成功调用."""
    msgs = [
        _make_invoke_skill_msg(),
        _make_verifier_call_msg(),
        ToolMessage(
            content="task failed", tool_call_id="task_1", name="task", status="error"
        ),
    ]
    assert _has_verifier_call_with_verdict(msgs) is False
