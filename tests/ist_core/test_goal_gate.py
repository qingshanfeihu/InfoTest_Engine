"""goal_gate 守护测试：/goal 自治循环的确定性逻辑（评判器 mock 掉，不打 LLM）。

覆盖：opt-in 透传 / kill switch / 达成停 / 未达成注入反馈回流 / 超上限如实停。
"""

from __future__ import annotations

import importlib

from langchain_core.messages import HumanMessage

goal_gate_mod = importlib.import_module("main.ist_core.nodes.goal_gate")
goal_gate = goal_gate_mod.goal_gate


def _patch_eval(monkeypatch, met: bool, reason: str = "差一点"):
    monkeypatch.setattr(goal_gate_mod, "_evaluate_goal",
                        lambda goal, msgs: {"met": met, "reason": reason})


def test_no_goal_is_inactive_passthrough(monkeypatch):
    """没 goal_text → inactive 透传（现有行为不变，绝不调评判器）。"""
    called = {"n": 0}
    monkeypatch.setattr(goal_gate_mod, "_evaluate_goal",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {"met": False})
    out = goal_gate({"messages": []})
    assert out == {"goal_status": "inactive"}
    assert called["n"] == 0  # 没目标绝不评判


def test_kill_switch_disables(monkeypatch):
    """IST_GOAL_ENABLED=0 → 即便有 goal 也 inactive。"""
    monkeypatch.setenv("IST_GOAL_ENABLED", "0")
    _patch_eval(monkeypatch, met=False)
    out = goal_gate({"goal_text": "上机全过", "messages": []})
    assert out == {"goal_status": "inactive"}


def test_goal_met_stops(monkeypatch):
    monkeypatch.setenv("IST_GOAL_ENABLED", "1")
    _patch_eval(monkeypatch, met=True, reason="全 pass")
    out = goal_gate({"goal_text": "上机全过", "messages": []})
    assert out["goal_status"] == "met"
    assert "messages" not in out  # 达成不注入


def test_goal_unmet_injects_and_loops(monkeypatch):
    monkeypatch.setenv("IST_GOAL_ENABLED", "1")
    _patch_eval(monkeypatch, met=False, reason="还有 5 个 fail")
    out = goal_gate({"goal_text": "上机全过", "messages": [], "goal_retry_count": 0})
    assert out["goal_status"] == "unmet"
    assert out["goal_retry_count"] == 1
    msgs = out["messages"]
    assert len(msgs) == 1 and isinstance(msgs[0], HumanMessage)
    assert "还有 5 个 fail" in msgs[0].content
    assert "dev_run_batch" in msgs[0].content  # 强调要基于真实结果


def test_exhausted_stops_honestly(monkeypatch):
    """retry 超上限 → exhausted + final_answer，如实停（不假装完成）。"""
    monkeypatch.setenv("IST_GOAL_ENABLED", "1")
    monkeypatch.setenv("IST_GOAL_MAX_ROUNDS", "3")
    _patch_eval(monkeypatch, met=False, reason="仍有 fail")
    out = goal_gate({"goal_text": "上机全过", "messages": [], "goal_retry_count": 3})
    assert out["goal_status"] == "exhausted"
    assert "未达成" in out["final_answer"]
    assert "messages" not in out  # 不再回流


def test_max_rounds_default_and_env(monkeypatch):
    monkeypatch.delenv("IST_GOAL_MAX_ROUNDS", raising=False)
    assert goal_gate_mod._max_rounds() == 8
    monkeypatch.setenv("IST_GOAL_MAX_ROUNDS", "4")
    assert goal_gate_mod._max_rounds() == 4
    monkeypatch.setenv("IST_GOAL_MAX_ROUNDS", "garbage")
    assert goal_gate_mod._max_rounds() == 8


def test_evaluate_requires_tool_evidence_not_just_claim(monkeypatch):
    """评判器判达成,但近况只有 AI 口头声称、无任何 ToolMessage → 守护改判未达成（防轻信）。"""
    from langchain_core.messages import AIMessage, ToolMessage

    class _FakeModel:
        def invoke(self, msgs):
            return AIMessage(content='{"met": true, "reason": "全部通过"}')

    import main.ist_core.agents._llm as llm
    monkeypatch.setattr(llm, "build_explore_model", lambda **k: _FakeModel())
    # 只有 AI 声称、无工具返回 → 改判未达成
    v = goal_gate_mod._evaluate_goal("上机全过", [AIMessage(content="我已修好,全部通过 PASS")])
    assert v["met"] is False
    # 有 ToolMessage(工具真实返回)→ 放行 met=True
    v2 = goal_gate_mod._evaluate_goal(
        "上机全过",
        [ToolMessage(content="44/44 pass 0 fail", tool_call_id="t1"), AIMessage(content="done")],
    )
    assert v2["met"] is True


def test_evaluator_error_is_failsafe_met(monkeypatch):
    """评判器异常 → 失败安全放行（met=True），不把 agent 困死。"""
    monkeypatch.setenv("IST_GOAL_ENABLED", "1")

    def _boom(goal, msgs):
        raise RuntimeError("model down")
    # 这里测真 _evaluate_goal 的异常分支：让 build_explore_model 抛错
    monkeypatch.setattr(goal_gate_mod, "_evaluate_goal", goal_gate_mod._evaluate_goal)
    import main.ist_core.agents._llm as llm
    monkeypatch.setattr(llm, "build_explore_model", lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
    out = goal_gate({"goal_text": "上机全过", "messages": []})
    assert out["goal_status"] == "met"  # 失败安全
