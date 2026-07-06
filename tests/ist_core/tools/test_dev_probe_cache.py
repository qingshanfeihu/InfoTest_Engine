"""dev_probe **run 作用域 single-flight** 守护(替代旧静/动关键字黑名单)。

设计(对抗评审定稿):不判命令静/动;一次 compile run 内同一命令只**真探一次**(single-flight)、
其余并发 draft 等结果;run 结束即弃、**跨 run 不复用**;**无 run 上下文裸探不缓**(main agent 手动探);
失败不缓、留待重探且等待者不死锁。mock `_do_probe`,不碰设备。

命令占位符用 "show cmd-a" / "show cmd-b" 等抽象串——缓存机制对命令内容无依赖,任意字符串均适用。
"""
from __future__ import annotations

import threading
import time

import main.ist_core.tools.device.run_case as rc

# 抽象占位符,不含任何领域词,让测试证明缓存对任意命令串均成立
_CMD_A = "show cmd-a"
_CMD_B = "show cmd-b"
_CMD_A_UPPER = "SHOW  CMD-A"   # 规范化后与 _CMD_A 同 key


def _mock_probe(monkeypatch):
    """把 _do_probe 换成按命令计数的 mock,返回 calls(真探记录)。"""
    calls: list[str] = []

    def _fake(cmd):
        calls.append(cmd)
        return f"=== dev_probe ===\ncommand: {cmd}\n--- output ---\nok-{len(calls)}"

    monkeypatch.setattr(rc, "_do_probe", _fake)
    return calls


def test_single_flight_same_command_probes_once(monkeypatch):
    """同 run 内多次探同命令(含大小写/空白规范化) → 只真探一次,其余命中缓存。"""
    calls = _mock_probe(monkeypatch)
    rc._current_run_token.set(rc._new_run_token())
    r1 = rc.dev_probe.invoke({"command": _CMD_A})
    r2 = rc.dev_probe.invoke({"command": _CMD_A})
    r3 = rc.dev_probe.invoke({"command": _CMD_A_UPPER})  # 规范化 → 同 key
    assert calls == [_CMD_A]           # 只真探一次
    assert r1 == r2 == r3


def test_no_run_context_always_probes(monkeypatch):
    """无 compile run 上下文(main agent 手动探)→ 每次裸探、不缓。"""
    calls = _mock_probe(monkeypatch)
    rc._current_run_token.set(None)
    rc.dev_probe.invoke({"command": _CMD_A})
    rc.dev_probe.invoke({"command": _CMD_A})
    assert len(calls) == 2             # 每次都真探


def test_cross_run_not_reused(monkeypatch):
    """跨 run(新 run_token)不复用——run 结束即弃。"""
    calls = _mock_probe(monkeypatch)
    rc._current_run_token.set(rc._new_run_token())
    rc.dev_probe.invoke({"command": _CMD_B})
    rc._current_run_token.set(rc._new_run_token())  # 新 run
    rc.dev_probe.invoke({"command": _CMD_B})
    assert len(calls) == 2             # 两次 run 各探一次


def test_different_commands_both_probed(monkeypatch):
    """同 run 内不同命令互不干扰,各真探一次。"""
    calls = _mock_probe(monkeypatch)
    rc._current_run_token.set(rc._new_run_token())
    rc.dev_probe.invoke({"command": _CMD_A})
    rc.dev_probe.invoke({"command": _CMD_B})
    rc.dev_probe.invoke({"command": _CMD_A})  # 命中缓存
    assert calls == [_CMD_A, _CMD_B]   # A/B 各探一次,第三次命中


def test_error_not_cached_reprobe(monkeypatch):
    """首探失败不缓,同命令下次重探。"""
    seq = {"n": 0}

    def _fake(cmd):
        seq["n"] += 1
        return "error: device_busy" if seq["n"] == 1 else f"=== dev_probe ===\ncommand: {cmd}\nok"

    monkeypatch.setattr(rc, "_do_probe", _fake)
    rc._current_run_token.set(rc._new_run_token())
    r1 = rc.dev_probe.invoke({"command": _CMD_A})
    r2 = rc.dev_probe.invoke({"command": _CMD_A})
    assert r1.startswith("error")          # 首探失败
    assert not r2.startswith("error")      # 重探成功(失败没被缓)
    assert seq["n"] == 2


def test_concurrent_single_flight(monkeypatch):
    """并发 5 线程探同命令(同 run_token)→ 真探一次,其余等结果(single-flight)。"""
    calls: list[str] = []
    lock = threading.Lock()

    def _slow(cmd):
        with lock:
            calls.append(cmd)
        time.sleep(0.2)                    # 慢探,让其它线程进入 wait
        return f"=== dev_probe ===\ncommand: {cmd}\nok"

    monkeypatch.setattr(rc, "_do_probe", _slow)
    token = rc._new_run_token()
    results: dict[int, str] = {}

    def worker(i):
        rc._current_run_token.set(token)   # 模拟 _compile_one_case 内 set
        results[i] = rc.dev_probe.invoke({"command": _CMD_A})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1                 # 5 并发只真探一次
    assert len(set(results.values())) == 1 # 都拿同一结果


def test_annotate_if_empty_probe_adds_timing_hint():
    """探针回显实质为空（裸提示符/无输出）→ 附时机语义提示（OBS-15：编译期干净态，探统计恒空）。"""
    from main.ist_core.tools.device.run_case import _annotate_if_empty_probe
    # 裸提示符（fastmcp 路径实测形态）
    out = _annotate_if_empty_probe("=== dev_probe (fastmcp apv_ssh) ===\ncommand: show statistics x\nstatus: ok\nAPV#")
    assert "干净态" in out and "有效域" in out
    # (无输出) 形态（stdio 路径）
    out2 = _annotate_if_empty_probe("=== dev_probe ===\ncommand: show x\n--- 设备回显(经跳转机)---\n(无输出)")
    assert "干净态" in out2
    # 有实质内容 → 原样返回不加提示
    out3 = _annotate_if_empty_probe("=== dev_probe ===\ncommand: show x\n--- 设备回显(经跳转机)---\nPool Name: p1  Hit: 3")
    assert "干净态" not in out3 and out3.endswith("Hit: 3")
