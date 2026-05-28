"""MessageReducer 单元测试 —— 直接覆盖本次 bug 的 long+short final_thought 场景。

旧 sink 用 ``_last_final_thought_prefix: str`` 单 slot 指纹去重。事件流：
1. seq 204 长报告（8115 字）→ 渲染 + 记指纹 ``report[:200]``
2. seq 213 短结尾「评审完成。」→ 渲染 + **指纹被覆盖为 "评审完成。"**
3. seq 225 finalize node_end final_answer = 长报告 → 比对 ``report[:200] != "评审完成。"``
   → **再次渲染长报告**

新 reducer 模型：
- 双源已拆（streaming.py 不再透传 final_answer）
- 同 uuid 永远只产生一条 message；不同事件 seq → 不同 uuid → 各自独立 message
- 测试断言：长报告 + 短结尾 → 两条独立 assistant message，且只有这两条
"""

from __future__ import annotations

from main.qa_agent.tui.message_model import (
    BLOCK_EVIDENCE,
    BLOCK_HIL_REQUEST,
    BLOCK_PHASE_MARKER,
    BLOCK_TEXT,
    BLOCK_THINKING,
    BLOCK_TOOL_RESULT,
    BLOCK_TOOL_USE,
)
from main.qa_agent.tui.reducer import MessageReducer


def _evt(kind: str, seq: int, **kw):
    base = {
        "kind": kind,
        "run_id": "r1",
        "seq": seq,
        "ts": "",
        "payload": {},
        "tags": {},
        "usage": None,
    }
    base.update(kw)
    return base


def test_token_streaming_then_final_clears_streaming_text():
    """`llm_token` 累加到 streaming_text；`llm_end name=final_thought` 清空 + push 终态。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("llm_token", 1, payload={"content": "Hel"}))
    r.dispatch(_evt("llm_token", 2, payload={"content": "lo"}))
    assert snaps[-1].streaming_text == "Hello"
    assert len(snaps[-1].messages) == 0

    r.dispatch(_evt("llm_end", 3, payload={"name": "final_thought", "content": "Hello world"}))
    snap = snaps[-1]
    assert snap.streaming_text is None, "streaming_text must be cleared on final"
    assert len(snap.messages) == 1
    assert snap.messages[0].role == "assistant"
    assert snap.messages[0].content[0].type == BLOCK_TEXT
    assert snap.messages[0].content[0].text == "Hello world"


def test_long_then_short_final_thought_yields_two_independent_messages():
    """本次 bug 的关键场景：长报告 + 短结尾 = 两条独立 assistant message，无任何去重。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    long_report = "# Report\n\n" + ("- bullet line\n" * 200)
    r.dispatch(_evt("llm_end", 1, payload={"name": "final_thought", "content": long_report}))
    r.dispatch(_evt("llm_end", 2, payload={"name": "final_thought", "content": "评审完成。"}))

    snap = snaps[-1]
    assert len(snap.messages) == 2
    assert snap.messages[0].uuid == "r1:1"
    assert snap.messages[1].uuid == "r1:2"
    assert snap.messages[0].content[0].text == long_report
    assert snap.messages[1].content[0].text == "评审完成。"


