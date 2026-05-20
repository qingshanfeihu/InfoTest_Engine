"""Stage 1 sink routing tests — verify TuiSink translates QaAgentEvent -> IstUiEvent.

不启 Textual App，纯 mock post_message。Stage 1 只覆盖核心事件类型；
Stage 4 加 PlatformTask / Xlsx / PythonExec / BashExec 路由测试。
"""

from __future__ import annotations

from typing import Any, List

import pytest

from main.qa_agent.tui.messages import (
    AIThinkingMessage,
    BashExecMessage,
    ErrorMessage,
    EvidenceMessage,
    FileReadMessage,
    FindingMessage,
    GrepHitsMessage,
    HilRequestMessage,
    HumanInputMessage,
    LsTreeMessage,
    PhaseMarkerMessage,
    PlatformTaskMessage,
    PythonExecMessage,
    SubAgentDispatchMessage,
    ToolCallMessage,
    XlsxSheetMessage,
)
from main.qa_agent.tui.sink import IstUiEvent, TuiSink


@pytest.fixture
def captured() -> List[IstUiEvent]:
    return []


@pytest.fixture
def sink(captured: List[IstUiEvent]) -> TuiSink:
    return TuiSink(post=captured.append, token_throttle_ms=0)  # 0ms = flush every call


def _ev(kind: str, **fields: Any) -> dict:
    base = {"run_id": "r1", "seq": 1, "ts": "2026-05-18T00:00:00.000Z", "kind": kind, "payload": {}, "tags": {}}
    base.update(fields)
    return base


def test_run_lifecycle_emits_run_start_and_end(sink, captured):
    sink(_ev("run_start", payload={"config": {"thread_id": "t1"}}))
    sink(_ev("run_end"))
    kinds = [e.kind for e in captured]
    assert "run_start" in kinds and "run_end" in kinds


def test_llm_token_buffered_and_flushed_on_next_event(sink, captured):
    sink(_ev("llm_start"))
    sink(_ev("llm_token", payload={"content": "hello"}))
    sink(_ev("llm_token", payload={"content": " world"}))
    sink(_ev("llm_end"))

    update_events = [e for e in captured if e.kind == "update_ai_token"]
    assert update_events, "应至少 flush 一次 token"
    chunks = "".join((e.extra or {}).get("chunk", "") for e in update_events)
    assert "hello" in chunks and "world" in chunks


def test_llm_start_appends_ai_thinking_message(sink, captured):
    sink(_ev("llm_start"))
    appended = [e for e in captured if e.kind == "append" and isinstance(e.message, AIThinkingMessage)]
    assert len(appended) == 1


def test_tool_call_dispatches_to_specialized_message(sink, captured):
    """已注册的工具名应路由到专属消息子类。"""
    cases = [
        ("qa_platform_run_task", PlatformTaskMessage),
        ("qa_deepagent_grep", GrepHitsMessage),
        ("qa_deepagent_ls", LsTreeMessage),
        ("qa_exec", PythonExecMessage),
        ("qa_bash", BashExecMessage),
    ]
    for tool_name, expected_cls in cases:
        local: List[IstUiEvent] = []
        s = TuiSink(post=local.append, token_throttle_ms=0)
        s(_ev("tool_call", tags={"name": tool_name}, payload={"input": {}}))
        appends = [e for e in local if e.kind == "append"]
        assert appends, f"{tool_name} 应至少产生一个 append 事件"
        assert isinstance(appends[0].message, expected_cls), (
            f"{tool_name} 应路由到 {expected_cls.__name__}, 实际 {type(appends[0].message).__name__}"
        )


def test_unknown_tool_falls_back_to_generic_tool_call(sink, captured):
    sink(_ev("tool_call", tags={"name": "some_unknown_tool"}, payload={"input": {"x": 1}}))
    appends = [e for e in captured if e.kind == "append"]
    assert appends and isinstance(appends[0].message, ToolCallMessage)
    assert appends[0].message.tool_name == "some_unknown_tool"


def test_xlsx_path_upgrades_read_file_to_xlsx_sheet(sink, captured):
    """关键：read_file & path.endswith('.xlsx') 必须升级为 XlsxSheetMessage。"""
    sink(_ev(
        "tool_call",
        tags={"name": "qa_deepagent_read_file"},
        payload={"input": {"path": "knowledge/orgin/Test List.xlsx"}},
    ))
    appends = [e for e in captured if e.kind == "append"]
    assert appends and isinstance(appends[0].message, XlsxSheetMessage)
    assert appends[0].message.workbook_path.endswith(".xlsx")


def test_non_xlsx_read_file_routes_to_file_read(sink, captured):
    sink(_ev(
        "tool_call",
        tags={"name": "qa_deepagent_read_file"},
        payload={"input": {"path": "main/qa_agent/graph.py"}},
    ))
    appends = [e for e in captured if e.kind == "append"]
    assert appends and isinstance(appends[0].message, FileReadMessage)


def test_phase_marker_routed_as_message(sink, captured):
    sink(_ev("phase_marker", payload={"phase": "scope"}))
    appends = [e for e in captured if e.kind == "append" and isinstance(e.message, PhaseMarkerMessage)]
    assert appends and appends[0].message.phase == "scope"


def test_evidence_and_finding_events(sink, captured):
    sink(_ev("evidence_added", payload={"summary": "ev1"}))
    sink(_ev("finding_emitted", payload={"summary": "f1"}))
    sink(_ev("finding_written", payload={"summary": "f2"}))
    msgs = [e.message for e in captured if e.kind == "append" and e.message is not None]
    assert any(isinstance(m, EvidenceMessage) for m in msgs)
    assert sum(1 for m in msgs if isinstance(m, FindingMessage)) == 2


def test_hil_request_routed_with_payload_fields(sink, captured):
    sink(_ev("hil_request", payload={
        "findings": {"d1": "ok"},
        "draft_answer": "draft",
        "reason": "needs review",
    }))
    hils = [e for e in captured if e.kind == "hil_request" and isinstance(e.message, HilRequestMessage)]
    assert hils
    assert hils[0].message.draft_answer == "draft"
    assert hils[0].message.reason == "needs review"


def test_subagent_lifecycle_emits_dispatch_messages(sink, captured):
    sink(_ev("subagent_start", tags={"name": "coverage_analyst"}))
    sink(_ev("subagent_end", tags={"name": "coverage_analyst"}))
    msgs = [e.message for e in captured if e.kind in {"subagent_start", "subagent_end"}]
    assert all(isinstance(m, SubAgentDispatchMessage) for m in msgs)
    statuses = [m.status for m in msgs]  # type: ignore[attr-defined]
    assert "running" in statuses and "done" in statuses


def test_error_event_routes_to_error_message(sink, captured):
    sink(_ev("error", payload={"error": "boom"}))
    msgs = [e.message for e in captured if e.kind == "append"]
    assert any(isinstance(m, ErrorMessage) for m in msgs)


def test_tool_done_emits_tool_done_event_with_result(sink, captured):
    sink(_ev("tool_call", tags={"name": "qa_deepagent_grep"}, payload={"input": {"pattern": "x"}}))
    sink(_ev("tool_result", tags={"name": "qa_deepagent_grep"}, payload={"output": "match in foo.py:10"}))
    done = [e for e in captured if e.kind == "tool_done"]
    assert done and (done[0].extra or {}).get("result", "") == "match in foo.py:10"
