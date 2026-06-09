"""B2 回归：并行工具的 tool_result 归位到各自 tool_use 行下方。

改造前：多个 ⏺ 连续 append、多组 ⎿ 堆在后面（结果不在对应 ⏺ 下）。
改造后：每个 ⏺ 行下紧跟自己的 ⎿ 结果（按 tool_use_id 定位插入 + 索引偏移）。
"""

from __future__ import annotations

from main.ist_core.ink.components import ist_app as M
from main.ist_core.ink.components.transcript import Transcript


class _FakeApp:
    def render(self):
        pass


def _stub():
    s = type("Stub", (), {})()
    s._transcript = Transcript()
    s._app = _FakeApp()
    s._tool_use_row = {}
    s._ai_stream_idx = -1
    s._last_thinking_idx = -1
    s._tool_start_stack = []
    s._tool_output_blocks = []
    s._place_result_lines = M.IstInkApp._place_result_lines.__get__(s)
    s._insert_result_lines = M.IstInkApp._insert_result_lines.__get__(s)
    return s


def test_parallel_tool_results_grouped_under_own_tool_use():
    s = _stub()
    s._transcript.append_message(" ⏺ Grep(A)")
    s._tool_use_row["idA"] = 0
    s._transcript.append_message(" ⏺ Grep(B)")
    s._tool_use_row["idB"] = 1

    s._place_result_lines("idA", ["   ⎿ resultA1", "   ⎿ resultA2"])
    s._place_result_lines("idB", ["   ⎿ resultB1"])

    msgs = s._transcript._messages
    assert msgs == [
        " ⏺ Grep(A)",
        "   ⎿ resultA1",
        "   ⎿ resultA2",
        " ⏺ Grep(B)",
        "   ⎿ resultB1",
    ]


def test_result_falls_back_to_append_when_no_anchor():
    """无对应 tool_use_id 时兜底 append 末尾（不崩）。"""
    s = _stub()
    s._transcript.append_message(" ⏺ Grep(A)")
    s._tool_use_row["idA"] = 0
    start = s._place_result_lines("missing", ["   ⎿ orphan"])
    assert start == 1
    assert s._transcript._messages[-1] == "   ⎿ orphan"


def test_insert_offsets_tracked_indices():
    """插入后，≥ 插入点的索引状态统一偏移。"""
    s = _stub()
    for i in range(5):
        s._transcript.append_message(f"line{i}")
    s._last_thinking_idx = 3
    s._ai_stream_idx = 4
    s._tool_output_blocks = [{"start_idx": 4}]
    s._tool_start_stack = [(3, "x")]
    s._insert_result_lines(2, ["ins1", "ins2"])
    # 插入 2 行于 idx=2，所有 >=2 的索引 +2
    assert s._last_thinking_idx == 5
    assert s._ai_stream_idx == 6
    assert s._tool_output_blocks[0]["start_idx"] == 6
    assert s._tool_start_stack[0][0] == 5
