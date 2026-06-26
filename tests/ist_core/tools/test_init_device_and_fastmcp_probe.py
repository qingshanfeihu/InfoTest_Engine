"""编译入口固化 init_device + dev_probe 切新版 FastMCP apv_ssh_execute 的离线单测。

覆盖三处改动（全 mock，不连真设备/跳板机）：
- device_mcp_client.probe_via_fastmcp：SSE 解析 + 解析不出 IP/HTTP 失败回退 None
- device_mcp_client.FrameworkMCPClient.init_device：调用派发
- run_case._do_probe：优先 FastMCP、失败回退老 probe_show
- compile_pipeline._init_device_for_compile：禁用/成功/撞锁/异常 均不阻断编译
- device_mcp_server.tools.init_device：撞单跑锁直接返回 error，不动设备
"""
from __future__ import annotations

import io
import json

import pytest


# ── probe_via_fastmcp ─────────────────────────────────────────────────
def _fake_sse(text: str) -> bytes:
    body = {"jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": text}]}}
    return ("event: message\ndata: " + json.dumps(body) + "\n\n").encode()


def test_probe_via_fastmcp_parses_sse(monkeypatch):
    from main.case_compiler import device_mcp_client as mc

    monkeypatch.setattr(mc, "resolve_device_ip", lambda build="", env=None: "172.16.35.70")

    class _Resp:
        def __init__(self, data):
            self._d = data
        def read(self):
            return self._d
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    text = ("=== apv_ssh_execute ===\nhost=172.16.35.70  mode=show\n"
            "command: show sdns pool method primary\nstatus: error\n"
            "--- output ---\nshow sdns pool method primary \n              ^\n")
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=30: _Resp(_fake_sse(text)))

    r = mc.probe_via_fastmcp("show sdns pool method primary", build="b")
    assert isinstance(r, dict)
    assert r["device_ip"] == "172.16.35.70"
    assert "status: error" in r["text"]
    assert "^" in r["text"]            # 对齐 ^ 保留（不剥回显）


def test_fastmcp_call_generic_parses_result(monkeypatch):
    """通用 fastmcp_call：迁移基座——任意工具走它，解析 SSE result 文本。"""
    from main.case_compiler import device_mcp_client as mc

    class _Resp:
        def __init__(self, data):
            self._d = data
        def read(self):
            return self._d
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    body = {"jsonrpc": "2.0", "id": 1,
            "result": {"content": [{"type": "text", "text": "OK-TEXT"}]}}
    sse = ("event: message\ndata: " + json.dumps(body) + "\n\n").encode()
    import urllib.request
    captured = {}

    def _fake_urlopen(req, timeout=30):
        captured["body"] = json.loads(req.data.decode())
        return _Resp(sse)
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    out = mc.fastmcp_call("init_device", {"device_count": 2})
    assert out == "OK-TEXT"
    assert captured["body"]["params"]["name"] == "init_device"
    assert captured["body"]["params"]["arguments"]["device_count"] == 2


def test_fastmcp_call_none_on_error(monkeypatch):
    from main.case_compiler import device_mcp_client as mc
    import urllib.request

    def _boom(req, timeout=30):
        raise OSError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert mc.fastmcp_call("apv_ssh_execute", {"host": "1.2.3.4", "command": "show version"}) is None


def test_probe_via_fastmcp_none_when_no_device_ip(monkeypatch):
    from main.case_compiler import device_mcp_client as mc
    monkeypatch.setattr(mc, "resolve_device_ip", lambda build="", env=None: None)
    assert mc.probe_via_fastmcp("show version", build="b") is None


def test_probe_via_fastmcp_none_on_http_error(monkeypatch):
    from main.case_compiler import device_mcp_client as mc
    monkeypatch.setattr(mc, "resolve_device_ip", lambda build="", env=None: "1.2.3.4")
    import urllib.request

    def _boom(req, timeout=30):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert mc.probe_via_fastmcp("show version", build="b") is None


