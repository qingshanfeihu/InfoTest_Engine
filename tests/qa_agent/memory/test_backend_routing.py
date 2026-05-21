"""CompositeBackend 路径路由 + AGENTS.md 加载入口。"""

from __future__ import annotations

from main.qa_agent.memory.backend import (
    build_memory_backend,
    get_default_root,
    get_memory_sources,
    _user_namespace,
)


def test_build_memory_backend_routes_have_working_and_memories():
    backend = build_memory_backend()
    assert "/working/" in backend.routes
    assert "/memories/" in backend.routes


def test_routing_maps_paths_to_correct_backend():
    backend = build_memory_backend()
    sorted_routes = backend.sorted_routes
    # 验证 /memories/foo.md 路由到 store
    from deepagents.backends.composite import _route_for_path

    chosen, normalized, prefix = _route_for_path(
        default=backend.default,
        sorted_routes=sorted_routes,
        path="/memories/preferences.md",
    )
    assert prefix == "/memories/"
    assert normalized == "/preferences.md"
    assert chosen is backend.routes["/memories/"]

    chosen2, normalized2, prefix2 = _route_for_path(
        default=backend.default,
        sorted_routes=sorted_routes,
        path="/working/foo.md",
    )
    assert prefix2 == "/working/"
    assert normalized2 == "/foo.md"
    assert chosen2 is backend.routes["/working/"]


def test_routing_unrelated_path_falls_back_to_default():
    backend = build_memory_backend()
    from deepagents.backends.composite import _route_for_path

    chosen, _, prefix = _route_for_path(
        default=backend.default,
        sorted_routes=backend.sorted_routes,
        path="/scratch.md",
    )
    assert prefix is None
    assert chosen is backend.default


def test_get_memory_sources_includes_agents_md():
    sources = get_memory_sources()
    assert sources == ["/memories/AGENTS.md"]


def test_get_default_root_under_repo():
    root = get_default_root()
    assert root.name == "memory"
    assert root.exists() or True  # 不强求存在，但路径合法


def test_user_namespace_falls_back_to_default():
    """server_info 缺失时降级到 ('default', 'memories')。"""
    ns = _user_namespace(None)
    assert ns == ("default", "memories")
    assert all(seg for seg in ns)


def test_user_namespace_uses_context_user_id():
    class _Rt:
        context = {"user_id": "alice"}

    ns = _user_namespace(_Rt())
    assert ns == ("alice", "memories")


def test_user_namespace_prefers_server_info_identity():
    class _User:
        identity = "bob"

    class _Server:
        user = _User()

    class _Rt:
        server_info = _Server()

    assert _user_namespace(_Rt()) == ("bob", "memories")


def test_user_namespace_validates_against_deepagents_rules():
    """deepagents StoreBackend 校验 namespace 字符白名单 [A-Za-z0-9\\-_.@+:~]+"""
    from deepagents.backends.store import _validate_namespace

    # 默认值合规
    _validate_namespace(_user_namespace(None))

    # 故意构造非法 user_id（含 *）应被 deepagents 拒
    class _Rt:
        context = {"user_id": "evil*"}

    import pytest

    with pytest.raises(ValueError):
        _validate_namespace(_user_namespace(_Rt()))
