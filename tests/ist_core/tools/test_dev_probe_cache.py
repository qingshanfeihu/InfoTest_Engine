"""dev_probe 共享缓存的**静态/动态区分**守护。

并发 draft 复用 `_PROBE_CACHE` 免重复探同一条 show 是性能关键;但动态查询
(statistics/session/命中计数等运行时值)缓存会返回 stale → 必须绕过始终现探。
`_probe_cacheable` 是判别闸:静态配置=可缓存,动态计数/状态=不可。
"""

from __future__ import annotations

from main.ist_core.tools.device.run_case import _probe_cacheable


def test_static_config_is_cacheable():
    """纯配置回显在一次 compile run 内稳定 → 可缓存。"""
    for cmd in (
        "show sdns host all",
        "show sdns host persistence",
        "show sdns host name",
        "show sdns listener",
        "show sdns pool",
        "show sdns status",  # 启停态在只读 compile 期稳定,可缓存
    ):
        assert _probe_cacheable(cmd), f"应可缓存: {cmd!r}"


def test_dynamic_queries_bypass_cache():
    """运行时计数/会话/连接/健康检查等每次可能不同 → 必须绕过缓存。"""
    for cmd in (
        "show statistics sdns pool",
        "show sdns pool statistics",
        "show sdns session",
        "show sdns connection",
        "show sdns pool counter",
        "show sdns pool health",
        "show statistics traffic",
    ):
        assert not _probe_cacheable(cmd), f"动态查询应绕过缓存: {cmd!r}"