# ── FrameworkMCPClient.init_device ────────────────────────────────────
def test_client_init_device_dispatches(monkeypatch):
    from main.case_compiler import device_mcp_client as mc

    captured = {}

    class _FakeClient(mc.FrameworkMCPClient):
        def __init__(self):  # 不连跳板机
            pass
        def call(self, calls):
            captured["calls"] = calls
            return {"init_device": {"initialized": 2, "failed": 0, "total": 2, "details": []}}

    res = _FakeClient().init_device(device_count=2)
    assert res["initialized"] == 2
    name, args = captured["calls"][0]
    assert name == "init_device"
    assert args["device_count"] == 2


# ── run_case._do_probe：优先 FastMCP，失败回退 ────────────────────────
def test_do_probe_prefers_fastmcp(monkeypatch):
    from main.case_compiler import device_mcp_client as mc
    from main.ist_core.tools.device import run_case

    monkeypatch.setattr(mc, "probe_via_fastmcp",
                        lambda cmd, build="": {"text": "status: error\n^", "device_ip": "1.2.3.4"})
    out = run_case._do_probe("show sdns pool method primary")
    assert "fastmcp apv_ssh" in out
    assert "status: error" in out


def test_do_probe_falls_back_to_probe_show(monkeypatch):
    from main.case_compiler import device_mcp_client as mc
    from main.ist_core.tools.device import run_case

    monkeypatch.setattr(mc, "probe_via_fastmcp", lambda cmd, build="": None)

    class _FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def probe_show(self, command, build=""):
            return {"command": command, "output": "fallback-output", "device_ip": "1.2.3.4"}

    monkeypatch.setattr(mc, "FrameworkMCPClient", _FakeClient)
    out = run_case._do_probe("show version")
    assert "fallback-output" in out
    assert "fastmcp" not in out


# ── compile_pipeline._init_device_for_compile ─────────────────────────
def test_init_device_for_compile_disabled(monkeypatch):
    import importlib
    cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")
    monkeypatch.setenv("IST_COMPILE_INIT_DEVICE", "0")
    res = {"phases": []}
    cp._init_device_for_compile(res)
    # 禁用时不应调用任何 client；phases 不记 init_device 成败
    assert not any("init_device:" in p for p in res["phases"])


def test_init_device_for_compile_success(monkeypatch):
    from main.case_compiler import device_mcp_client as mc
    import importlib
    cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")
    monkeypatch.setenv("IST_COMPILE_INIT_DEVICE", "1")

    class _FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def init_device(self, device_count=0, device_index=-1):
            return {"initialized": 1, "failed": 0, "total": 1, "details": []}

    monkeypatch.setattr(mc, "FrameworkMCPClient", _FakeClient)
    res = {"phases": []}
    cp._init_device_for_compile(res)
    assert any("init_device: 1/1" in p for p in res["phases"])


def test_init_device_for_compile_busy_does_not_block(monkeypatch):
    from main.case_compiler import device_mcp_client as mc
    import importlib
    cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")
    monkeypatch.setenv("IST_COMPILE_INIT_DEVICE", "1")

    class _FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def init_device(self, device_count=0, device_index=-1):
            return {"error": "another run in progress (lock held by probe_1)"}

    monkeypatch.setattr(mc, "FrameworkMCPClient", _FakeClient)
    res = {"phases": []}
    cp._init_device_for_compile(res)   # 不抛
    assert any("init_device: 失败" in p for p in res["phases"])


def test_init_device_for_compile_client_unavailable(monkeypatch):
    """FrameworkMCPClient 不可用（paramiko 缺等）也不阻断编译。"""
    import builtins
    import importlib
    cp = importlib.import_module("main.ist_core.tools.device.compile_pipeline")
    monkeypatch.setenv("IST_COMPILE_INIT_DEVICE", "1")
    real_import = builtins.__import__

    def _fake_import(name, *a, **k):
        if name == "main.case_compiler.device_mcp_client":
            raise ImportError("no paramiko")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    res = {"phases": []}
    cp._init_device_for_compile(res)   # 不抛
    assert any("跳过" in p for p in res["phases"])


