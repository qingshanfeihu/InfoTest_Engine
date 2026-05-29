"""FooterPane 状态行测试。

ist_app 的 token 阶段切换已经下沉到 ``MessageReducer``——见
``tests/tui/test_reducer.py::test_usage_only_accumulates_to_snapshot_usage`` 等。
本文件只保留对 FooterPane 渲染层的单测。
"""

from __future__ import annotations

from main.ist_core.ink.components.footer import FooterPane







def test_footer_idle_shows_both_arrows_with_totals():
    f = FooterPane()
    f.update(status="ready", input_tokens=1234, output_tokens=567, model="qwen-plus")
    line = f._status_line.value
    assert "↑ 1,234" in line
    assert "↓ 567" in line
    assert "qwen-plus" in line


def test_footer_input_phase_keeps_session_summary():
    """阶段切换已下沉到 MessageReducer / thinking 行；status 行恒显 ↑/↓ 会话累计。"""
    f = FooterPane()
    f.update(status="ready", input_tokens=2000, output_tokens=300, llm_phase="input")
    line = f._status_line.value
    assert "↑ 2,000" in line
    assert "↓ 300" in line


def test_footer_output_phase_keeps_session_summary():
    f = FooterPane()
    f.update(
        status="ready",
        input_tokens=1000,
        output_tokens=200,
        llm_phase="output",
        output_token_count=42,
    )
    line = f._status_line.value
    assert "↑ 1,000" in line
    assert "↓ 200" in line


def test_footer_phase_clears_after_finalize():
    """空字符串 phase 表示 LLM 收尾——回到 ↑/↓ 总计显示。"""
    f = FooterPane()
    f.update(input_tokens=100, output_tokens=50, llm_phase="output")
    f.update(llm_phase="", output_token_count=0)
    line = f._status_line.value
    assert "↑ 100" in line and "↓ 50" in line
