"""升级末轮(effort=max + 全回显 brief + 逐轮归档)+ fork 翻流式(停滞守卫/finish_reason)
+ footbar 最大深度思考中——2026-07-07 本轮改动的机读断言。

覆盖纯函数/可注入单元;并发流式稳定性与守卫真生效走实跑验证(不在单测)。
"""
from __future__ import annotations

import types


# ------------------------------------------------- F: ForkExecutor._limits_for
def test_limits_for_max_bumps_both_walls():
    from main.ist_core.resilience import AdaptiveLimiter, ForkExecutor
    fe = ForkExecutor(AdaptiveLimiter(1, 1, 4))
    base_wall, base_trans = fe._limits_for("")
    high_wall, high_trans = fe._limits_for("high")
    max_wall, max_trans = fe._limits_for("max")
    # 非 max:基础值(600/1200 默认)
    assert base_wall == high_wall == fe.wallclock_s
    assert base_trans == high_trans == fe.transient_wallclock_s
    # max:两层都放宽,且重试窗口 ≥ 单次墙钟(容得下一次完整 max 单跑)
    assert max_wall > base_wall
    assert max_trans >= max_wall


def test_limits_for_max_env_override(monkeypatch):
    from main.ist_core.resilience import AdaptiveLimiter, ForkExecutor
    monkeypatch.setenv("IST_FORK_WALLCLOCK_MAX_S", "999")
    monkeypatch.setenv("IST_FORK_TRANSIENT_WALLCLOCK_MAX_S", "1500")
    fe = ForkExecutor(AdaptiveLimiter(1, 1, 4))
    wall, trans = fe._limits_for("max")
    assert wall == 999.0 and trans == 1500.0


# ------------------------------------------ D2: footbar 最大深度思考中
def test_payloads_have_max_thinking():
    from main.ist_core.ink.components.ist_app import _payloads_have_max_thinking
    running_hi = {"kind": "fork", "status": "running", "effort": "high"}
    running_max = {"kind": "fork", "status": "running", "effort": "max"}
    done_max = {"kind": "fork", "status": "ok", "effort": "max"}
    assert _payloads_have_max_thinking([running_hi]) is False
    assert _payloads_have_max_thinking([running_hi, running_max]) is True
    assert _payloads_have_max_thinking([done_max]) is False   # 已结束不算


def test_engine_bottom_line_max_thinking_tail():
    from main.ist_core.ink.components.ist_app import _render_engine_bottom_line
    p = {"kind": "engine", "run": "dongkl", "phase": "worker_fanout",
         "round": 2, "total": 4, "counts": {"produced": 1}}
    assert "最大深度思考中" not in _render_engine_bottom_line(p)
    assert "最大深度思考中" in _render_engine_bottom_line(p, max_thinking=True)


# ------------------------------------------ H: finish_reason 终止信号
def _chunk(*, gen_info=None, resp_meta=None):
    msg = types.SimpleNamespace(response_metadata=resp_meta or {})
    return types.SimpleNamespace(generation_info=gen_info, message=msg)


def test_chunk_finish_reason_reads_both_sources():
    from main.ist_core.agents._llm import _get_chat_openai_with_reasoning
    cls = _get_chat_openai_with_reasoning()
    assert cls._chunk_finish_reason(_chunk(gen_info={"finish_reason": "stop"})) == "stop"
    assert cls._chunk_finish_reason(_chunk(resp_meta={"finish_reason": "tool_calls"})) == "tool_calls"
    assert cls._chunk_finish_reason(_chunk()) == ""


def test_verify_finish_enabled_toggle(monkeypatch):
    from main.ist_core.agents._llm import _get_chat_openai_with_reasoning
    cls = _get_chat_openai_with_reasoning()
    monkeypatch.delenv("IST_LLM_VERIFY_FINISH", raising=False)
    assert cls._verify_finish_enabled() is True     # 默认开
    monkeypatch.setenv("IST_LLM_VERIFY_FINISH", "0")
    assert cls._verify_finish_enabled() is False


# ------------------------------------------ D2 数据面: reducer fork_start 带 effort
def test_reducer_fork_start_carries_effort():
    from main.ist_core.tui.reducer import MessageReducer
    r = MessageReducer()
    r._on_fork_cards({"payload": {"records": [
        {"event": "fork_start", "fork_id": "abc123", "skill": "compile-worker",
         "agent": "compile-worker", "effort": "max", "ts": 1.0}]}})
    snap = r.snapshot()
    idx = snap.fork_card_indices.get("fork:abc123")
    assert idx is not None, "fork_start 应建卡"
    payload = snap.messages[idx].content[0].payload
    assert payload.get("effort") == "max", "effort 应透传进卡片 payload(供 footbar 挂标)"


# ------------------------------------------ Fix4: 设备回显报告展示层清理

# ------------------------- 布局门(2026-07-08 官方长上下文实践,PROMPT_ENGINEERING_STANDARD §一)

def test_worker_skill_has_tail_examples_and_instructions_last():
    """worker SKILL:尾块 <examples> 存在;$ARGUMENTS(数据)在 <instructions>(指令)之前。"""
    from pathlib import Path
    body = (Path("main/ist_core/skills/compile-worker/SKILL.md")).read_text(encoding="utf-8")
    assert "<examples>" in body and "STATUS: produced" in body and "STATUS: needs_user_decision" in body
    assert body.find("$ARGUMENTS") < body.find("<instructions>")
    assert body.rstrip().endswith("</instructions>")


