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

from main.ist_core.tui.message_model import (
    BLOCK_EVIDENCE,
    BLOCK_HIL_REQUEST,
    BLOCK_PHASE_MARKER,
    BLOCK_TEXT,
    BLOCK_THINKING,
    BLOCK_TOOL_RESULT,
    BLOCK_TOOL_USE,
)
from main.ist_core.tui.reducer import MessageReducer


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


def test_reasoning_token_sets_thinking_phase():
    """reasoning delta（content 空、reasoning 非空）→ llm_phase='thinking'（footer 真实状态源），
    且不混入回答文本；随后 content delta → output。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("llm_token", 1, payload={"reasoning": "让我逐步推理"}))
    assert snaps[-1].llm_phase == "thinking"
    assert snaps[-1].streaming_text is None   # 思考不混入回答文本

    r.dispatch(_evt("llm_token", 2, payload={"reasoning": "继续想"}))
    assert snaps[-1].llm_phase == "thinking"

    r.dispatch(_evt("llm_token", 3, payload={"content": "答案是42"}))
    assert snaps[-1].llm_phase == "output"
    assert snaps[-1].streaming_text == "答案是42"


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


def test_llm_phase_input_on_start_output_on_token_cleared_on_end():
    """llm_start→input；llm_token→output+估算 token；llm_end→清空 phase。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("llm_start", 1))
    assert snaps[-1].llm_phase == "input"
    assert snaps[-1].output_token_count == 0

    r.dispatch(_evt("llm_token", 2, payload={"content": "abcd"}))
    assert snaps[-1].llm_phase == "output"
    assert snaps[-1].output_token_count == 1

    r.dispatch(_evt("llm_end", 3, payload={"name": "final_thought", "content": "done"}))
    assert snaps[-1].llm_phase == ""
    assert snaps[-1].output_token_count == 0


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
    
    assert snap.messages[0].role == "assistant"
    use_block = snap.messages[0].content[0]
    assert use_block.type == BLOCK_TOOL_USE
    assert use_block.name == "qa_grep"
    assert use_block.tool_use_id == "r1:1"
    
    assert use_block.status == "done"

    
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

    
    r.dispatch(_evt("tool_call", 10, tags={"name": "task"},
                    payload={"name": "task", "input": {"subagent_type": "verifier"}}))
    
    r.dispatch(_evt("llm_end", 11,
                    tags={"parent_subagent": "verifier"},
                    payload={"name": "final_thought", "content": "verifier report"}))

    snap = snaps[-1]
    
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

    
    assert captured[0] is not captured[1]
    assert len(captured[0]) == 1
    assert len(captured[1]) == 2
    
    assert isinstance(captured[0], tuple)


def _find(snap, seq):
    """按 uuid 后缀 seq 找 message。"""
    return next(m for m in snap.messages if m.uuid.endswith(f":{seq}"))


def test_nested_fork_pops_stack_via_run_id(monkeypatch):
    """Plan B 核心：嵌套 fork 下用 lc_tool_run_id 精确配对，fork 结束后栈弹空，
    fork 之后的 main agent 报告 parent 为空（顶层显示，不被折叠）。

    复现真实日志 run-91b831a3d39a：seq143 QIS 调 fork，内部工具乱序 result 把
    FIFO 错位，旧逻辑栈永不弹出 → 主报告被错打 parent 折叠隐藏。
    """
    import main.ist_core.tui.reducer as reducer
    monkeypatch.setattr(reducer, "_FORK_SKILLS_CACHE", {"review-verifier"})

    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    
    r.dispatch(_evt("tool_call", 1, tags={"name": "invoke_skill", "lc_tool_run_id": "RID_QIS"},
                    payload={"name": "invoke_skill",
                             "input": {"skill": "review-verifier", "brief": "x"}}))
    
    r.dispatch(_evt("tool_call", 2, tags={"name": "qa_grep", "lc_tool_run_id": "RID_GREP"},
                    payload={"name": "qa_grep", "input": {"pattern": "foo"}}))
    r.dispatch(_evt("tool_result", 3, tags={"name": "qa_grep", "lc_tool_run_id": "RID_GREP"},
                    payload={"name": "qa_grep", "output": "hit"}))
    
    r.dispatch(_evt("llm_end", 4, payload={"name": "final_thought", "content": "VERIFIER REPORT"}))
    
    r.dispatch(_evt("tool_result", 5, tags={"name": "invoke_skill", "lc_tool_run_id": "RID_QIS"},
                    payload={"name": "invoke_skill", "output": "VERDICT: PARTIAL\nLEVEL: P3"}))
    
    r.dispatch(_evt("llm_end", 6, payload={"name": "final_thought", "content": "MAIN REPORT"}))

    snap = snaps[-1]
    
    assert _find(snap, 4).parent_tool_use_id == "r1:1"
    
    assert r._subagent_parent_stack == []
    
    assert _find(snap, 6).parent_tool_use_id == ""


