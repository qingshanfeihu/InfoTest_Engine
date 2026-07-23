"""Langfuse LLM 可观测性 — v3 最佳实践集成。

通过 ``CallbackHandler`` + monkey-patch ``_parse_langfuse_trace_attributes_from_metadata``
自动追踪所有 LLM 调用（主 agent + fork 子 agent），绕过 deepagents 中间件剥离 metadata 的问题。

三键（LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL）
缺一则静默跳过，不影响主流程。``IST_LANGFUSE_ENABLED=0`` 可强制关闭。

用法::

    # graph.py qa_node 入口
    inject_langfuse_callbacks(
        merged_config["callbacks"],
        user_id="...", session_id="...", tags=[...],
        metadata={"thread_id": "...", ...},
    )

    # loader.py fork 入口
    inject_langfuse_callbacks(cfg["callbacks"], ...)
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_client: Any | None = None
_init_lock = threading.Lock()
_initialized = False

# run_id → (trace_id, created_ts) 的内存映射，用于 score 关联
_TRACE_CACHE_TTL = int(os.environ.get("IST_LANGFUSE_TRACE_CACHE_TTL", "7200"))  # 默认 2 小时
_trace_id_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()

# Redis 共享缓存（跨进程：TUI 写、Web Server 读 score 关联）
_redis_client: Any | None = None
_redis_inited = False
_redis_lock = threading.Lock()
_REDIS_KEY_PREFIX = "ist:trace_id:"


def _add_no_proxy(host_url: str) -> None:
    """把 Langfuse host 加入 NO_PROXY，避免企业内网代理拦截。"""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(host_url)
        hostname = parsed.hostname or ""
    except Exception:
        hostname = ""
    if not hostname:
        return
    for var in ("NO_PROXY", "no_proxy"):
        existing = os.environ.get(var, "")
        if hostname not in existing:
            os.environ[var] = f"{existing},{hostname}" if existing else hostname


def _get_credentials() -> tuple[str, str, str]:
    """读取三键，缺任一则返回空串。"""
    public_key = (os.environ.get("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = (os.environ.get("LANGFUSE_SECRET_KEY") or "").strip()
    host = (os.environ.get("LANGFUSE_BASE_URL")
            or os.environ.get("LANGFUSE_HOST") or "").strip()
    return public_key, secret_key, host


def warmup_langfuse_client() -> None:
    """后台线程预热 Langfuse client（非阻塞）。

    在 web server / TUI 启动时调用，首次 agent 请求到来时 client 已缓存完毕。
    三键不全时静默跳过，零开销。
    """
    if _initialized or os.environ.get("IST_LANGFUSE_ENABLED", "1").strip() == "0":
        return
    public_key, secret_key, host = _get_credentials()
    if not public_key or not secret_key or not host:
        return
    threading.Thread(target=get_langfuse_client, daemon=True, name="langfuse-warmup").start()


def get_langfuse_client() -> Any | None:
    """返回全局 Langfuse client 单例（线程安全）。三键缺一或 disabled 则返回 None。

    初始化失败时 ``_initialized`` 保持 False，下次调用可重试
    （避免瞬态网络故障导致 Langfuse 永久不可用）。
    """
    global _client, _initialized
    if _initialized:
        return _client
    with _init_lock:
        if _initialized:
            return _client

        if os.environ.get("IST_LANGFUSE_ENABLED", "1").strip() == "0":
            logger.info("Langfuse: 已通过 IST_LANGFUSE_ENABLED=0 关闭")
            _initialized = True
            return None

        public_key, secret_key, host = _get_credentials()
        if not public_key or not secret_key or not host:
            logger.debug("Langfuse: 三键不全，跳过初始化 (pk=%s sk=%s host=%s)",
                         bool(public_key), bool(secret_key), bool(host))
            return None
        try:
            _add_no_proxy(host)
            from langfuse import Langfuse
            _client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
            atexit.register(flush_langfuse)
            logger.info("Langfuse: client 初始化成功 → %s (pk=%s…)", host, public_key[:12])
            _initialized = True
        except Exception:
            logger.exception("Langfuse: client 初始化失败（下次调用将重试）")
            _client = None
    return _client


def flush_langfuse() -> None:
    """进程退出前 flush 缓冲区，确保数据落盘。"""
    c = _client
    if c is not None:
        try:
            c.flush()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# run_id → trace_id 缓存（带 TTL 过期清理）
# ---------------------------------------------------------------------------

def _get_redis() -> Any | None:
    """返回 Redis client 单例（跨进程共享 trace_id 缓存用）。IST_REDIS_URL 未设置或不可达则返回 None。"""
    global _redis_client, _redis_inited
    if _redis_inited:
        return _redis_client
    with _redis_lock:
        if _redis_inited:
            return _redis_client
        _redis_inited = True
        url = (os.environ.get("IST_REDIS_URL") or "").strip()
        if not url:
            return None
        try:
            import redis
            _redis_client = redis.from_url(url, decode_responses=True)
            _redis_client.ping()
            logger.info("Langfuse: Redis trace_id 缓存已连接 → %s", url.split("@")[-1])
        except Exception:
            logger.debug("Langfuse: Redis 不可用，trace_id 缓存降级为纯内存", exc_info=True)
            _redis_client = None
    return _redis_client


def cache_trace_id(run_id: str, trace_id: str) -> None:
    """根 span 创建后，缓存 run_id → trace_id 映射（内存 + Redis 双写）。"""
    with _cache_lock:
        _trace_id_cache[run_id] = (trace_id, time.monotonic())
    # Redis 跨进程共享（TUI 进程写，Web Server 进程读）
    r = _get_redis()
    if r is not None:
        try:
            r.set(f"{_REDIS_KEY_PREFIX}{run_id}", trace_id, ex=_TRACE_CACHE_TTL)
        except Exception:
            logger.debug("Langfuse: Redis trace_id 写入失败", exc_info=True)


def _evict_stale_cache() -> None:
    """清理过期的 trace_id 缓存条目（惰性：每次查询时触发）。"""
    now = time.monotonic()
    with _cache_lock:
        stale = [k for k, (_, ts) in _trace_id_cache.items()
                 if now - ts > _TRACE_CACHE_TTL]
        for k in stale:
            del _trace_id_cache[k]


def get_trace_id(run_id: str) -> str | None:
    """查询 run_id 对应的 Langfuse trace_id（内存优先 → Redis 回填 → 过期自动清除）。"""
    # 1. 内存缓存命中
    with _cache_lock:
        entry = _trace_id_cache.get(run_id)
    if entry is not None:
        trace_id, ts = entry
        if time.monotonic() - ts <= _TRACE_CACHE_TTL:
            return trace_id
        # 过期，清除
        with _cache_lock:
            _trace_id_cache.pop(run_id, None)
    # 2. Redis 回填（跨进程场景：TUI 写、Web Server 读）
    r = _get_redis()
    if r is not None:
        try:
            val = r.get(f"{_REDIS_KEY_PREFIX}{run_id}")
            if val:
                # 回填内存缓存
                with _cache_lock:
                    _trace_id_cache[run_id] = (val, time.monotonic())
                return val
        except Exception:
            logger.debug("Langfuse: Redis trace_id 读取失败", exc_info=True)
    return None


def submit_langfuse_score(
    run_id: str,
    name: str,
    value: float,
    comment: str = "",
) -> None:
    """异步提交 score 到 Langfuse（后台线程，非阻塞主流程）。

    Parameters
    ----------
    run_id:
        本次运行 ID，用于查找对应的 Langfuse trace_id。
    name:
        score 名称（如 ``user-rating``）。
    value:
        数值分数。
    comment:
        可选文字评价。
    """
    def _do() -> None:
        client = get_langfuse_client()
        if client is None:
            return
        trace_id = get_trace_id(run_id)
        if not trace_id:
            logger.debug("Langfuse score: run_id=%s 无对应 trace_id，跳过", run_id)
            return
        try:
            client.create_score(
                trace_id=trace_id,
                name=name,
                value=value,
                comment=comment or None,
            )
            logger.debug("Langfuse score: %s=%.1f trace=%s", name, value, trace_id[:12])
        except Exception:
            logger.debug("Langfuse score 上报失败", exc_info=True)
        # 惰性清理过期缓存
        _evict_stale_cache()

    threading.Thread(target=_do, daemon=True, name="langfuse-score").start()


class _RootSpanInjector:
    """拦截 Langfuse client.start_observation()，在创建根 span 后注入 trace 属性。

    CallbackHandler 在 parent_run_id 为 None 时通过 self.client.start_observation()
    创建新的 root trace——但 __on_llm_action 不调 update_trace()，user_id/session_id 丢失。
    本代理在 start_observation() 返回后立即调 update_trace() 补上属性。
    """

    def __init__(self, client: Any, user_id: str, session_id: str,
                 tags: list[str] | None, metadata: dict[str, Any] | None,
                 cache_run_id: str = ""):
        self._client = client
        self._user_id = user_id
        self._session_id = session_id
        self._tags = tags
        self._metadata = metadata
        self._cache_run_id = cache_run_id

    def start_observation(self, **kwargs: Any) -> Any:
        obs = self._client.start_observation(**kwargs)
        try:
            update_kwargs: dict[str, Any] = {}
            if self._user_id:
                update_kwargs["user_id"] = self._user_id
            if self._session_id:
                update_kwargs["session_id"] = self._session_id
            if self._tags:
                update_kwargs["tags"] = self._tags
            if self._metadata:
                update_kwargs["metadata"] = self._metadata
            if update_kwargs:
                obs.update_trace(**update_kwargs)
            # 缓存 run_id → trace_id，供后续 score 关联。
            # 优先使用显式传入的 cache_run_id（不依赖 metadata，不会被下游覆盖）。
            _run_id = self._cache_run_id or (self._metadata or {}).get("run_id") or ""
            if _run_id and hasattr(obs, "trace_id"):
                cache_trace_id(_run_id, obs.trace_id)
        except Exception:
            logger.debug("RootSpanInjector: update_trace 失败", exc_info=True)
        return obs

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def inject_langfuse_callbacks(
    callbacks: list[Any],
    *,
    user_id: str = "",
    session_id: str = "",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    cache_run_id: str = "",
) -> list[Any]:
    """往 callbacks 列表追加 Langfuse CallbackHandler，注入 trace 属性。

    Monkey-patch _get_parent_observation：当 parent_run_id 为 None 时返回
    _RootSpanInjector 代理，在创建根 span 后自动调 update_trace() 注入属性。
    这绕过了 deepagents 中间件剥离 metadata 的问题。

    ``cache_run_id``：如果提供，在根 span 创建后以该值为 key 缓存 trace_id，
    供后续 ``submit_langfuse_score`` 关联 score。直接传入比从 metadata 读取
    更可靠（metadata 可能被下游覆盖）。
    """
    if get_langfuse_client() is None:
        logger.debug("Langfuse: client 未就绪，跳过 callback 注入")
        return callbacks
    try:
        from langfuse.langchain import CallbackHandler

        handler = CallbackHandler(update_trace=True)

        _orig_get_parent = handler._get_parent_observation

        def _patched_get_parent(parent_run_id: Any) -> Any:
            parent = _orig_get_parent(parent_run_id)
            if parent_run_id is None:
                from langfuse._client.client import Langfuse
                if isinstance(parent, Langfuse):
                    return _RootSpanInjector(
                        parent,
                        user_id=user_id,
                        session_id=session_id,
                        tags=tags,
                        metadata=metadata,
                        cache_run_id=cache_run_id,
                    )
            return parent

        handler._get_parent_observation = _patched_get_parent

        callbacks.append(handler)
        logger.info(
            "Langfuse: CallbackHandler 已注入 (user=%s session=%s tags=%s cache_run_id=%s)",
            user_id or "-", session_id or "-", tags or "-", cache_run_id or "-",
        )
    except Exception:
        logger.warning("Langfuse: CallbackHandler 创建失败", exc_info=True)
    return callbacks


def build_trace_attributes(
    config: dict[str, Any] | None,
    *,
    entry: str = "",
    skill: str = "",
    fork_id: str = "",
) -> dict[str, Any]:
    """从 config 提取 Langfuse trace 属性，供 ``inject_langfuse_callbacks`` 使用。"""
    cbl = (config or {}).get("configurable") or {}

    _thread_id = cbl.get("thread_id") or ""

    # user_id: wx_user_id > auth_user > thread_id 首段
    uid = cbl.get("wx_user_id") or cbl.get("auth_user") or ""
    if not uid and _thread_id:
        uid = _thread_id.split("_", 1)[0] if "_" in _thread_id else _thread_id

    # session_id: auth_session_id > thread_id
    sid = cbl.get("auth_session_id") or _thread_id or ""

    # tags
    tgs: list[str] = []
    if entry:
        tgs.append(f"entry:{entry}")
    if skill:
        tgs.append(f"skill:{skill}")
    if fork_id:
        tgs.append(f"fork:{fork_id}")

    # metadata
    meta: dict[str, Any] = {}
    if _thread_id:
        meta["thread_id"] = _thread_id
    _conv_id = cbl.get("auth_conversation_id") or ""
    if _conv_id:
        meta["conversation_id"] = _conv_id
    _run_id = cbl.get("run_id") or ""
    if _run_id:
        meta["run_id"] = _run_id

    return {"user_id": uid, "session_id": sid, "tags": tgs or None, "metadata": meta or None}
