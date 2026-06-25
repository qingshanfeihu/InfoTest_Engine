"""环境池守护测试：load_environments 开关/覆盖 + acquire 认领/跳过/超时/回退 + 客户端参数化。

不打真 SSH——_healthy / _try_lock / paramiko 全 mock 掉，只测调度与参数化逻辑。
"""

from __future__ import annotations

import pytest

from main.case_compiler import config, env_pool
from main.case_compiler import device_mcp_client as dmc


# ── config.load_environments ────────────────────────────────────────────────

def test_pool_disabled_returns_single_current_env(monkeypatch):
    """默认（未启用）→ 单环境 = 现役跳板机，行为同今天。"""
    monkeypatch.delenv("IST_ENV_POOL_ENABLED", raising=False)
    monkeypatch.delenv("IST_JUMPHOST_HOST", raising=False)
    config.get_config(reload=True)
    envs = config.load_environments()
    assert len(envs) == 1
    assert envs[0].jumphost == config.get_config().jumphost.host


def test_pool_enabled_returns_four_defaults(monkeypatch):
    monkeypatch.setenv("IST_ENV_POOL_ENABLED", "1")
    monkeypatch.delenv("IST_ENV_POOL_HOSTS", raising=False)
    config.get_config(reload=True)
    envs = config.load_environments()
    hosts = [e.jumphost for e in envs]
    assert hosts == config._DEFAULT_POOL_HOSTS
    assert [e.id for e in envs] == ["env-103", "env-93", "env-79", "env-105"]
    # 克隆环境：user/路径/server_cmd 全一致
    assert all(e.server_path == envs[0].server_path for e in envs)


def test_pool_hosts_override_and_dedup(monkeypatch):
    monkeypatch.setenv("IST_ENV_POOL_ENABLED", "1")
    monkeypatch.setenv("IST_ENV_POOL_HOSTS", "1.2.3.4, 5.6.7.8 , 1.2.3.4")
    config.get_config(reload=True)
    envs = config.load_environments()
    assert [e.jumphost for e in envs] == ["1.2.3.4", "5.6.7.8"]  # 去重保序


# ── env_pool.acquire ────────────────────────────────────────────────────────

def _fake_pool(monkeypatch, env_ids):
    envs = [config.Environment(id=i, jumphost=i.replace("env-", "10.0.0.")) for i in env_ids]
    monkeypatch.setattr(config, "load_environments", lambda: envs)
    monkeypatch.setattr(env_pool, "_healthy", lambda e, **k: True)
    locked: set[str] = set()

    def fake_lock(eid):
        if eid in locked:
            return None
        locked.add(eid)
        return ("fh", eid)

    monkeypatch.setattr(env_pool, "_try_lock", fake_lock)
    monkeypatch.setattr(env_pool, "_unlock", lambda fh: locked.discard(fh[1]))
    return locked


def test_acquire_yields_and_releases(monkeypatch):
    locked = _fake_pool(monkeypatch, ["env-a", "env-b"])
    with env_pool.acquire() as e:
        assert e.id == "env-a"
        assert "env-a" in locked
    assert not locked  # 退出释放


def test_acquire_skips_busy_picks_other(monkeypatch):
    _fake_pool(monkeypatch, ["env-a", "env-b"])
    with env_pool.acquire() as e1:
        assert e1.id == "env-a"
        with env_pool.acquire() as e2:
            assert e2.id == "env-b"  # env-a 被占 → 选下一个


def test_acquire_all_busy_times_out(monkeypatch):
    _fake_pool(monkeypatch, ["env-a"])
    with env_pool.acquire():            # 占住唯一环境
        with pytest.raises(TimeoutError):
            with env_pool.acquire(timeout=0.05, poll_s=0.01):
                pass


def test_acquire_falls_back_when_none_healthy(monkeypatch):
    _fake_pool(monkeypatch, ["env-103", "env-93"])
    monkeypatch.setattr(env_pool, "_healthy", lambda e, **k: False)  # 全不就绪
    with env_pool.acquire() as e:
        assert e.id == "env-103"  # 回退首个（现役），不整体卡死


def test_try_lock_roundtrip(monkeypatch, tmp_path):
    """真 fcntl 锁：拿→释放→可再拿。"""
    monkeypatch.setattr(env_pool, "_LOCK_DIR", tmp_path)
    fh = env_pool._try_lock("env-x")
    assert fh is not None
    env_pool._unlock(fh)
    fh2 = env_pool._try_lock("env-x")
    assert fh2 is not None
    env_pool._unlock(fh2)


