"""自动化环境池：多跳板机并行 runner 的认领/释放 + health-check + 跨进程互斥锁。

每个环境 = 一台跳板机 + 各自**独立设备床**（同地址克隆）。一个 verify/上机任务认领一个
**空闲且就绪**的环境（fcntl 文件锁，跨进程互斥），用完释放；4 机 → 最多 4 任务并行。

安全保证：
- 默认池**关**（``config.load_environments`` 只返回现役 103）→ 调用方不经本模块，行为同今天。
- health-check（``framework_ready``，带 TTL 缓存）跳过框架未部署/不可达的环境 → Path A 渐进
  上线天然安全：今天只有 103 就绪，新机克隆部署后自动加入可用池。
- 全部环境都不就绪 → 回退到首个环境（现役 103），避免 health-check 误判/网络抖动整体卡死。
- 全部就绪环境都忙 → 阻塞轮询到 timeout 抛 ``TimeoutError``；池机制本身异常由调用方回退单环境兜底。
"""
from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import time
from pathlib import Path
from typing import Iterator

from main.case_compiler import config as _config

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_LOCK_DIR = _ROOT / "runtime" / "env_locks"

_HEALTH_TTL_S = 120.0
_health_cache: dict[str, tuple[bool, float]] = {}


def is_enabled() -> bool:
    """环境池是否启用（``IST_ENV_POOL_ENABLED`` 真值）。关→调用方走现役单环境。"""
    return _config._pool_enabled()


def _healthy(env, ttl: float = _HEALTH_TTL_S) -> bool:
    """env 是否就绪（SSH 可达 + 框架 server.py 在），带 TTL 缓存避免每次 acquire 都 SSH。"""
    hit = _health_cache.get(env.id)
    if hit is not None and (time.time() - hit[1]) < ttl:
        return hit[0]
    from main.case_compiler.device_mcp_client import framework_ready
    try:
        ok = bool(framework_ready(env))
    except Exception:  # noqa: BLE001
        ok = False
    _health_cache[env.id] = (ok, time.time())
    return ok


def clear_health_cache() -> None:
    """清 health 缓存（部署完新机后想立即让它进池，或测试用）。"""
    _health_cache.clear()


def _try_lock(env_id: str):
    """尝试拿 env 的排他锁。拿到→返回持锁的打开文件句柄；被占→None。"""
    _LOCK_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(_LOCK_DIR / f"{env_id}.lock", "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    try:
        fh.write(f"{os.getpid()}\n")
        fh.flush()
    except Exception:  # noqa: BLE001
        pass
    return fh


def _unlock(fh) -> None:
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:  # noqa: BLE001
        pass
    try:
        fh.close()
    except Exception:  # noqa: BLE001
        pass


def ready_environments() -> list:
    """当前**就绪**（health-check 通过）的环境列表——TUI/诊断用。"""
    return [e for e in _config.load_environments() if _healthy(e)]


@contextlib.contextmanager
def acquire(timeout: float = 1800.0, poll_s: float = 5.0,
            health_check: bool = True) -> Iterator[object]:
    """认领一个空闲就绪环境；``yield`` config.Environment；退出释放锁。

    全忙→阻塞轮询到 timeout 抛 ``TimeoutError``。单环境（池关）时退化为直接拿那一个。
    """
    envs = _config.load_environments()
    if not envs:
        raise RuntimeError("没有可用环境（load_environments 返回空）")

    deadline = time.time() + max(0.0, timeout)
    while True:
        ready = [e for e in envs if _healthy(e)] if health_check else list(envs)
        # 全不就绪 → 回退首个环境（现役 103），不让 health-check 误判/网络抖动整体卡死
        if not ready:
            ready = envs[:1]
        for env in ready:
            fh = _try_lock(env.id)
            if fh is not None:
                logger.info("[env_pool] 认领环境 %s (%s)", env.id, env.jumphost)
                try:
                    yield env
                finally:
                    _unlock(fh)
                    logger.info("[env_pool] 释放环境 %s", env.id)
                return
        if time.time() >= deadline:
            raise TimeoutError(
                f"环境池全忙：{len(ready)} 个候选环境都被占用，等待超 {timeout:.0f}s。")
        time.sleep(poll_s)
