"""主循环连接韧性 + 心跳（resilience）。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from main.ist_core import resilience as R


def test_is_connection_error_detects():
    assert R._is_connection_error(Exception("APIConnectionError: Connection error."))
    assert R._is_connection_error(Exception("Max retries exceeded"))
    assert R._is_connection_error(Exception("read timed out"))
    assert R._is_connection_error(Exception("502 Bad Gateway"))
    assert not R._is_connection_error(Exception("invalid argument"))
    assert not R._is_connection_error(ValueError("bad json"))


def test_run_with_resilience_success_no_retry():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return "ok"

    assert R.run_with_resilience(fn) == "ok"
    assert calls["n"] == 1


def test_run_with_resilience_retries_connection_error(monkeypatch):
    monkeypatch.setenv("IST_MAINLOOP_RETRIES", "3")
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("APIConnectionError: Connection error.")
        return "recovered"

    assert R.run_with_resilience(fn) == "recovered"
    assert calls["n"] == 3


def test_run_with_resilience_non_connection_error_immediate_raise(monkeypatch):
    monkeypatch.setenv("IST_MAINLOOP_RETRIES", "3")
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("business bug")

    with pytest.raises(ValueError):
        R.run_with_resilience(fn)
    assert calls["n"] == 1  # 不重试业务错误


def test_run_with_resilience_exhausts_and_raises(monkeypatch):
    monkeypatch.setenv("IST_MAINLOOP_RETRIES", "2")
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise Exception("connection reset")

    with pytest.raises(Exception, match="connection reset"):
        R.run_with_resilience(fn)
    assert calls["n"] == 3  # 1 + 2 retries


def test_retries_disabled_by_env(monkeypatch):
    monkeypatch.setenv("IST_MAINLOOP_RETRIES", "0")
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise Exception("connection error")

    with pytest.raises(Exception):
        R.run_with_resilience(fn)
    assert calls["n"] == 1


def test_heartbeat_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("IST_HEARTBEAT", "1")
    hb_path = tmp_path / "hb.json"
    with R.Heartbeat(path=hb_path, interval_s=0.05) as hb:
        hb.set_note("test-note")
        time.sleep(0.12)
    assert hb_path.exists()
    d = json.loads(hb_path.read_text())
    assert d["pid"] > 0
    assert "elapsed_s" in d
    assert d["note"] == "test-note"
    assert d["alive"] is False  # 退出后最后一次写 alive=False


def test_heartbeat_disabled_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("IST_HEARTBEAT", "0")
    hb_path = tmp_path / "hb.json"
    with R.Heartbeat(path=hb_path, interval_s=0.05):
        time.sleep(0.1)
    assert not hb_path.exists()


def test_record_main_activity_writes_jsonl(tmp_path, monkeypatch):
    log = tmp_path / "main_activity.jsonl"
    monkeypatch.setenv("IST_MAIN_ACTIVITY", "1")
    monkeypatch.setattr(R, "_MAIN_ACTIVITY_PATH", str(log))
    R.record_main_activity("tool_start", tool_name="qa_compile_prep", detail="dongkl.txt")
    R.record_main_activity("tool_end", tool_name="qa_compile_prep")
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    r0 = json.loads(lines[0])
    assert r0["event"] == "tool_start"
    assert r0["tool"] == "qa_compile_prep"
    assert "dongkl" in r0["detail"]


def test_record_main_activity_updates_heartbeat_note(tmp_path, monkeypatch):
    log = tmp_path / "ma.jsonl"
    monkeypatch.setattr(R, "_MAIN_ACTIVITY_PATH", str(log))
    monkeypatch.setenv("IST_MAIN_ACTIVITY", "1")
    hb = R.Heartbeat(path=tmp_path / "hb.json", interval_s=10)
    R.set_active_heartbeat(hb)
    try:
        R.record_main_activity("tool_start", tool_name="qa_cluster_intents")
        assert hb._note == "tool=qa_cluster_intents"
    finally:
        R.set_active_heartbeat(None)


def test_record_main_activity_disabled(tmp_path, monkeypatch):
    log = tmp_path / "ma.jsonl"
    monkeypatch.setattr(R, "_MAIN_ACTIVITY_PATH", str(log))
    monkeypatch.setenv("IST_MAIN_ACTIVITY", "0")
    R.record_main_activity("tool_start", tool_name="x")
    assert not log.exists()
