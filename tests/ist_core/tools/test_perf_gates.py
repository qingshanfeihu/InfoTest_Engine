"""性能病灶回归(2026-07-04 dongkl 闭环取证驱动):run-identity 绑定。

实测浪费源:staging 目录跨 run 复用,被打断执行的旧日志被新 digest 收割成假结果
(0/34、1/34 两轮),假 fail 又触发无效修复轮 → run-identity(deliver 时刻跳板机 epoch)
绑定,旧日志判 stale 不产 verdict。
"""
from __future__ import annotations

from main.case_compiler.device_mcp_client import FrameworkMCPClient


class _FakeSSH:
    """离线仿真 fetch_batch_details 的 SSH 通道(协议:<<<CASE:aid|mtime>>>body)。"""
    def __init__(self, raw: str):
        self._raw = raw

    def exec_command(self, cmd, timeout=0):
        raw = self._raw

        class _O:
            def read(self):
                return raw.encode()

        return None, _O(), None


def test_fetch_batch_details_marks_stale_logs():
    fake = FrameworkMCPClient.__new__(FrameworkMCPClient)
    fake._c = _FakeSSH("<<<CASE:OLD1|100>>>#### Fail Num 1"
                       "<<<CASE:NEW1|9999999999>>>#### Success Num 1")
    d = fake.fetch_batch_details("SUBMIT", min_epoch=5000)
    assert d["OLD1"] == FrameworkMCPClient.STALE_LOG_MARK
    assert "Success" in d["NEW1"]
    # min_epoch=0(不启用)→ 全收,兼容旧行为
    d2 = fake.fetch_batch_details("SUBMIT", min_epoch=0)
    assert "Fail" in d2["OLD1"]
