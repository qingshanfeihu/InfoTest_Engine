"""注入中间件：reminder 构造 + 去重 + 注入位置。"""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from main.qa_agent.memory.middleware import (
    MemoryInjectionMiddleware,
    _has_recent_reminder,
    _last_user_query,
    _extract_thread_id,
)


class _StubStore:
    def __init__(self, *, working: str = "", long_term=None):
        self._working = working
        self._lt = long_term or []

    def read_working(self, thread_id, *, max_lines=80):
        return self._working

    def read_long_term(self, query, *, top_k=3):
        return list(self._lt)


def _build_request(messages, *, thread_id="t-1"):
    """返回一个最小化 ModelRequest，足以测试 _inject 行为。"""
    from langchain.agents.middleware.types import ModelRequest

    state: dict = {"thread_id": thread_id, "messages": messages}

    class _Rt:
        execution_info = type("EI", (), {"thread_id": thread_id})()
        context = None
        store = None

    return ModelRequest(
        model=mock.MagicMock(),  # 不会被调用
        system_prompt=None,
        messages=list(messages),
        tool_choice=None,
        tools=[],
        response_format=None,
        runtime=_Rt(),
        state=state,
    )


# ---- helper functions ----------------------------------------------------


def test_has_recent_reminder_detects_within_4():
    msgs = [
        HumanMessage(content="x"),
        HumanMessage(content="<memory-context>foo</memory-context>"),
        HumanMessage(content="y"),
        HumanMessage(content="z"),
    ]
    assert _has_recent_reminder(msgs)


def test_has_recent_reminder_ignores_old():
    msgs = (
        [HumanMessage(content="<memory-context>old</memory-context>")]
        + [HumanMessage(content=f"x{i}") for i in range(10)]
    )
    assert not _has_recent_reminder(msgs)


def test_last_user_query_skips_reminders():
    msgs = [
        HumanMessage(content="<system-reminder>skills</system-reminder>"),
        HumanMessage(content="<memory-context>memory</memory-context>"),
        HumanMessage(content="actual question"),
    ]
    assert _last_user_query(msgs) == "actual question"


def test_extract_thread_id_prefers_runtime_execution_info():
    state = {"thread_id": "from-state"}

    class _Rt:
        execution_info = type("EI", (), {"thread_id": "from-runtime"})()

    assert _extract_thread_id(state, _Rt()) == "from-runtime"


def test_extract_thread_id_falls_back_to_state():
    class _Rt:
        execution_info = None

    assert _extract_thread_id({"thread_id": "from-state"}, _Rt()) == "from-state"


def test_extract_thread_id_default_when_missing():
    assert _extract_thread_id({}, type("R", (), {"execution_info": None})()) == "default"


# ---- MemoryInjectionMiddleware._build_reminder --------------------------


def test_build_reminder_returns_none_when_empty():
    store = _StubStore(working="", long_term=[])
    mw = MemoryInjectionMiddleware(store)
    req = _build_request([HumanMessage(content="q")])
    reminder = mw._build_reminder(thread_id="t1", query="q", request=req)
    assert reminder is None


def test_build_reminder_includes_l1_when_present():
    store = _StubStore(working="line1\nline2", long_term=[])
    mw = MemoryInjectionMiddleware(store)
    req = _build_request([HumanMessage(content="q")])
    reminder = mw._build_reminder(thread_id="t1", query="q", request=req)
    assert reminder is not None
    assert "Working Notes" in reminder.content
    assert "line1" in reminder.content
    assert "<memory-context>" in reminder.content


def test_build_reminder_includes_l2_when_present():
    store = _StubStore(
        working="",
        long_term=[("/memories/preferences.md", "用户偏好正文")],
    )
    mw = MemoryInjectionMiddleware(store)
    req = _build_request([HumanMessage(content="评审")])
    reminder = mw._build_reminder(thread_id="t1", query="评审", request=req)
    assert reminder is not None
    assert "Relevant Long-Term Notes" in reminder.content
    assert "/memories/preferences.md" in reminder.content


def test_build_reminder_truncates_long_l2_blocks():
    long = "y" * 2000
    store = _StubStore(long_term=[("/memories/x.md", long)])
    mw = MemoryInjectionMiddleware(store)
    req = _build_request([HumanMessage(content="q")])
    reminder = mw._build_reminder(thread_id="t1", query="q", request=req)
    assert "..." in reminder.content


# ---- MemoryInjectionMiddleware._inject ---------------------------------


def test_inject_inserts_before_last_human_message():
    store = _StubStore(working="some entry")
    mw = MemoryInjectionMiddleware(store)
    msgs = [
        HumanMessage(content="prev"),
        AIMessage(content="reply"),
        HumanMessage(content="now"),
    ]
    req = _build_request(msgs)
    new_req = mw._inject(req)
    assert len(new_req.messages) == 4
    # 倒数第 2 条应该是 reminder（插在最后一条 HumanMessage 之前）
    assert "<memory-context>" in new_req.messages[-2].content
    assert new_req.messages[-1].content == "now"


def test_inject_skips_when_recent_reminder_present():
    store = _StubStore(working="entry")
    mw = MemoryInjectionMiddleware(store)
    msgs = [
        HumanMessage(content="<memory-context>old</memory-context>"),
        HumanMessage(content="now"),
    ]
    req = _build_request(msgs)
    new_req = mw._inject(req)
    # 不再追加新的 reminder
    reminder_count = sum(
        1 for m in new_req.messages if "<memory-context>" in (m.content or "")
    )
    assert reminder_count == 1


def test_inject_swallows_store_exceptions():
    """store 抛错时 _inject 必须返回原 request，不影响主流程。"""

    class _Boom:
        def read_working(self, *a, **k):
            raise RuntimeError("disk full")

        def read_long_term(self, *a, **k):
            raise RuntimeError("store down")

    mw = MemoryInjectionMiddleware(_Boom())
    msgs = [HumanMessage(content="q")]
    req = _build_request(msgs)
    out = mw._inject(req)
    assert out.messages == msgs  # 原样返回
