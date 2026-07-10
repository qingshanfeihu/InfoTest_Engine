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


def test_thread_local_fork_label_set_and_cleared():
    """graph 回调 metadata 缺失时的兜底身份标:fork 执行期同线程可读,退出即清。"""
    from main.ist_core.skills import loader as L

    class _Stub:
        def invoke(self, inp, cfg):
            assert L.current_fork_label() == "compile-attributor"   # 执行期可读
            return {"messages": []}

    import os
    os.environ["IST_FORK_STEP_EMIT"] = "0"   # 走阻塞 invoke 分支
    try:
        L._invoke_fork_streamed(_Stub(), "brief", "compile-attributor#3")
    finally:
        os.environ.pop("IST_FORK_STEP_EMIT", None)
    assert L.current_fork_label() == ""                             # 退出即清


def test_graph_callback_falls_back_to_thread_label():
    """kwargs 无 metadata(LangChain tool/end 回调常态)→ 兜底 thread-local 打标。"""
    from main.ist_core.graph import _MainAgentProgressHandler
    from main.ist_core.skills import loader as L
    h = _MainAgentProgressHandler()
    L._FORK_CTX.label = "compile-worker"
    try:
        tags = h._subagent_tags({})            # 无 metadata
        assert tags.get("parent_subagent") == "compile-worker"
    finally:
        L._FORK_CTX.label = ""
    assert h._subagent_tags({}).get("parent_subagent") is None


def test_orphan_tool_result_without_call_is_dropped():
    """无头孤儿结果块不渲染(2026-07-10 第5轮 ctrl+o 实证:单边泄漏的 result 成片
    无头 ⎿ 噪音);主 agent 正常结果有 call 配对不受影响。"""
    r = MessageReducer()
    r.dispatch(_evt("tool_result", 1, payload={"output": "orphan noise"}))
    assert not r.snapshot().messages
    # 正常配对:call 先行 → result 挂上
    r.dispatch(_evt("tool_call", 2, tags={"name": "fs_read"}, payload={"input": {"p": "x"}}))
    r.dispatch(_evt("tool_result", 3, tags={"name": "fs_read"}, payload={"output": "content"}))
    snap = r.snapshot()
    assert any(b.type == "tool_result" for m in snap.messages for b in m.content)
