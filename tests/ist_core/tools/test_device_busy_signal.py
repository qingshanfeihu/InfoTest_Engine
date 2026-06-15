"""设备忙(撞锁)信号链路：server _busy_info → client run_and_wait → run_batch/run_case verdict。

需求：上机受跳转机框架全局锁约束(同一时刻只能跑一个)。当 ist 在上一个用例还在
验证时又来提交，server 必须抛**结构化 busy 信号**(正在验证哪个 autoid、已跑多久)，
client 原样上抛、不静默放弃、不误判为提交失败，最终 agent 看到 verdict=busy 自行
决定等待/重试/上报。
"""

from __future__ import annotations

import importlib.util
import time

import pytest


def _load_server_tools():
    spec = importlib.util.spec_from_file_location(
        "mcp_tools_under_test", "main/device_mcp_server/tools.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── server 端 _busy_info ────────────────────────────────────────────────

def test_busy_info_parses_autoid_and_elapsed_from_task_id():
    m = _load_server_tools()
    started = int(time.time()) - 37
    info = m._busy_info((f"ist_sdns_203031753342777976_{started}", 12345))
    assert info["error"] == "device_busy" and info["busy"] is True
    assert info["running_autoid"] == "203031753342777976"
    assert 30 <= info["elapsed_s"] <= 60          # 约 37s，给抖动余量
    assert "203031753342777976" in info["message"]
    assert "环境忙" in info["message"]


def test_busy_info_handles_missing_lock_gracefully():
    m = _load_server_tools()
    info = m._busy_info(None)
    assert info["error"] == "device_busy" and info["busy"] is True
    assert info["running_autoid"] == ""          # 未知不崩
    assert info["elapsed_s"] is None


# ── client run_and_wait 上抛 busy（不静默放弃） ─────────────────────────

class _BusyClient:
    """模拟 run 撞锁返回 busy 结构的 client（只覆写 run）。"""

    def __init__(self, busy_payload):
        self._busy = busy_payload

    def run(self, module, autoid, build):
        return self._busy


def test_run_and_wait_surfaces_busy_not_submit_failed(monkeypatch):
    from main.case_compiler.device_mcp_client import FrameworkMCPClient
    busy = {"error": "device_busy", "busy": True,
            "running_autoid": "B999", "elapsed_s": 88,
            "message": "环境忙：正在验证用例 B999，已运行 88s。"}
    # 直接驱动 run_and_wait 的逻辑：绑一个假 run 到实例上
    inst = FrameworkMCPClient.__new__(FrameworkMCPClient)
    inst.run = lambda module, autoid, build: busy            # type: ignore[assignment]
    out = FrameworkMCPClient.run_and_wait(inst, "sdns", "B999", "b1", ["B999"])
    assert out["busy"] is True and out["error"] == "device_busy"
    assert out["running_autoid"] == "B999" and out["elapsed_s"] == 88
    assert "B999" in out["message"]


def test_run_and_wait_still_reports_real_submit_failure(monkeypatch):
    from main.case_compiler.device_mcp_client import FrameworkMCPClient
    inst = FrameworkMCPClient.__new__(FrameworkMCPClient)
    inst.run = lambda module, autoid, build: {"error": "boom"}  # 非 busy 的真失败
    out = FrameworkMCPClient.run_and_wait(inst, "sdns", "X1", "b1", ["X1"])
    assert out["error"].startswith("submit failed") and "boom" in out["error"]
    assert not out.get("busy")
