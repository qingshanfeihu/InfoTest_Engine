"""Memory backend assembly: CompositeBackend + namespace + store factory.

参考实现：
- deepagents 文档 CompositeBackend(default=StateBackend(), routes={"/memories/": StoreBackend(...)})
- cc-haha 的 memdir/paths.ts 路径解析
- 本仓库 main_agent.py:90-98 原 FilesystemBackend 装配

为什么改用 CompositeBackend 替换原 FilesystemBackend：
- L1 工作记忆走 StateBackend（thread 内有效，checkpointer 自动持久化）
- L2 长期记忆走 StoreBackend（跨 thread，namespace 隔离）
- L3 AGENTS.md 走 deepagents 内置 MemoryMiddleware（memory= 参数触发）
- 原 qa_deepagent_* 工具仍走真实磁盘（不经过 backend），不受影响
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

# 重型 import 延迟到函数内部，避免 import backend.py 就拉起 deepagents 全家桶（~57MB）
# 类型注解用 TYPE_CHECKING 守护
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore
    from deepagents.backends import CompositeBackend

logger = logging.getLogger(__name__)

_store_singleton: Any = None
_store_singleton_dsn: str | None = None


def _build_default_store():
    """按 env IST_MEMORY_STORE_DSN 选 InMemoryStore / SqliteStore / PostgresStore。

    DSN 格式：
    - (空) → InMemoryStore（默认，进程内）
    - sqlite:///path/to/store.db → SqliteStore
    - postgresql://... → PostgresStore
    """
    global _store_singleton, _store_singleton_dsn

    dsn = (os.environ.get("IST_MEMORY_STORE_DSN") or "").strip()
    if _store_singleton is not None and _store_singleton_dsn == dsn:
        return _store_singleton

    if not dsn:
        from langgraph.store.memory import InMemoryStore
        _store_singleton = InMemoryStore()
        _store_singleton_dsn = dsn
        return _store_singleton

    if dsn.startswith("sqlite"):
        try:
            import sqlite3
            from langgraph.store.sqlite import SqliteStore

            db_path = dsn.replace("sqlite:///", "").replace("sqlite://", "")
            conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
            store = SqliteStore(conn)
            store.setup()
            _store_singleton = store
            _store_singleton_dsn = dsn
            return store
        except Exception as exc:
            logger.warning("SqliteStore 初始化失败，降级 InMemoryStore: %s", exc)
            from langgraph.store.memory import InMemoryStore
            _store_singleton = InMemoryStore()
            _store_singleton_dsn = dsn
            return _store_singleton

    if dsn.startswith("postgres"):
        try:
            from langgraph.store.postgres import PostgresStore

            store = PostgresStore.from_conn_string(dsn)
            store.setup()
            _store_singleton = store
            _store_singleton_dsn = dsn
            return store
        except Exception as exc:
            logger.warning("PostgresStore 初始化失败，降级 InMemoryStore: %s", exc)
            from langgraph.store.memory import InMemoryStore
            _store_singleton = InMemoryStore()
            _store_singleton_dsn = dsn
            return _store_singleton

    logger.warning("未识别的 IST_MEMORY_STORE_DSN=%r，使用 InMemoryStore", dsn)
    from langgraph.store.memory import InMemoryStore
    _store_singleton = InMemoryStore()
    _store_singleton_dsn = dsn
    return _store_singleton


def _user_namespace(rt: Any) -> tuple[str, ...]:
    """用户级 namespace factory。

    参考 deepagents 文档：namespace=lambda rt: (rt.server_info.user.identity, "memories")
    IST-Core 在 langgraph dev 之外（TUI 直连）可能没有 server_info，降级到 "default"。
    """
    try:
        identity = rt.server_info.user.identity
        if identity:
            return (str(identity), "memories")
    except Exception:
        pass
    try:
        ctx = getattr(rt, "context", None) or {}
        user_id = ctx.get("user_id") or ctx.get("identity") or "default"
        return (str(user_id), "memories")
    except Exception:
        return ("default", "memories")


def get_default_store():
    """获取全局 store 单例（供 fork agent / dream task 共享）。"""
    return _build_default_store()


def build_memory_backend(*, store=None):
    """构造主 agent 与 fork agent 共享的 CompositeBackend。

    路由：
    - /working/   → StateBackend（thread 内，checkpointer 持久化）
    - /memories/  → StoreBackend（跨 thread，namespace 隔离）
    - 其他路径    → StateBackend（deepagents 内置 todos / scratch 等）

    artifacts_root="/tmp"：让 deepagents FilesystemMiddleware 把 large_tool_results
    与 conversation_history 落到 tmp/ 下而不是项目根（避免污染仓库目录树；
    tmp/ 已在 .gitignore）。FilesystemMiddleware 默认 artifacts_root="/"
    会把这两个目录写到项目根，触发 git status 噪声。
    """
    from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

    resolved_store = store or _build_default_store()
    return CompositeBackend(
        default=StateBackend(),
        routes={
            "/working/": StateBackend(),
            "/memories/": StoreBackend(
                store=resolved_store,
                namespace=_user_namespace,
            ),
        },
        artifacts_root="/tmp",
    )


def get_memory_sources() -> list[str]:
    """返回 create_deep_agent(memory=...) 的 sources 列表。

    deepagents MemoryMiddleware 会在 before_agent 时 download_files 这些路径，
    注入到 system prompt。对应 L3 AGENTS.md。
    """
    return ["/memories/AGENTS.md"]


def get_default_root() -> Path:
    """返回真实磁盘上的 memory 根目录（用于 dream task / AGENTS.md 种子文件）。"""
    root_env = (os.environ.get("IST_MEMORY_ROOT") or "").strip()
    if root_env:
        return Path(root_env).resolve()
    project_root = Path(__file__).resolve().parents[3]
    return project_root / "memory"


def make_memory_backend_factory():
    """返回 deepagents BackendFactory：(runtime) → CompositeBackend。

    用法（main_agent.py）::

        backend_kwarg["backend"] = make_memory_backend_factory()

    deepagents 0.5.9 把它当 ``BackendFactory = Callable[[ToolRuntime], BackendProtocol]``
    用，每次 graph 调用前用真实 ToolRuntime 调一次。这让 namespace 能按运行时
    user.identity 变化（langgraph dev 多用户部署场景）。

    本地 TUI 直连模式下 ToolRuntime 没有 server_info.user.identity，_user_namespace
    会降级到 ("default", "memories")，行为与静态 build_memory_backend() 一致。

    backend 实例进程内单例缓存：store 单例由 _build_default_store 管理，无需每次重造。
    """
    _cached: list = []

    def _factory(runtime):
        if _cached:
            return _cached[0]
        backend = build_memory_backend()
        _cached.append(backend)
        return backend

    return _factory