def test_fork_pairing_falls_back_to_fifo_without_run_id(monkeypatch):
    """向后兼容：事件不带 lc_tool_run_id（CLI / server / 旧日志）→ 回退 FIFO。
    单层 fork 下 FIFO 仍能正确弹栈（无嵌套错位时 top==pop(0)）。"""
    import main.ist_core.tui.reducer as reducer
    monkeypatch.setattr(reducer, "_FORK_SKILLS_CACHE", {"review-verifier"})

    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_evt("tool_call", 1, tags={"name": "invoke_skill"},
                    payload={"name": "invoke_skill",
                             "input": {"skill": "review-verifier", "brief": "x"}}))
    r.dispatch(_evt("tool_result", 2, tags={"name": "invoke_skill"},
                    payload={"name": "invoke_skill", "output": "VERDICT: PARTIAL\nLEVEL: P3"}))
    r.dispatch(_evt("llm_end", 3, payload={"name": "final_thought", "content": "MAIN REPORT"}))

    
    assert r._subagent_parent_stack == []
    assert _find(snaps[-1], 3).parent_tool_use_id == ""


def test_serial_multi_sheet_forks_each_pop_correctly(monkeypatch):
    """多 sheet：fork 同步阻塞执行（loader.invoke），forks 串行——A 完整结束
    （tool_result 弹栈）后 B 才开始。验证每个 fork 各自精确弹栈，其间和其后的
    main agent 报告 parent 正确（fork 内挂 parent、fork 间/后为空）。"""
    import main.ist_core.tui.reducer as reducer
    monkeypatch.setattr(reducer, "_FORK_SKILLS_CACHE", {"review-verifier"})

    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    def fork(call_seq, res_seq, rid, body_seq):
        r.dispatch(_evt("tool_call", call_seq,
                        tags={"name": "invoke_skill", "lc_tool_run_id": rid},
                        payload={"name": "invoke_skill",
                                 "input": {"skill": "review-verifier", "brief": "x"}}))
        
        r.dispatch(_evt("llm_end", body_seq,
                        payload={"name": "final_thought", "content": "INNER"}))
        
        r.dispatch(_evt("tool_result", res_seq,
                        tags={"name": "invoke_skill", "lc_tool_run_id": rid},
                        payload={"name": "invoke_skill", "output": "VERDICT: PASS\nLEVEL: P4"}))

    fork(1, 3, "RID_A", 2)
    
    assert r._subagent_parent_stack == []
    fork(4, 6, "RID_B", 5)
    assert r._subagent_parent_stack == []

    snap = snaps[-1]
    
    assert _find(snap, 2).parent_tool_use_id == "r1:1"
    assert _find(snap, 5).parent_tool_use_id == "r1:4"


# ---------------------------------------------------------------- fork 卡片板

def _cards_evt(seq: int, *records):
    return _evt("fork_cards", seq, payload={"records": list(records)})


