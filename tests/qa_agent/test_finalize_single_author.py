"""finalize：评审通过时 final_answer 仅 verifier，不叠 main 补刀."""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from main.qa_agent.graph import finalize


def _verifier_report() -> str:
    return "完整评审\n" + "x" * 2000 + "\nVERDICT: FAIL\nLEVEL: P2\n"


def test_finalize_uses_verifier_only_when_gate_passed():
    tool_id = "call_verifier_1"
    msgs = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": tool_id,
                    "name": "task",
                    "args": {"subagent_type": "review-verification"},
                }
            ],
        ),
        ToolMessage(content=_verifier_report(), tool_call_id=tool_id),
    ]
    state = {
        "gate_status": "passed",
        "final_answer": "main 补刀 smode 段落不应出现在 final_answer",
        "messages": msgs,
    }
    out = finalize(state)
    assert out["final_answer"] == _verifier_report()
    assert "smode" not in out["final_answer"]


def test_finalize_keeps_main_when_already_relayed():
    relayed = _verifier_report()
    state = {
        "gate_status": "passed",
        "final_answer": relayed,
        "messages": [],
    }
    out = finalize(state)
    assert out["final_answer"] == relayed
