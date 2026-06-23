"""V3 步骤0：fan-out 并发自适应 + 429 退避（batch_tools）。

验证 auto 模式按 item 数自适应、env 硬覆盖、显式值、夹紧上限，以及 429 退避重试。
"""

from __future__ import annotations

import importlib

import main.ist_core.tools.device.batch_tools as bt


def test_resolve_concurrency_auto_floors_at_default():
    assert bt._resolve_concurrency(0, n_items=1) == bt._DEFAULT_FANOUT
    assert bt._resolve_concurrency(0, n_items=2) == bt._DEFAULT_FANOUT


def test_resolve_concurrency_auto_scales_with_items():
    assert bt._resolve_concurrency(0, n_items=10) == 10


def test_resolve_concurrency_auto_caps_at_max():
    assert bt._resolve_concurrency(0, n_items=100) == bt._MAX_FANOUT


def test_resolve_concurrency_explicit_value_wins_over_auto():
    assert bt._resolve_concurrency(8, n_items=100) == 8


def test_resolve_concurrency_explicit_still_capped():
    assert bt._resolve_concurrency(999, n_items=5) == bt._MAX_FANOUT


def test_resolve_concurrency_env_hard_override(monkeypatch):
    monkeypatch.setenv("IST_FANOUT_CONCURRENCY", "3")
    assert bt._resolve_concurrency(0, n_items=100) == 3
    assert bt._resolve_concurrency(8, n_items=100) == 3


def test_resolve_concurrency_zero_items_auto_is_default():
    assert bt._resolve_concurrency(0, n_items=0) == bt._DEFAULT_FANOUT


def test_is_rate_limit_error_detects_variants():
    assert bt._is_rate_limit_error(Exception("Error code: 429"))
    assert bt._is_rate_limit_error(Exception("rate limit exceeded"))
    assert bt._is_rate_limit_error(Exception("Too Many Requests"))
    assert bt._is_rate_limit_error(Exception("model overloaded"))
    assert not bt._is_rate_limit_error(Exception("connection reset by peer"))
    assert not bt._is_rate_limit_error(Exception("timeout"))


def test_fanout_retries_on_rate_limit_then_succeeds(monkeypatch):
    # 前两次抛 429，第三次成功 → 应重试到成功，不判失败。
    calls = {"n": 0}

    def fake_execute(skill, brief):
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("Error code: 429 Too Many Requests")
        return "ok-output"

    import main.ist_core.skills.loader as loader
    monkeypatch.setattr(loader, "execute_fork_skill", fake_execute)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)  # 不真睡

    out = bt.compile_fanout.invoke({
        "skill": "ist_compile_draft",
        "briefs_json": '[{"key": "c1", "brief": "b"}]',
    })
    import json
    res = json.loads(out)
    assert res[0]["ok"] is True
    assert res[0]["output"] == "ok-output"
    assert calls["n"] == 3


def test_fanout_gives_up_after_max_retries(monkeypatch):
    def always_429(skill, brief):
        raise Exception("429 rate limit")

    import main.ist_core.skills.loader as loader
    monkeypatch.setattr(loader, "execute_fork_skill", always_429)
    monkeypatch.setattr(bt.time, "sleep", lambda s: None)

    import json
    out = bt.compile_fanout.invoke({
        "skill": "ist_compile_draft",
        "briefs_json": '[{"key": "c1", "brief": "b"}]',
    })
    res = json.loads(out)
    assert res[0]["ok"] is False
    assert "限流重试耗尽" in res[0]["output"]
