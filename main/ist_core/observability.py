"""Langfuse 链路追踪(2026-07-09 替代 LangSmith)。

LangSmith 靠 env 变量全局自动 tracing;Langfuse 走 LangChain CallbackHandler,
须在每个 LLM 调用点手动挂进 ``config["callbacks"]``。本模块提供一个进程级缓存的
handler:env 门控、懒初始化、best-effort(任何失败静默降级为不追踪,绝不阻断主流程)。

启用条件(与旧 LangSmith sink 同哲学,该 sink 已删):``LANGFUSE_PUBLIC_KEY`` + ``LANGFUSE_SECRET_KEY``
都在 → 默认开;``LANGFUSE_TRACING_ENABLED=false`` 显式关。host 走 ``LANGFUSE_BASE_URL``
(或 ``LANGFUSE_HOST``,SDK 两者都认)。

挂载点(全部 LangChain 调用点,缺一即该链路不进 Langfuse):
- ``graph.qa_node`` — 主 agent(sync/async 都经它)
- ``skills/loader._invoke_fork_streamed`` — fork 子 agent
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

_HANDLER = None
_INIT_DONE = False
# 初始化失败不永久放弃(2026-07-13 实证:02:16 TUI 进程 auth_check 撞 jp.cloud 瞬态
# 读超时→整个进程终身禁用,全天两轮 run 零 trace 盲跑)——冷却后重试,既保住
# "不反复重试拖慢每次调用"的本意,又不让一次网络抖动变成八小时观测黑洞。
_NEXT_RETRY_TS = 0.0
_RETRY_COOLDOWN_S = float(os.environ.get("IST_OBS_RETRY_COOLDOWN_S", "300"))

# 可观测性自身的可观测(2026-07-10 实证:jp.cloud 出口静默读超时,一轮 ¥96 全程无 trace,
# 仅 tui.log 有 ERROR——盲跑必须对用户可见):状态机 + 失败回调(TUI footer 挂告警)。
_STATUS: dict = {"state": "uninit", "detail": ""}   # uninit|off|ok|init_failed|export_failing
_FAIL_CB = None
_WATCH_INSTALLED = False


def langfuse_status() -> dict:
    return dict(_STATUS)


def on_observability_failure(cb) -> None:
    """注册失败回调(线程安全的幂等安装):初始化失败或运行中上报失败时以 status dict 调用。"""
    global _FAIL_CB
    _FAIL_CB = cb
    if _STATUS["state"] in ("init_failed", "export_failing"):
        try:
            cb(dict(_STATUS))
        except Exception:  # noqa: BLE001
            logger.debug("obs 失败回调异常", exc_info=True)


def _set_status(state: str, detail: str = "") -> None:
    _STATUS.update(state=state, detail=detail[:200])
    if state in ("init_failed", "export_failing") and _FAIL_CB is not None:
        try:
            _FAIL_CB(dict(_STATUS))
        except Exception:  # noqa: BLE001
            logger.debug("obs 失败回调异常", exc_info=True)


class _OtelExportErrWatch(logging.Handler):
    """挂在 OTLP exporter logger 上:首次导出失败即置 export_failing(此后幂等)。"""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        if record.levelno >= logging.ERROR and _STATUS["state"] != "export_failing":
            _set_status("export_failing", record.getMessage())


def _install_export_watch() -> None:
    global _WATCH_INSTALLED
    if _WATCH_INSTALLED:
        return
    _WATCH_INSTALLED = True
    for name in ("opentelemetry.exporter.otlp.proto.http.trace_exporter",
                 "opentelemetry.sdk.trace.export"):
        logging.getLogger(name).addHandler(_OtelExportErrWatch())


def _enabled() -> bool:
    v = (os.environ.get("LANGFUSE_TRACING_ENABLED") or "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY")
                and os.environ.get("LANGFUSE_SECRET_KEY"))


def get_langfuse_handler():
    """返回进程级缓存的 Langfuse CallbackHandler;未启用/初始化失败 → None。

    调用方:``cbs = [...]; h = get_langfuse_handler(); cbs += [h] if h else []``。
    首次调用懒初始化;auth_check 失败**冷却后重试**(默认 300s,IST_OBS_RETRY_COOLDOWN_S
    可调)——旧版"失败即永久 None"让一次瞬态超时把长驻 TUI 进程变成整日盲跑
    (2026-07-13 实证),而 jp.cloud 出口读超时是本网络的已知常态(tui.log 三天前科)。
    """
    global _HANDLER, _INIT_DONE, _NEXT_RETRY_TS
    if _INIT_DONE:
        return _HANDLER
    now = time.time()
    if now < _NEXT_RETRY_TS:
        return None                    # 冷却期内不重试(不拖慢每次 LLM 调用)
    if not _enabled():
        _INIT_DONE = True              # 未配置/显式关=确定态,无需重试
        _set_status("off", "未配置或显式关闭")
        return None
    try:
        from langfuse import get_client
        from langfuse.langchain import CallbackHandler
        client = get_client()          # 自 env 读 key/host,进程级单例
        try:
            if not client.auth_check():  # 校验失败降级(不阻断),冷却后重试
                logger.warning("Langfuse auth_check 未通过,链路追踪禁用(%.0fs 后重试)",
                               _RETRY_COOLDOWN_S)
                _set_status("init_failed", "auth_check 未通过")
                _NEXT_RETRY_TS = now + _RETRY_COOLDOWN_S
                return None
        except Exception as exc:  # noqa: BLE001 — auth_check 网络异常也降级,不抛
            logger.warning("Langfuse auth_check 异常(%.0fs 后重试): %s",
                           _RETRY_COOLDOWN_S, exc)
            _set_status("init_failed", f"auth_check 异常: {exc}")
            _NEXT_RETRY_TS = now + _RETRY_COOLDOWN_S
            return None
        _HANDLER = CallbackHandler()
        _INIT_DONE = True
        _set_status("ok")
        _install_export_watch()   # 运行中导出失败(网络断流)也要浮到用户面
        logger.info("Langfuse 链路追踪已启用")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Langfuse handler 初始化失败(降级为不追踪,%.0fs 后重试): %s",
                       _RETRY_COOLDOWN_S, exc)
        _set_status("init_failed", str(exc))
        _HANDLER = None
        _NEXT_RETRY_TS = now + _RETRY_COOLDOWN_S
    return _HANDLER