def test_thought_with_tool_calls_marker_skipped():
    """``[Calling tools]`` 占位不该入 messages（仅清流式态）。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("llm_token", 1, payload={"content": "thinking..."}))
    r.dispatch(_evt("llm_end", 2, payload={"name": "thought", "content": "[Calling tools]"}))

    snap = snaps[-1]
    assert snap.streaming_text is None
    assert len(snap.messages) == 0


def test_usage_only_accumulates_to_snapshot_usage():
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("llm_end", 1, payload={"name": "usage_only"}, usage={
        "input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
    }))
    r.dispatch(_evt("llm_end", 2, payload={"name": "usage_only"}, usage={
        "input_tokens": 30, "output_tokens": 10, "total_tokens": 40,
    }))
    assert dict(snaps[-1].usage) == {"input_tokens": 130, "output_tokens": 60, "total_tokens": 190}
    # usage_only 不入 messages
    assert len(snaps[-1].messages) == 0


def test_tool_call_then_tool_result_pairs_by_tool_use_id():
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("tool_call", 1, tags={"name": "qa_grep"},
                    payload={"name": "qa_grep", "input": {"pattern": "foo"}}))
    r.dispatch(_evt("tool_result", 2, tags={"name": "qa_grep"},
                    payload={"name": "qa_grep", "output": "hit-1\nhit-2"}))

    snap = snaps[-1]
    assert len(snap.messages) == 2
    # 第一条：assistant + tool_use
    assert snap.messages[0].role == "assistant"
    use_block = snap.messages[0].content[0]
    assert use_block.type == BLOCK_TOOL_USE
    assert use_block.name == "qa_grep"
    assert use_block.tool_use_id == "r1:1"
    # 关键：tool_result 到达后，原 tool_use block 状态切到 done
    assert use_block.status == "done"

    # 第二条：user + tool_result（tool_use_id 配对）
    assert snap.messages[1].role == "user"
    res_block = snap.messages[1].content[0]
    assert res_block.type == BLOCK_TOOL_RESULT
    assert res_block.tool_use_id == "r1:1"
    assert res_block.output == "hit-1\nhit-2"


def test_subagent_inner_event_attaches_parent_tool_use_id():
    """task tool 调用 → 主 agent 发 tool_call；subagent 内部事件带 parent_subagent
    tag → reducer 把 parent_tool_use_id 设为 task tool_use_id。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    # 主 agent 调 task tool
    r.dispatch(_evt("tool_call", 10, tags={"name": "task"},
                    payload={"name": "task", "input": {"subagent_type": "verifier"}}))
    # subagent 内部 emit final_thought
    r.dispatch(_evt("llm_end", 11,
                    tags={"parent_subagent": "verifier"},
                    payload={"name": "final_thought", "content": "verifier report"}))

    snap = snaps[-1]
    # 找 verifier 内部那条 message
    verifier_msg = next(m for m in snap.messages if m.subagent_type == "verifier")
    assert verifier_msg.parent_tool_use_id == "r1:10"
    assert verifier_msg.content[0].text == "verifier report"


def test_thinking_block_creates_thinking_content():
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("info", 1, payload={"name": "thinking_block", "thinking": "deep thought"}))
    snap = snaps[-1]
    assert len(snap.messages) == 1
    block = snap.messages[0].content[0]
    assert block.type == BLOCK_THINKING
    assert block.thinking == "deep thought"


def test_phase_marker_evidence_finding_become_system_messages():
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("phase_marker", 1, payload={"phase": "discover"}))
    r.dispatch(_evt("evidence_added", 2, payload={"path": "x.md", "lines": [1, 2]}))
    r.dispatch(_evt("finding_emitted", 3, payload={"kind": "P0", "msg": "issue"}))

    snap = snaps[-1]
    assert len(snap.messages) == 3
    types = [m.content[0].type for m in snap.messages]
    assert types == [BLOCK_PHASE_MARKER, BLOCK_EVIDENCE, "finding"]
    roles = [m.role for m in snap.messages]
    assert roles == ["system", "system", "system"]


def test_run_lifecycle_status_transitions():
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    assert r.snapshot().status == "idle"
    r.dispatch(_evt("run_start", 1))
    assert snaps[-1].status == "running"
    r.dispatch(_evt("run_end", 2))
    assert snaps[-1].status == "done"


def test_set_run_status_external_hook_propagates():
    """bridge 在 worker 完成时调 reducer.set_run_status——确认会触发 notify。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.set_run_status("done")
    assert snaps[-1].status == "done"


def test_hil_request_creates_hil_request_block():
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("hil_request", 1, payload={
        "findings": {"a": 1},
        "draft_answer": "draft",
        "reason": "uncertain",
    }))
    snap = snaps[-1]
    assert len(snap.messages) == 1
    block = snap.messages[0].content[0]
    assert block.type == BLOCK_HIL_REQUEST
    assert dict(block.payload) == {"findings": {"a": 1}, "draft_answer": "draft", "reason": "uncertain"}


def test_messages_tuple_immutable_across_dispatches():
    """每次 dispatch 后 snapshot.messages 是新 tuple（不影响之前订阅者）。"""
    r = MessageReducer()
    captured: list[tuple] = []

    def cb(s):
        captured.append(s.messages)

    r.subscribe(cb)
    r.dispatch(_evt("llm_end", 1, payload={"name": "final_thought", "content": "a"}))
    r.dispatch(_evt("llm_end", 2, payload={"name": "final_thought", "content": "b"}))

    # 第一次和第二次的 messages tuple 是不同对象
    assert captured[0] is not captured[1]
    assert len(captured[0]) == 1
    assert len(captured[1]) == 2
    # tuple 本身不可变，订阅者不能改
    assert isinstance(captured[0], tuple)
