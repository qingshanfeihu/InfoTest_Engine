"""迁移表门(P1-G1e):非法迁移抛错;pass 锁;派发审计;原子落盘。"""
from __future__ import annotations

import pytest

from main.ist_core.compile_engine import ledger as L


def _led(tmp_path):
    return L.EngineLedger(tmp_path / "engine_ledger.json")


def test_legal_flow(tmp_path):
    led = _led(tmp_path)
    led.transition("a1", L.S_PENDING)
    led.transition("a1", L.S_DISPATCHED)
    led.transition("a1", L.S_PRODUCED)
    led.lock_pass("a1", 123.0)
    assert led.case("a1")["state"] == L.S_PASSED
    assert led.case("a1")["passed_mtime_lock"] == 123.0


def test_passed_is_locked(tmp_path):
    led = _led(tmp_path)
    led.transition("a1", L.S_PENDING)
    led.transition("a1", L.S_DISPATCHED)
    led.transition("a1", L.S_PRODUCED)
    led.lock_pass("a1", 1.0)
    with pytest.raises(L.IllegalTransition, match="passed 卷禁止回炉"):
        led.transition("a1", L.S_PENDING)
    # 双跑翻转显式豁免(E6 778041)
    led.transition("a1", L.S_FAILED_ACTIVE, flip_evidence="double-run flip r1=pass r2=fail")
    assert led.data["audit"]["notes"][-1]["event"] == "pass_flip"


def test_dispatch_audit_scope(tmp_path):
    led = _led(tmp_path)
    for a in ("a1", "a2"):
        led.transition(a, L.S_PENDING)
    led.record_dispatch(["a1", "a2"], round_no=0, allowed_from={L.S_PENDING})
    led.transition("a1", L.S_DISPATCHED)
    led.transition("a1", L.S_PRODUCED)
    with pytest.raises(L.IllegalTransition, match="派发集越界"):
        led.record_dispatch(["a1"], round_no=1, allowed_from={L.S_PENDING})


def test_atomic_save_roundtrip(tmp_path):
    led = _led(tmp_path)
    led.transition("a1", L.S_PENDING)
    led.save()
    led2 = _led(tmp_path)
    assert led2.case("a1")["state"] == L.S_PENDING
