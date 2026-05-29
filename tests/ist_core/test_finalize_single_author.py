"""finalize（对齐 Anthropic 官方）：直接透传主 agent 的 final_answer。

新设计：fork verifier 完整 result 只通过 ToolResult 给主 agent；
主 agent 负责复述内容给用户。finalize 仅剥离 VERDICT/LEVEL 行。
"""

from __future__ import annotations

from main.ist_core.graph import _strip_verdict_lines, finalize


def _main_agent_relayed_report() -> str:
    """模拟主 agent 复述的完整报告。"""
    return "完整评审\n" + "x" * 2000 + "\nVERDICT: FAIL\nLEVEL: P2\n"


def test_finalize_passes_main_agent_answer_through():
    """finalize 直接透传主 agent 的 final_answer，仅剥离 VERDICT/LEVEL 行。"""
    answer = _main_agent_relayed_report()
    state = {
        "gate_status": "passed",
        "final_answer": answer,
        "messages": [],
    }
    out = finalize(state)
    
    assert out["final_answer"] == _strip_verdict_lines(answer)
    
    assert "VERDICT:" not in out["final_answer"]
    assert "LEVEL:" not in out["final_answer"]
    
    assert "完整评审" in out["final_answer"]


def test_finalize_does_not_inject_tool_message_content():
    """finalize 不再从 messages 提取 verifier ToolMessage 当 final_answer。

    对齐 Anthropic 官方：fork 内部 result 不直接 leak 给用户，
    必须由主 agent 复述。
    """
    state = {
        "gate_status": "passed",
        "final_answer": "短总结",
        "messages": [],
    }
    out = finalize(state)
    assert out["final_answer"] == "短总结"


def test_finalize_strips_verdict_and_level():
    """剥离逻辑保留：gate 已检测过，final_answer 不需要保留这两行。"""
    answer = "正文\n\nVERDICT: PASS\nLEVEL: P3\n"
    state = {"final_answer": answer, "messages": []}
    out = finalize(state)
    assert "VERDICT" not in out["final_answer"]
    assert "LEVEL" not in out["final_answer"]
    assert "正文" in out["final_answer"]