# ── FrameworkMCPClient(env) 参数化 ──────────────────────────────────────────

def test_client_connects_to_env_jumphost(monkeypatch):
    monkeypatch.setenv("IST_JUMPHOST_PASS", "x")
    seen = {}

    class FakeSSH:
        def set_missing_host_key_policy(self, *a):
            pass

        def connect(self, host, port=22, username=None, password=None, **k):
            seen["host"], seen["port"], seen["user"] = host, port, username

        def close(self):
            pass

    import paramiko
    monkeypatch.setattr(paramiko, "SSHClient", lambda: FakeSSH())

    env = config.Environment(id="env-93", jumphost="10.4.127.93", ssh_user="test")
    c = dmc.FrameworkMCPClient(env)
    assert seen["host"] == "10.4.127.93" and seen["user"] == "test"
    assert c._server_cmd == env.server_cmd

    c2 = dmc.FrameworkMCPClient()  # legacy: env=None → 模块级现役单环境
    assert seen["host"] == dmc.JUMPHOST
    assert c2._server_cmd == dmc.SERVER_CMD


# ── 真并发：N 线程同时 acquire（真 fcntl 锁），证明分散到不同环境、无双持 ─────────────

def _run_concurrent(monkeypatch, tmp_path, n_envs: int, n_threads: int, timeout=15.0):
    import threading
    import time

    monkeypatch.setattr(env_pool, "_LOCK_DIR", tmp_path)
    envs = [config.Environment(id=f"env-{i}", jumphost=f"10.0.0.{i}") for i in range(n_envs)]
    monkeypatch.setattr(config, "load_environments", lambda: envs)
    monkeypatch.setattr(env_pool, "_healthy", lambda e, **k: True)

    held: dict[str, int] = {}
    lock = threading.Lock()
    state = {"conc": 0, "max_conc": 0}
    got: list[str] = []
    violations: list[str] = []
    barrier = threading.Barrier(n_threads)

    def worker():
        barrier.wait()  # 让所有线程尽量同一时刻抢，逼出真并发
        with env_pool.acquire(timeout=timeout, poll_s=0.005) as e:
            with lock:
                held[e.id] = held.get(e.id, 0) + 1
                if held[e.id] > 1:           # 同一环境被两个线程同时持有 = 互斥失效
                    violations.append(e.id)
                state["conc"] += 1
                state["max_conc"] = max(state["max_conc"], state["conc"])
                got.append(e.id)
            time.sleep(0.05)                 # 拉长持有窗口，强制并发重叠
            with lock:
                held[e.id] -= 1
                state["conc"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return got, violations, state["max_conc"]


def test_concurrent_acquire_distributes_no_collision(monkeypatch, tmp_path):
    """4 线程同时 acquire → 分到 4 个不同环境、4 路真并发、无同环境双持。"""
    got, violations, max_conc = _run_concurrent(monkeypatch, tmp_path, n_envs=4, n_threads=4)
    assert not violations, f"同一环境被并发双持: {violations}"
    assert sorted(got) == ["env-0", "env-1", "env-2", "env-3"]  # 完美分散
    assert max_conc == 4                                          # 真 4 路并发，非串行


def test_concurrent_overflow_queues_without_collision(monkeypatch, tmp_path):
    """6 线程抢 2 环境 → 任意时刻最多 2 路、无双持、6 个最终都完成（多出的排队）。"""
    got, violations, max_conc = _run_concurrent(monkeypatch, tmp_path, n_envs=2, n_threads=6)
    assert not violations
    assert max_conc <= 2            # 设备级互斥：永不超过环境数
    assert len(got) == 6           # 全部完成（排队等空闲，不丢）


def test_framework_ready_false_on_connect_fail(monkeypatch):
    monkeypatch.setenv("IST_JUMPHOST_PASS", "x")

    class FakeSSH:
        def set_missing_host_key_policy(self, *a):
            pass

        def connect(self, *a, **k):
            raise OSError("unreachable")

        def close(self):
            pass

    import paramiko
    monkeypatch.setattr(paramiko, "SSHClient", lambda: FakeSSH())
    env = config.Environment(id="env-79", jumphost="10.4.127.79")
    assert dmc.framework_ready(env) is False
