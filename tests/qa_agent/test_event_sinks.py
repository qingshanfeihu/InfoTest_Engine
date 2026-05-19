from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from main.qa_agent.events import EventBus
from main.qa_agent.sinks import CLISink, JsonlFileSink, LangSmithSink


def test_sinks_package_exports_all_public_sinks() -> None:
    assert CLISink is not None
    assert JsonlFileSink is not None
    assert LangSmithSink is not None


def test_jsonl_sink_roundtrip(tmp_path: Path) -> None:
    sink = JsonlFileSink(log_dir=tmp_path)
    bus = EventBus(run_id="rt-123")
    bus.subscribe(sink)

    bus.emit("run_start", payload={})
    bus.emit("tool_call", payload={"name": "qa_search_product_kb"}, tags={"doc_type": "feature_json"})
    bus.emit("llm_token", payload={"content": "Hello"})
    bus.emit("run_end", payload={})
    sink.close()

    path = tmp_path / "run-rt-123.jsonl"
    assert path.exists()
    parsed = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [event["kind"] for event in parsed] == ["run_start", "tool_call", "llm_token", "run_end"]
    assert parsed[1]["tags"]["doc_type"] == "feature_json"
    assert parsed[2]["payload"]["content"] == "Hello"


def test_cli_sink_replay_preserves_order(tmp_path: Path, capsys) -> None:
    sink = JsonlFileSink(log_dir=tmp_path)
    bus = EventBus(run_id="replay-01")
    bus.subscribe(sink)

    bus.emit("run_start", payload={})
    bus.emit("node_start", payload={}, tags={"node": "qa_node"})
    bus.emit("tool_call", payload={"name": "qa_search_product_kb"})
    bus.emit("tool_result", payload={"output": "..."})
    bus.emit("node_end", payload={}, tags={"node": "qa_node"})
    bus.emit("run_end", payload={})
    sink.close()

    replay = CLISink(verbose=True, no_color=True)
    replay.replay(str(tmp_path / "run-replay-01.jsonl"))

    output = capsys.readouterr().out
    markers = ["[run_start]", "[node_start]", "[tool_call]", "[tool_result]", "[node_end]", "[run_end]"]
    positions = [output.find(marker) for marker in markers]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)


def test_cli_sink_token_flush_preserves_content() -> None:
    sink = CLISink(verbose=False, no_color=True, throttle_ms=0)

    buf = io.StringIO()
    orig_stdout = sys.stdout
    sys.stdout = buf
    try:
        for ch in "Hello, world!":
            sink({"kind": "llm_token", "payload": {"content": ch}, "run_id": "x", "seq": 1, "ts": "", "tags": {}})
        sink({"kind": "run_end", "payload": {}, "run_id": "x", "seq": 2, "ts": "", "tags": {}})
    finally:
        sys.stdout = orig_stdout

    assert "Hello, world!" in buf.getvalue()


def test_langsmith_sink_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)

    sink = LangSmithSink()

    assert sink.enabled is False
    sink({"kind": "run_start", "payload": {}, "run_id": "x", "seq": 1, "ts": "", "tags": {}})
