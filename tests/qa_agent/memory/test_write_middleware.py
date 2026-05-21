"""MemoryWriteMiddleware：after_model 触发 + 计数器 + distill 触发条件。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from main.qa_agent.memory.middleware import (
    MemoryWriteMiddleware,
    read_session_counter,
    reset_session_counter,
)


class _StubStore:
    def __init__(self):
        self.appended: list[tuple[str, str]] = []

    def append_working(self, thread_id, entry):
        self.appended.append((thread_id, entry))


@pytest.fixture
def isolated_memory_root(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_AGENT_MEMORY_ROOT", str(tmp_path / "memory"))
    yield tmp_path / "memory"


@pytest.fixture
def stub_runtime():
    class _EI:
        thread_id = "thread-1"

    class _Rt:
        execution_info = _EI()

    return _Rt()


# ---- L1 hot path 写入 ---------------------------------------------------


def test_after_model_writes_l1_entry(isolated_memory_root, stub_runtime):
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None)

    state = {
        "thread_id": "thread-1",
        "messages": [
            HumanMessage(content="评审"),
            AIMessage(content="grep 一下", tool_calls=[]),
        ],
    }
    mw.after_model(state, stub_runtime)
    assert len(store.appended) == 1
    tid, entry = store.appended[0]
    assert tid == "thread-1"
    assert "thought: grep 一下" in entry


def test_after_model_handles_no_messages(isolated_memory_root, stub_runtime):
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None)
    mw.after_model({}, stub_runtime)
    assert store.appended == []


def test_after_model_swallows_store_exceptions(isolated_memory_root, stub_runtime):
    class _Boom:
        def append_working(self, *a, **k):
            raise RuntimeError("disk full")

    mw = MemoryWriteMiddleware(_Boom(), extractor_agent=None)
    state = {"messages": [AIMessage(content="x")], "thread_id": "t1"}
    # 不应 raise
    mw.after_model(state, stub_runtime)


# ---- distill 触发条件 ---------------------------------------------------


def test_should_distill_on_keyword_match():
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None, distill_every_n=99)
    msgs = [HumanMessage(content="以后不要用 F5 类比")]
    assert mw._should_distill(msgs, turn_count=1)


def test_should_distill_on_turn_count():
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None, distill_every_n=10)
    msgs = [HumanMessage(content="random query")]
    assert mw._should_distill(msgs, turn_count=10)
    assert not mw._should_distill(msgs, turn_count=5)


def test_should_distill_negative_when_no_trigger():
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None, distill_every_n=10)
    msgs = [HumanMessage(content="just a question")]
    assert not mw._should_distill(msgs, turn_count=3)


def test_distill_skipped_when_extractor_is_none(isolated_memory_root, stub_runtime):
    """extractor=None 时即使触发也不会启线程。"""
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None, distill_every_n=1)
    state = {
        "thread_id": "t1",
        "messages": [
            HumanMessage(content="以后不要"),
            AIMessage(content="ok"),
        ],
    }
    # 仅验证不抛异常即可（kick_distill_async 会被跳过因 extractor=None）
    mw.after_model(state, stub_runtime)


# ---- session counter ---------------------------------------------------


def test_session_counter_increments_on_first_turn(isolated_memory_root, stub_runtime):
    reset_session_counter()
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None)
    state = {
        "thread_id": "thread-A",
        "messages": [HumanMessage(content="hi"), AIMessage(content="hi")],
    }
    initial = read_session_counter()
    mw.after_model(state, stub_runtime)
    assert read_session_counter() == initial + 1
    # 同 thread 第二轮不重复 +1
    mw.after_model(state, stub_runtime)
    assert read_session_counter() == initial + 1


def test_session_counter_distinct_threads_each_count_once(
    isolated_memory_root, stub_runtime
):
    """3 个不同 thread_id 各触发首轮 +1，共 +3。

    middleware._extract_thread_id 优先取 runtime.execution_info.thread_id；
    要让 stub 看起来像 3 个独立 thread，必须每次换一个 runtime（构造一个
    新的 EI，thread_id 不同）。
    """
    reset_session_counter()
    store = _StubStore()
    mw = MemoryWriteMiddleware(store, extractor_agent=None)
    initial = read_session_counter()
    for tid in ("a", "b", "c"):
        class _EI:
            thread_id = tid
        class _Rt:
            execution_info = _EI()
        rt = _Rt()
        state = {"thread_id": tid, "messages": [AIMessage(content="x")]}
        mw.after_model(state, rt)
    assert read_session_counter() == initial + 3
