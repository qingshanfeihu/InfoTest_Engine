"""fork 事件隔离门(2026-07-10 yzg 复跑实证:归因 fork 散文/工具行刷主屏)。

规则:带 parent_subagent 标且无 invoke_skill/task 容器的「游离 fork」事件——
正文/工具行不落主 transcript,流式增量不驱动主相位,结果行不吃主 inflight 队头;
有容器的 fork(invoke_skill)保持嵌套渲染不变。
"""
from __future__ import annotations

from main.ist_core.tui.message_model import BLOCK_TEXT
from main.ist_core.tui.reducer import MessageReducer


def _evt(kind: str, seq: int, **kw):
    base = {"kind": kind, "run_id": "r1", "seq": seq, "ts": "",
            "payload": {}, "tags": {}, "usage": None}
    base.update(kw)
    return base


FORK = {"parent_subagent": "compile-attributor"}


def test_orphan_fork_text_and_tools_do_not_reach_transcript():
    r = MessageReducer()
    r.dispatch(_evt("llm_token", 1, tags=dict(FORK), payload={"content": "Analysis prose..."}))
    r.dispatch(_evt("tool_call", 2, tags={**FORK, "name": "submit_attribution"},
                    payload={"input": {"autoid": "x"}}))
    r.dispatch(_evt("tool_result", 3, tags={**FORK, "name": "submit_attribution"},
                    payload={"output": "error: validation"}))
    r.dispatch(_evt("llm_end", 4, tags=dict(FORK), payload={"content": "final prose"}))
    snap = r.snapshot()
    assert not snap.messages                       # 零落屏
    assert snap.streaming_text in (None, "")       # 不进主流式 ⏺
    assert r._inflight_tool_use_ids == []          # 不抢主 inflight


def test_orphan_fork_does_not_drive_main_phase():
    r = MessageReducer()
    r.dispatch(_evt("llm_start", 1, tags=dict(FORK)))
    assert r.snapshot().llm_phase == ""            # fork 不置主相位
    r.dispatch(_evt("llm_token", 2, tags=dict(FORK), payload={"reasoning": "thinking..."}))
    assert r.snapshot().llm_phase == ""
    r.dispatch(_evt("llm_start", 3))               # 主 agent 自己的调用照常
    assert r.snapshot().llm_phase == "input"


def test_container_fork_keeps_nested_rendering():
    """invoke_skill 容器 fork:事件仍进 transcript(挂 parent_tool_use_id 折叠)。"""
    r = MessageReducer()
    r.dispatch(_evt("tool_call", 1, tags={"name": "invoke_skill"},
                    payload={"input": {"skill": "review-verifier"}}))
    assert r._subagent_parent_stack                # 容器已开
    r.dispatch(_evt("llm_end", 2, tags={"parent_subagent": "review-verifier"},
                    payload={"content": "fork text"}))
    snap = r.snapshot()
    texts = [b for m in snap.messages for b in m.content if b.type == BLOCK_TEXT]
    assert any("fork text" in (b.text or "") for b in texts)
    assert snap.messages[-1].parent_tool_use_id    # 挂在容器下


def test_main_agent_events_untouched():
    r = MessageReducer()
    r.dispatch(_evt("llm_token", 1, payload={"content": "主回答"}))
    assert r.snapshot().streaming_text == "主回答"
    r.dispatch(_evt("llm_end", 2, payload={"content": "主回答完整"}))
    snap = r.snapshot()
    assert any("主回答完整" in (b.text or "")
               for m in snap.messages for b in m.content if b.type == BLOCK_TEXT)
