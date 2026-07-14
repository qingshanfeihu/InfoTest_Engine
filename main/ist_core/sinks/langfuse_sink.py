# [已注释] Langfuse LLM 可观测性 — 暂时禁用
# 如需恢复，取消下方注释并确保 langfuse>=2.0 已安装
#
# from __future__ import annotations
#
# import atexit
# import logging
# import os
# import threading
# from typing import Any
#
# logger = logging.getLogger(__name__)
#
# _handler: Any | None = None
# _langfuse_client: Any | None = None
# _init_lock = threading.Lock()
# _initialized = False
#
#
# def _add_no_proxy(host_url: str) -> None:
#     from urllib.parse import urlparse
#     try:
#         parsed = urlparse(host_url)
#         hostname = parsed.hostname or ""
#     except Exception:
#         hostname = ""
#     if not hostname:
#         return
#     for var in ("NO_PROXY", "no_proxy"):
#         existing = os.environ.get(var, "")
#         if hostname not in existing:
#             os.environ[var] = f"{existing},{hostname}" if existing else hostname
#
#
# def get_langfuse_handler() -> Any | None:
#     global _handler, _langfuse_client, _initialized
#     if _initialized:
#         return _handler
#     with _init_lock:
#         if _initialized:
#             return _handler
#         _initialized = True
#         public_key = (os.environ.get("LANGFUSE_PUBLIC_KEY") or "").strip()
#         secret_key = (os.environ.get("LANGFUSE_SECRET_KEY") or "").strip()
#         host = (os.environ.get("LANGFUSE_HOST") or os.environ.get("LANGFUSE_BASE_URL") or "").strip()
#         if not public_key or not secret_key or not host:
#             return None
#         try:
#             _add_no_proxy(host)
#             from langfuse import Langfuse
#             from langfuse.langchain import CallbackHandler
#             _langfuse_client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
#             _handler = CallbackHandler()
#             atexit.register(flush_langfuse)
#         except Exception:
#             _handler = None
#     return _handler
#
#
# def flush_langfuse() -> None:
#     client = _langfuse_client
#     if client is not None:
#         try:
#             client.flush()
#         except Exception:
#             pass
#
#
# def inject_langfuse_callbacks(callbacks: list[Any]) -> list[Any]:
#     handler = get_langfuse_handler()
#     if handler is not None:
#         callbacks.append(handler)
#     return callbacks