# ── _probe_uncacheable：CLI 无效命令可缓存(防 churn)，传输失败不缓存 ────
def test_probe_uncacheable_cli_invalid_is_cacheable():
    """无效命令(status:error + --- output --- 对齐^)是确定性结果 → 可缓存，绝不能反复真探。"""
    from main.ist_core.tools.device import run_case
    cli_invalid = ("=== dev_probe (fastmcp apv_ssh) ===\n=== apv_ssh_execute ===\n"
                   "host=172.16.35.70  mode=show\ncommand: show sdns pool method primary\n"
                   "status: error\n--- output ---\nshow sdns pool method primary \n              ^\n")
    assert run_case._probe_uncacheable(cli_invalid) is False


def test_probe_uncacheable_transport_fail_not_cached():
    from main.ist_core.tools.device import run_case
    ssh_fail = "=== dev_probe (fastmcp apv_ssh) ===\nerror: SSH to 172.16.35.70 failed: timed out"
    assert run_case._probe_uncacheable(ssh_fail) is True
    restapi_fail = ("=== dev_probe (fastmcp apv_ssh) ===\nstatus: error\n--- error ---\n"
                    "REST API connection to 172.16.35.70:9997 failed: Connection refused")
    assert run_case._probe_uncacheable(restapi_fail) is True


def test_probe_uncacheable_old_probe_show_error_not_cached():
    """老 probe_show 错误分支(status:error 但无 --- output ---)→ 不缓存。"""
    from main.ist_core.tools.device import run_case
    old_err = "=== dev_probe ===\ncommand: show x\nstatus: error\ncannot resolve device connection"
    assert run_case._probe_uncacheable(old_err) is True


def test_probe_uncacheable_lock_and_empty_and_valid():
    from main.ist_core.tools.device import run_case
    assert run_case._probe_uncacheable("another run in progress (lock held by probe_1)") is True
    assert run_case._probe_uncacheable("") is True
    valid = ("=== dev_probe (fastmcp apv_ssh) ===\nstatus: success\n--- output ---\n"
             "Software Version : InfosecOS Beta.APV-HG-K.10.5.0.568")
    assert run_case._probe_uncacheable(valid) is False


# ── Option Y：客户端 deliver（_deliver_clientside）────────────────────
def test_deliver_clientside_staging_and_symlink(tmp_path, monkeypatch):
    """客户端 deliver：sftp 写 .tmp → mv case.xlsx + 软链 test_xlsx.py，返回 staging 结构。"""
    from main.case_compiler import device_mcp_client as mc

    xlsx = tmp_path / "case.xlsx"
    xlsx.write_bytes(b"PK\x03\x04fake-xlsx-bytes")

    cmds = []
    written = {}

    class _SFTPFile:
        def __init__(self, store, path):
            self._store, self._path = store, path
        def write(self, data):
            self._store[self._path] = data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class _SFTP:
        def open(self, path, mode="r"):
            return _SFTPFile(written, path)
        def close(self):
            pass

    class _O:
        def __init__(self, s=b""):
            self._s = s
        def read(self):
            return self._s

    class _FakeC:
        def exec_command(self, cmd, timeout=30):
            cmds.append(cmd)
            out = b"OK\n" if "echo OK" in cmd else b""
            return (None, _O(out), _O(b""))
        def open_sftp(self):
            return _SFTP()

    client = mc.FrameworkMCPClient.__new__(mc.FrameworkMCPClient)
    client._c = _FakeC()

    res = client._deliver_clientside("sdns", "12345", str(xlsx))
    assert res.get("error") is None
    assert res["staging_dir"].endswith("ist_staging_sdns/12345")
    assert res["bytes"] == len(b"PK\x03\x04fake-xlsx-bytes")
    # sftp 写到 .tmp
    assert any(p.endswith("case.xlsx.tmp") for p in written)
    # 命令含 mkdir / mv 原子重命名 / ln 软链
    joined = "\n".join(cmds)
    assert "mkdir -p" in joined
    assert "mv -f" in joined and "case.xlsx" in joined
    assert "ln -sfn ../../../../lib/test_xlsx.py" in joined


