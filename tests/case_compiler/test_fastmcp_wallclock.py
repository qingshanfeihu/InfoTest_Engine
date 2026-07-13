"""fastmcp_call 墙钟死线:SSE keep-alive 不得无限续租 idle 超时。

2026-07-13 实证:服务端工具调用卡死时,SSE 每隔十几秒一条 keep-alive——urlopen 的
timeout 只是 socket idle 超时,被 keep-alive 不断续租,单发 resp.read() 挂 20min+
(全量回归在床态探针上级联挂死)。修:逐块读+总墙钟=timeout,拿到 result/error
事件即停;死线触发返回 None(调用方按不可达处理)。
"""
from __future__ import annotations

import time
import urllib.request

import main.case_compiler.device_mcp_client as mcp


class _KeepAliveForeverResp:
    """永远只吐 SSE keep-alive、不给 result 的响应(服务端卡死形态)。"""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        time.sleep(0.02)
        return b": keep-alive\n\n"


class _ResultThenCloseResp:
    def __init__(self):
        self._chunks = [
            b'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"text":"OK-ECHO"}]}}\n\n',
            b"",
        ]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self._chunks.pop(0) if self._chunks else b""


def test_wallclock_deadline_stops_keepalive_hang(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=0: _KeepAliveForeverResp())
    t0 = time.monotonic()
    out = mcp.fastmcp_call("apv_ssh_execute", {"host": "x", "command": "show version"},
                           timeout=1)
    elapsed = time.monotonic() - t0
    assert out is None            # 死线触发=不可达语义
    assert elapsed < 5            # 不再无限挂(1s 死线+读粒度余量)


def test_result_event_returns_without_waiting_stream_close(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=0: _ResultThenCloseResp())
    out = mcp.fastmcp_call("apv_ssh_execute", {"host": "x", "command": "show version"},
                           timeout=5)
    assert out == "OK-ECHO"
