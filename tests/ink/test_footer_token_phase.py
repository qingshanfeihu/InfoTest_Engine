"""FooterPane 状态行测试。

ist_app 的 token 阶段切换已经下沉到 ``MessageReducer``——见
``tests/tui/test_reducer.py::test_usage_only_accumulates_to_snapshot_usage`` 等。
本文件只保留对 FooterPane 渲染层的单测。
"""

from __future__ import annotations

from main.qa_agent.ink.components.footer import FooterPane


# ---------------------------------------------------------------------------
# FooterPane: 状态行 (_timer_running=False) 按 phase 切箭头
# ---------------------------------------------------------------------------


def test_footer_idle_shows_both_arrows_with_totals():
    f = FooterPane()
    f.update(status="ready", input_tokens=1234, output_tokens=567, model="qwen-plus")
    line = f._status_line.value
    assert "↑ 1,234" in line
    assert "↓ 567" in line
    assert "qwen-plus" in line


def test_footer_input_phase_only_up_arrow():
    f = FooterPane()
    f.update(status="ready", input_tokens=2000, output_tokens=300, llm_phase="input")
    line = f._status_line.value
    assert "↑ 2,000 tokens" in line
    # output 箭头不应出现在 input 阶段
    assert "↓" not in line


def test_footer_output_phase_only_down_arrow_with_streaming_count():
    f = FooterPane()
    # 模拟流式中：output_token_count 用估算字符数 / 4
    f.update(
        status="ready",
        input_tokens=1000,
        output_tokens=200,
        llm_phase="output",
        output_token_count=42,
    )
    line = f._status_line.value
    assert "↓ 42 tokens" in line
    # input 箭头不应出现在 output 阶段
    assert "↑" not in line


def test_footer_phase_clears_after_finalize():
    """空字符串 phase 表示 LLM 收尾——回到 ↑/↓ 总计显示。"""
    f = FooterPane()
    f.update(input_tokens=100, output_tokens=50, llm_phase="output")
    f.update(llm_phase="", output_token_count=0)
    line = f._status_line.value
    assert "↑ 100" in line and "↓ 50" in line
