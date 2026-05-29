"""Stage 1 TuiState smoke tests."""

from main.ist_core.tui.state import TuiState


def test_default_state():
    s = TuiState()
    assert s.thread_id == "" and s.run_id == ""
    assert s.tokens_used == 0 and s.tokens_budget == 128000
    assert s.streaming is False
    assert s.llm_calls == 0 and s.tool_calls == 0
    assert s.log_tail == []


def test_reset_run_keeps_thread_id_and_budget():
    s = TuiState(thread_id="t1", tokens_budget=100, tokens_used=42, llm_calls=3, tool_calls=5)
    s.append_log("hello")
    s.reset_run(run_id="r2")
    assert s.thread_id == "t1"
    assert s.tokens_budget == 100
    assert s.tokens_used == 42
    assert s.run_id == "r2"
    assert s.llm_calls == 0 and s.tool_calls == 0
    assert s.log_tail == []


def test_log_tail_truncates_to_max_keep():
    s = TuiState()
    for i in range(20):
        s.append_log(f"line{i}", max_keep=8)
    assert len(s.log_tail) == 8
    assert s.log_tail[0] == "line12"
    assert s.log_tail[-1] == "line19"
