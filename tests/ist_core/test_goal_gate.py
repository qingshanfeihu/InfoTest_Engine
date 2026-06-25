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


def test_evaluator_error_is_conservative_unmet(monkeypatch):
    """评判器异常 → 保守判未达成（不在『误判达成提前收手』这个危险方向 fail-open）；
    受 retry 上限兜底不困死，故回流继续而非停。"""
    monkeypatch.setenv("IST_GOAL_ENABLED", "1")
    monkeypatch.delenv("IST_GOAL_MAX_ROUNDS", raising=False)
    # 测真 _evaluate_goal 的异常分支：让 build_explore_model 抛错
    import main.ist_core.agents._llm as llm
    monkeypatch.setattr(llm, "build_explore_model", lambda **k: (_ for _ in ()).throw(RuntimeError("down")))
    out = goal_gate({"goal_text": "上机全过", "messages": [], "goal_retry_count": 0})
    assert out["goal_status"] == "unmet"  # 保守：异常绝不放行成达成
    assert out["goal_retry_count"] == 1   # 回流继续，受 max_rounds 兜底不困死


# ── _parse_verdict 解析鲁棒性（裁判唯一危险方向=误判达成，故不确定一律默认未达成）──────────

def test_parse_verdict_clean_json():
    assert goal_gate_mod._parse_verdict('{"met": true, "reason": "44/44 pass"}')["met"] is True
    assert goal_gate_mod._parse_verdict('{"met": false, "reason": "还差3个"}')["met"] is False


def test_parse_verdict_markdown_fenced():
    raw = '这是结论：\n```json\n{"met": true, "reason": "全 pass"}\n```'
    assert goal_gate_mod._parse_verdict(raw)["met"] is True


def test_parse_verdict_restated_goal_substring_not_misread():
    """模型明说未达成、但散文里含 `"met": true` 子串（复述目标）→ 不得误判达成（旧子串兜底的 bug）。"""
    raw = '目标是让所有 "met": true 的用例通过，但实际还差3个。结论：{"met": false, "reason": "还差3个"}'
    assert goal_gate_mod._parse_verdict(raw)["met"] is False


def test_parse_verdict_multi_block_takes_last_conclusion():
    """举例块 {met:true} + 末尾结论块 {met:false} → 取末块结论=未达成（旧贪婪正则会跨块解析失败再误判）。"""
    raw = '举例：全过就是 {"met": true}。但实测还有2个fail，最终：{"met": false, "reason": "还差MX和引号"}'
    assert goal_gate_mod._parse_verdict(raw)["met"] is False


def test_parse_verdict_garbage_defaults_unmet():
    """抽不到含 met 的合法 JSON（纯文本/裸 true/yes/截断 JSON）→ 一律保守判未达成。"""
    assert goal_gate_mod._parse_verdict("YES 我觉得全过了")["met"] is False
    assert goal_gate_mod._parse_verdict("true")["met"] is False
    assert goal_gate_mod._parse_verdict('{"met": false')["met"] is False  # 截断、无闭括号
    assert goal_gate_mod._parse_verdict("")["met"] is False


# ── _render_tail 裁决摘要：fail 排在数组后段也永不被 per_msg 截没 ──────────────────────────

def test_render_tail_verdict_digest_survives_truncation():
    from langchain_core.messages import ToolMessage
    import json as _json

    # 40 个 case：前 38 个 pass，最后 2 个 fail/unknown 排在数组末尾
    records = [{"autoid": f"A{i}", "verdict": "pass"} for i in range(38)]
    records += [{"autoid": "A901", "verdict": "fail"}, {"autoid": "A902", "verdict": "unknown"}]
    content = _json.dumps(records, ensure_ascii=False)
    out = goal_gate_mod._render_tail(
        [ToolMessage(content=content, tool_call_id="t1")], per_msg=600
    )
    # 关键信号（总数 + 非pass 的 autoid）必须出现在摘要里，即使原始数组被 per_msg 截断
    assert "裁决摘要" in out
    assert "共40" in out
    assert "A901(fail)" in out and "A902(unknown)" in out
    assert "fail:1" in out and "unknown:1" in out
