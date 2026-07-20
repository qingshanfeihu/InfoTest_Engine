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
from typing import Any

logger = logging.getLogger(__name__)

_client: Any | None = None
_init_lock = threading.Lock()
_initialized = False


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


class _RootSpanInjector:
    """拦截 Langfuse client.start_observation()，在创建根 span 后注入 trace 属性。

    CallbackHandler 在 parent_run_id 为 None 时通过 self.client.start_observation()
    创建新的 root trace——但 __on_llm_action 不调 update_trace()，user_id/session_id 丢失。
    本代理在 start_observation() 返回后立即调 update_trace() 补上属性。
    """

    def __init__(self, client: Any, user_id: str, session_id: str,
                 tags: list[str] | None, metadata: dict[str, Any] | None):
        self._client = client
        self._user_id = user_id
        self._session_id = session_id
        self._tags = tags
        self._metadata = metadata

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
) -> list[Any]:
    """往 callbacks 列表追加 Langfuse CallbackHandler，注入 trace 属性。

    Monkey-patch _get_parent_observation：当 parent_run_id 为 None 时返回
    _RootSpanInjector 代理，在创建根 span 后自动调 update_trace() 注入属性。
    这绕过了 deepagents 中间件剥离 metadata 的问题。
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
                    )
            return parent

        handler._get_parent_observation = _patched_get_parent

        callbacks.append(handler)
        logger.info(
            "Langfuse: CallbackHandler 已注入 (user=%s session=%s tags=%s)",
            user_id or "-", session_id or "-", tags or "-",
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