def test_fork_card_create_update_finalize_inplace():
    """fork_start 建卡→tool/tool_result 原地更新(消息数不变)→fork_end 定格;
    rev 每次 dispatch 单调递增;fork_board_rev 卡片变更递增。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)

    r.dispatch(_cards_evt(1, {"event": "fork_start", "fork_id": "f1", "ts": 1.0,
                              "skill": "compile-worker", "agent": "compile-worker",
                              "tag": "engine:994838", "autoid": "203031754291994838",
                              "brief_head": "编写 case"}))
    s1 = snaps[-1]
    assert len(s1.messages) == 1
    card = s1.messages[0].content[0]
    assert card.type == "fork_card"
    assert card.payload["status"] == "running" and card.payload["autoid"].endswith("994838")
    assert s1.fork_card_indices["fork:f1"] == 0

    r.dispatch(_cards_evt(2, {"event": "tool", "fork_id": "f1", "ts": 2.0,
                              "tool": "dev_probe", "arg": "show sdns", "n_calls": 3}))
    s2 = snaps[-1]
    assert len(s2.messages) == 1, "tool 事件应原地更新,不新增消息"
    p = s2.messages[0].content[0].payload
    assert p["current_tool"] == "dev_probe" and p["n_calls"] == 3
    assert s2.rev > s1.rev and s2.fork_board_rev > s1.fork_board_rev

    r.dispatch(_cards_evt(3, {"event": "tool_result", "fork_id": "f1", "ts": 3.0,
                              "tool": "dev_probe", "status": "ok", "summary": "Pool: p1"}))
    assert list(snaps[-1].messages[0].content[0].payload["recent"]) == ["dev_probe → Pool: p1"]

    r.dispatch(_cards_evt(4, {"event": "fork_end", "fork_id": "f1", "ts": 9.0, "ok": True,
                              "error": "", "elapsed_s": 8.0, "calls": 7, "ai_rounds": 4,
                              "tokens_in": 1000, "tokens_out": 50, "cache_hit": 900}))
    p = snaps[-1].messages[0].content[0].payload
    assert p["status"] == "ok" and p["calls"] == 7 and p["tokens_in"] == 1000
    # 终态后迟到的 tool 事件不再改卡
    r.dispatch(_cards_evt(5, {"event": "tool", "fork_id": "f1", "ts": 10.0,
                              "tool": "fs_read", "arg": "x", "n_calls": 8}))
    p2 = snaps[-1].messages[0].content[0].payload
    assert p2["status"] == "ok" and p2["current_tool"] == ""


def test_fork_card_skeleton_on_out_of_order_tool():
    """tool 先到(fork_start 丢/乱序)→ 自动建骨架卡,不崩不丢。"""
    r = MessageReducer()
    r.dispatch(_cards_evt(1, {"event": "tool", "fork_id": "f9", "ts": 1.0,
                              "tool": "fs_grep", "arg": "p", "n_calls": 1}))
    snap = r.snapshot()
    assert len(snap.messages) == 1
    assert snap.messages[0].content[0].payload["status"] == "running"


def test_engine_card_upsert_and_progress_single_row():
    """engine_tick 同 run 恒一张卡;progress 同 key 恒一行(48 心跳收敛 1 行)。"""
    r = MessageReducer()
    r.dispatch(_cards_evt(1, {"event": "run_meta", "run": "dongkl", "kind": "engine",
                              "ts": 1.0, "mindmap": "x.txt", "ledger": "l.json"}))
    for i in range(5):
        r.dispatch(_cards_evt(2 + i, {"event": "engine_tick", "run": "dongkl",
                                      "phase": "worker_fanout", "round": 0, "wave": 1,
                                      "counts": {"produced": i}, "total": 34, "ts": 2.0 + i}))
    for i in range(48):
        r.dispatch(_cards_evt(100 + i, {"event": "progress", "key": "runbatch:dongkl",
                                        "phase": "上机", "elapsed_s": 10 + 30 * i,
                                        "total_s": 1440, "n_cases": 32,
                                        "detail": "smoke_test/.../test_xlsx.py",
                                        "status": "running", "ts": 100.0 + i}))
    snap = r.snapshot()
    assert len(snap.messages) == 2, "engine 卡 + progress 行,各恒一条"
    eng = snap.messages[0].content[0].payload
    assert eng["counts"]["produced"] == 4 and eng["status"] == "running"
    prog = snap.messages[1].content[0].payload
    assert prog["elapsed_s"] == 10 + 30 * 47
    # 终态定格
    r.dispatch(_cards_evt(200, {"event": "progress", "key": "runbatch:dongkl",
                                "phase": "上机", "elapsed_s": 1500, "total_s": 1440,
                                "n_cases": 32, "detail": "完成", "status": "done", "ts": 999.0}))
    r.dispatch(_cards_evt(201, {"event": "engine_tick", "run": "dongkl", "phase": "report",
                                "round": 2, "wave": 3, "counts": {"passed": 34},
                                "total": 34, "ts": 1000.0}))
    snap = r.snapshot()
    assert snap.messages[1].content[0].payload["status"] == "done"
    assert snap.messages[0].content[0].payload["status"] == "done"


def test_rev_monotonic_across_reset():
    """rev 跨 reset 不清零(清零=reset 后全部快照被 UI 判旧丢弃)。"""
    r = MessageReducer()
    snaps = []
    r.subscribe(snaps.append)
    r.dispatch(_cards_evt(1, {"event": "fork_start", "fork_id": "a", "ts": 1.0}))
    rev_before = snaps[-1].rev
    r.reset()
    assert snaps[-1].rev > rev_before, "reset 后 rev 必须继续递增"
    assert snaps[-1].messages == ()
    r.dispatch(_cards_evt(2, {"event": "fork_start", "fork_id": "b", "ts": 2.0}))
    assert snaps[-1].rev > rev_before + 1
    assert snaps[-1].fork_card_indices == {"fork:b": 0}


def test_fork_cards_interleaved_with_normal_messages_keep_index():
    """卡片与普通消息交错:下标登记随 append 正确,原地更新命中正确消息。"""
    r = MessageReducer()
    r.dispatch(_evt("llm_end", 1, payload={"name": "thought", "text": "分析中"}))
    r.dispatch(_cards_evt(2, {"event": "fork_start", "fork_id": "f1", "ts": 1.0,
                              "skill": "s", "brief_head": "b"}))
    r.dispatch(_evt("llm_end", 3, payload={"name": "thought", "text": "继续"}))
    r.dispatch(_cards_evt(4, {"event": "tool", "fork_id": "f1", "ts": 2.0,
                              "tool": "fs_read", "arg": "a.md", "n_calls": 1}))
    snap = r.snapshot()
    idx = snap.fork_card_indices["fork:f1"]
    assert snap.messages[idx].content[0].payload["current_tool"] == "fs_read"
    n = len(snap.messages)
    r.dispatch(_cards_evt(5, {"event": "tool", "fork_id": "f1", "ts": 3.0,
                              "tool": "fs_grep", "arg": "p", "n_calls": 2}))
    assert len(r.snapshot().messages) == n, "原地更新不增消息"
