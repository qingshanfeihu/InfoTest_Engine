"""FooterPane 状态行测试。

ist_app 的 token 阶段切换已经下沉到 ``MessageReducer``——见
``tests/tui/test_reducer.py::test_usage_only_accumulates_to_snapshot_usage`` 等。
本文件只保留对 FooterPane 渲染层的单测。
"""

from __future__ import annotations

from main.ist_core.ink.components.footer import FooterPane, _format_token_count







def test_footer_idle_shows_both_arrows_with_totals():
    f = FooterPane()
    f.update(status="ready", input_tokens=1234, output_tokens=567, model="qwen-plus")
    line = f._status_line.value
    assert "↑ 1.2k" in line
    assert "↓ 567" in line
    assert "qwen-plus" in line


def test_footer_large_token_counts_use_k_suffix():
    f = FooterPane()
    f.update(status="ready", input_tokens=6_111_701, output_tokens=57_566, model="mimo-v2.5-pro")
    line = f._status_line.value
    assert "↑ 6111.7k" in line
    assert "↓ 57.6k" in line


def test_format_token_count_threshold():
    assert _format_token_count(999) == "999"
    assert _format_token_count(1000) == "1.0k"
    assert _format_token_count(57_566) == "57.6k"


def test_footer_input_phase_keeps_session_summary():
    """阶段切换已下沉到 MessageReducer / thinking 行；status 行恒显 ↑/↓ 会话累计。"""
    f = FooterPane()
    f.update(status="ready", input_tokens=2000, output_tokens=300, llm_phase="input")
    line = f._status_line.value
    assert "↑ 2.0k" in line
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
    assert "↑ 1.0k" in line
    assert "↓ 200" in line


def test_footer_phase_clears_after_finalize():
    """空字符串 phase 表示 LLM 收尾——回到 ↑/↓ 总计显示。"""
    f = FooterPane()
    f.update(input_tokens=100, output_tokens=50, llm_phase="output")
    f.update(llm_phase="", output_token_count=0)
    line = f._status_line.value
    assert "↑ 100" in line and "↓ 50" in line


_VERBS_ALL = [
    "Thinking", "Considering", "Analyzing", "Brewing", "Pondering",
    "Cogitating", "Reflecting", "Processing", "Evaluating", "Examining",
]


def _busy_thinking_line(**phase_kw) -> str:
    """造 busy footer，捕获思考行文本（thinking_cb），跑完停 timer。"""
    captured: list = []
    f = FooterPane(thinking_text_cb=lambda t: captured.append(t))
    f.update(status="busy", model="mimo-v2.5-pro", **phase_kw)
    f._stop_timer()
    return captured[-1] if captured else ""


def test_footer_thinking_line_shows_real_state_thinking():
    """thinking 相位 → 尾字段=深度思考中；前面随机词保留；模型名不再是尾字段。"""
    line = _busy_thinking_line(llm_phase="thinking", input_tokens=100)
    assert "深度思考中" in line
    assert "· mimo-v2.5-pro)" not in line          # 尾字段被真实状态替换
    assert any(f"✶ {v}…" in line for v in _VERBS_ALL)  # 前面随机词不动


def test_footer_thinking_line_output_state():
    line = _busy_thinking_line(llm_phase="output", output_token_count=42)
    assert "生成回答中" in line
    assert "· mimo-v2.5-pro)" not in line


def test_footer_thinking_line_input_state():
    line = _busy_thinking_line(llm_phase="input", input_tokens=200)
    assert "接收/处理中" in line


def test_footer_thinking_line_no_phase_shows_run_increment_tokens():
    """无相位（工具执行/编排间隙，等 fork/长工具）→ 随机词 + 计时 + **本轮增量** ↑↓ token：
    - bug2：尾字段**不回退模型名**（停止思考不再显示模型名）
    - 显**本轮增量**（非会话累计）token——fork_input 实时递增，让用户看到 fork 在烧钱/有进展
      （区别于旧「静态会话总量配 spinner 误导」的顾虑：增量是动的、有意义的）
    - 不显任何相位状态词
    """
    line = _busy_thinking_line(llm_phase="", input_tokens=515_600, output_tokens=10_400)
    assert "mimo-v2.5-pro" not in line              # bug2：不回退模型名
    assert "↑" in line and "↓" in line              # 显本轮增量 token（fork 进展可见）
    assert (
        "深度思考中" not in line
        and "生成回答中" not in line
        and "接收/处理中" not in line
    )
    assert any(f"✶ {v}…" in line for v in _VERBS_ALL)  # 随机词 + 计时仍在