def test_deliver_clientside_read_error():
    from main.case_compiler import device_mcp_client as mc
    client = mc.FrameworkMCPClient.__new__(mc.FrameworkMCPClient)
    client._c = None
    res = client._deliver_clientside("sdns", "1", "/nonexistent/case.xlsx")
    assert "read xlsx failed" in res.get("error", "")


# ── framework_ready device-aware 健康检查 ─────────────────────────────
class _FakeSSH:
    """假 SSH 通道：按命令内容返回设备 IP / :22 OPEN|CLOSED。"""
    def __init__(self, ip="172.16.35.70", port22="OPEN", raise_on=None):
        self._ip, self._p22, self._raise_on = ip, port22, raise_on

    def exec_command(self, cmd, timeout=8):
        if self._raise_on and self._raise_on in cmd:
            raise RuntimeError("boom")
        out = ""
        if "parse_device_conn" in cmd:
            out = (self._ip or "") + "\n"
        elif "/dev/tcp" in cmd:
            out = self._p22 + "\n"

        class _O:
            def __init__(self, s):
                self._s = s.encode()
            def read(self):
                return self._s
        return (None, _O(out), _O(""))


def test_device_reachable_open():
    from main.case_compiler import device_mcp_client as mc
    env = type("E", (), {"server_path": "/home/test/mcp_server/server.py"})()
    assert mc._device_reachable_via(_FakeSSH(port22="OPEN"), env) is True


def test_device_reachable_closed_excludes_env():
    """设备 :22 不可达（如 79 床 down）→ False，池剔除。"""
    from main.case_compiler import device_mcp_client as mc
    env = type("E", (), {"server_path": "/home/test/mcp_server/server.py"})()
    assert mc._device_reachable_via(_FakeSSH(port22="CLOSED"), env) is False


def test_device_reachable_no_ip_is_conservative_pass():
    from main.case_compiler import device_mcp_client as mc
    env = type("E", (), {"server_path": "/home/test/mcp_server/server.py"})()
    assert mc._device_reachable_via(_FakeSSH(ip=""), env) is True


def test_device_reachable_exec_error_is_conservative_pass():
    from main.case_compiler import device_mcp_client as mc
    env = type("E", (), {"server_path": "/home/test/mcp_server/server.py"})()
    assert mc._device_reachable_via(_FakeSSH(raise_on="parse_device_conn"), env) is True


# ── server 侧 init_device 单跑锁 ──────────────────────────────────────
def test_server_init_device_busy_returns_error_without_touching_device(monkeypatch):
    """撞锁时 init_device 直接返回 error，绝不进 _init_one_device（不动设备）。"""
    tools = pytest.importorskip("main.device_mcp_server.tools")

    monkeypatch.setattr(tools, "_read_conf_text",
                        lambda: "[comm]\nssh_ips = 172.16.35.70\n[dev]\nhostname = APV\n")
    monkeypatch.setattr(tools, "_ensure_dirs", lambda: None)
    monkeypatch.setattr(tools, "_acquire_lock", lambda task_id: None)   # 锁被占
    monkeypatch.setattr(tools, "_read_lock", lambda: ("probe_999", 123))

    touched = {"n": 0}
    monkeypatch.setattr(tools, "_init_one_device",
                        lambda *a, **k: touched.__setitem__("n", touched["n"] + 1))

    res = tools.init_device()
    assert "another run in progress" in res.get("error", "")
    assert touched["n"] == 0            # 没动设备
