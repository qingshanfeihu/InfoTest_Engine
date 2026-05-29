"""Dream task 五道闸单测。

覆盖：功能开关 / 24h 时间门 / 10min 节流 / 5 sessions / PID 锁。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from main.ist_core.memory import dream
from main.ist_core.memory.middleware import reset_session_counter


@pytest.fixture(autouse=True)
def isolated_dream_root(tmp_path, monkeypatch):
    """每个 test 用独立的 memory 根目录，避免 lockfile / counter 串扰。"""
    monkeypatch.setenv("IST_MEMORY_ROOT", str(tmp_path / "memory"))
    
    dream._release_pid_lock()
    yield
    dream._release_pid_lock()


def _set_sessions(n: int):
    counter_path = dream._dream_root() / "session_count"
    counter_path.write_text(str(n), encoding="utf-8")





def test_gate1_dream_disabled_by_env(monkeypatch):
    monkeypatch.setenv("IST_DREAM_ENABLED", "0")
    _set_sessions(10)
    ok, reason = dream.should_run_dream()
    assert ok is False
    assert "IST_DREAM_ENABLED=0" in reason


def test_gate1_memory_disabled_by_env(monkeypatch):
    monkeypatch.setenv("IST_MEMORY_ENABLED", "0")
    _set_sessions(10)
    ok, reason = dream.should_run_dream()
    assert ok is False
    assert "IST_MEMORY_ENABLED=0" in reason


def test_gate1_disable_llm_blocks_dream(monkeypatch):
    monkeypatch.setenv("IST_MEMORY_DISABLE_LLM", "1")
    _set_sessions(10)
    ok, reason = dream.should_run_dream()
    assert ok is False
    assert "DISABLE_LLM" in reason





def test_gate2_blocks_when_recently_ran():
    _set_sessions(10)
    last_run = dream._last_run_path()
    last_run.write_text(str(time.time()), encoding="utf-8")
    ok, reason = dream.should_run_dream()
    assert ok is False
    assert "24h" in reason


def test_gate2_passes_when_old_enough():
    _set_sessions(10)
    last_run = dream._last_run_path()
    
    last_run.write_text(str(time.time() - 25 * 3600), encoding="utf-8")
    ok, _ = dream.should_run_dream()
    assert ok is True





def test_gate4_blocks_below_min_sessions():
    _set_sessions(2)
    ok, reason = dream.should_run_dream()
    assert ok is False
    assert "sessions" in reason


def test_gate4_passes_at_threshold():
    _set_sessions(5)
    ok, _ = dream.should_run_dream()
    assert ok is True


def test_gate4_threshold_overridable_via_env(monkeypatch):
    monkeypatch.setenv("IST_DREAM_MIN_SESSIONS", "1")
    _set_sessions(1)
    ok, _ = dream.should_run_dream()
    assert ok is True





def test_gate5_pid_lock_blocks_concurrent():
    _set_sessions(10)
    ok1, _ = dream.should_run_dream()
    assert ok1 is True

    
    
    ok2, reason2 = dream.should_run_dream()
    assert ok2 is False
    assert "throttled" in reason2 or "PID" in reason2


def test_gate5_releases_after_lock_release():
    _set_sessions(10)
    ok1, _ = dream.should_run_dream()
    assert ok1 is True

    dream._release_pid_lock()
    
    dream._last_run_path().unlink(missing_ok=True)
    _set_sessions(10)
    ok2, _ = dream.should_run_dream()
    assert ok2 is True


def test_gate5_stale_lock_recovered():
    """PID 文件指向已死进程应被回收。"""
    _set_sessions(10)
    pid_path = dream._pid_lock_path()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("99999", encoding="utf-8")
    
    import os
    old = time.time() - 11 * 60
    os.utime(pid_path, (old, old))
    
    ok, reason = dream.should_run_dream()
    assert ok is True, reason