def test_footer_thinking_line_live_download_tokens():
    """思考/回答期只显 ↓(单箭头=当前相位方向,2026-07-06):本轮累计+(当次实时)。"""
    line = _busy_thinking_line(llm_phase="thinking", output_token_count=1234, output_tokens=0)
    # 口径统一(2026-07-03):↓ 恒显本轮累计,当次调用实时估算以 (+N) 并列——
    # 同一显示位不再随相位切换含义(旧版 thinking 显当次、等待显累计,被读成"不同步")。
    assert "↓ 0(+1.2k) tokens" in line              # 累计 0 + 当次实时 1.2k
    assert "深度思考中" in line
    assert "↑" not in line                           # 下载相位不显上传箭头
    # input 相位：只显 ↑ 本轮增量(单箭头=当前方向)
    line2 = _busy_thinking_line(llm_phase="input", input_tokens=2000)
    assert "↑ 2.0k tokens" in line2
    assert "↓" not in line2
    assert "接收/处理中" in line2


def test_footer_no_phase_shows_worker_wait_when_fork_silent():
    """无相位 + 本轮出现过 fork 事件 + 静默 ≥15s → busy 行标注「◌ worker Ns 无新事件」。

    场景：main 阻塞等 fork（无 LLM 相位），fork 的 LLM 长思考期 evidence 无新行——
    用户能看出在等 worker 而非挂死（TODO-1 轻量版）。
    """
    import time as _t
    captured: list = []
    f = FooterPane(thinking_text_cb=lambda t: captured.append(t))
    f.update(status="busy", model="m")
    f._busy_since = _t.time() - 60             # busy 已 60s
    f.fork_last_event_ts = _t.time() - 20      # busy 后出现过 fork 事件，已静默 20s
    f._refresh()
    f._stop_timer()
    line = next((t for t in reversed(captured) if t), "")
    assert "◌ worker" in line and "无新事件" in line


def test_footer_no_phase_no_worker_wait_when_fork_fresh_or_absent():
    import time as _t
    # fork 事件很新（<15s）→ 不标注
    captured: list = []
    f = FooterPane(thinking_text_cb=lambda t: captured.append(t))
    f.update(status="busy", model="m")
    f._busy_since = _t.time() - 60
    f.fork_last_event_ts = _t.time() - 3       # fork 事件很新
    f._refresh()
    f._stop_timer()
    assert "◌ worker" not in (next((t for t in reversed(captured) if t), ""))
    # 本轮无 fork 事件（ts=0 早于 busy_since）→ 不标注
    captured2: list = []
    f2 = FooterPane(thinking_text_cb=lambda t: captured2.append(t))
    f2.update(status="busy", model="m")
    f2._refresh()
    f2._stop_timer()
    assert "◌ worker" not in (next((t for t in reversed(captured2) if t), ""))


def test_sticky_error_shows_and_clears():
    # 粘性错误条(2026-07-05 遗留#5):error 驻留状态行(单行截断),下一轮 busy 自动清
    f = FooterPane()
    f.update(status="error")
    f.set_sticky_error("compile_emit 失败: G 列为 None\n第二行明细")
    line = f._status_line.value
    assert "✖" in line and "G 列为 None" in line and "第二行明细" in line and "\n" not in line
    f.update(status="thinking")   # 新一轮开始 → 驻留解除
    assert "✖" not in f._status_line.value
    f._stop_timer()


def test_sticky_error_truncated_to_single_width():
    f = FooterPane()
    f.update(status="error")
    f.set_sticky_error("x" * 300)
    seg = f._status_line.value.split("·")[0]
    assert "…" in seg and len(seg) < 130
