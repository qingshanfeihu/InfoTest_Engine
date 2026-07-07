r"""企业微信智能机器人 — WebSocket 长连接核心驱动。

基于官方文档:
  - 长连接协议: https://developer.work.weixin.qq.com/document/path/101463
  - 文档工具:    https://developer.work.weixin.qq.com/document/path/101468

心跳保活（双保险）:
  协议层:   ws.run_forever(ping_interval=20, ping_timeout=10)
  应用层:   独立心跳线程，每 18s 发送 JSON keepalive 帧
           (比协议层更可靠——协议级 ping 帧常被公司防火墙/NAT 丢弃)
"""

from __future__ import annotations

import json
import logging
import ctypes
import threading
import time
import uuid
from typing import Any

import websocket

from .config import smart_config, server_config

logger = logging.getLogger("wecom_bot_smart.gateway")


# ============================================================================
# IST-Core 调用
# ============================================================================

def _call_ist_core(user_query: str, user_id: str = "smart_user") -> str:
    import os as _os
    _os.environ.setdefault("IST_NON_INTERACTIVE", "1")
    _os.environ.setdefault("IST_LLM_STREAMING", "0")

    from main.ist_core.runner import _ensure_env
    _ensure_env()

    from main.ist_core.graph import build_ist_core_graph
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import HumanMessage

    tid = f"smart-{user_id or 'anon'}-{uuid.uuid4().hex[:8]}"
    logger.info("IST-Core 开始: thread=%s query=%.100s", tid, user_query)

    with InMemorySaver() as saver:
        graph = build_ist_core_graph(checkpointer=saver, checkpointer_mode="sync")
        config: dict[str, Any] = {"configurable": {"thread_id": tid}}
        initial_state: dict[str, Any] = {
            "task_type": "QA",
            "user_input": user_query,
            "messages": [HumanMessage(content=user_query)],
        }
        result = graph.invoke(initial_state, config)

    final = result.get("final_answer") or "（无回答）"
    logger.info("IST-Core 完成: thread=%s len=%d", tid, len(final))
    return final


# ============================================================================
# 任务注册表
# ============================================================================

_task_registry: dict[str, dict[str, Any]] = {}
_registry_lock = threading.Lock()


def _register_task(user_id: str, stream_id: str) -> threading.Event:
    with _registry_lock:
        old = _task_registry.pop(user_id, None)
    if old is not None:
        _kill_existing(old, user_id)

    cancel_evt = threading.Event()
    with _registry_lock:
        _task_registry[user_id] = {
            "thread": threading.current_thread(),
            "cancel": cancel_evt,
            "stream_id": stream_id,
            "start_ts": time.monotonic(),
        }
    return cancel_evt


def _deregister_task(user_id: str) -> None:
    with _registry_lock:
        _task_registry.pop(user_id, None)


def _cancel_task(user_id: str) -> bool:
    with _registry_lock:
        task = _task_registry.pop(user_id, None)
    if task is None:
        return False
    _kill_existing(task, user_id)
    return True


def _kill_existing(task: dict[str, Any], user_id: str) -> None:
    task["cancel"].set()
    t: threading.Thread = task["thread"]
    logger.info("取消旧任务: user=%s", user_id)
    if t.ident is not None:
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(t.ident), ctypes.py_object(SystemExit)
        )
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(t.ident), None)


def _active_count() -> int:
    with _registry_lock:
        return len(_task_registry)


# ============================================================================
# 协议工具
# ============================================================================

def _mk_req_id() -> str:
    return uuid.uuid4().hex[:16]


def _send_cmd(ws, cmd: str, body: dict, req_id: str | None = None) -> str:
    rid = req_id or _mk_req_id()
    msg = {"cmd": cmd, "headers": {"req_id": rid}, "body": body}
    ws.send(json.dumps(msg, ensure_ascii=False))
    return rid


# ============================================================================
# MCP 文档客户端（lazy init）
# ============================================================================

_doc_toolkit = None


def _get_doc_toolkit():
    global _doc_toolkit
    mcp_url = server_config.mcp_doc_url
    if mcp_url and _doc_toolkit is None:
        try:
            from .tools import DocMcpClient, DocToolKit
            client = DocMcpClient(mcp_url)
            client.initialize()
            _doc_toolkit = DocToolKit(client)
            logger.info("MCP 文档客户端已就绪")
        except Exception:
            logger.exception("MCP 文档客户端初始化失败")
            return None
    return _doc_toolkit


_last_result: dict[str, dict[str, str]] = {}


# ============================================================================
# WebSocket 网关
# ============================================================================

class SmartBotGateway:

    def __init__(self) -> None:
        self._ws: websocket.WebSocketApp | None = None
        self._running = False
        self._subscribed = False
        self._heartbeat_stop: threading.Event | None = None

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        self._running = True
        backoff = 1
        while self._running:
            self._subscribed = False
            try:
                self._connect_and_serve()
            except Exception:
                logger.warning("WS 异常，%ds 后重连 (活跃=%d)…",
                               backoff, _active_count(), exc_info=True)
            if not self._running:
                break
            logger.info("⏳ 断线，%ds 后重连…", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)

    def shutdown(self) -> None:
        self._running = False
        if self._heartbeat_stop:
            self._heartbeat_stop.set()
        if self._ws:
            self._ws.close()

    # ------------------------------------------------------------------
    # 连接 + 鉴权
    # ------------------------------------------------------------------

    def _connect_and_serve(self) -> None:
        logger.info("🔌 正在连接企微网关…")
        self._ws = websocket.WebSocketApp(
            smart_config.gateway_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        # **协议层心跳**: 每 20s 发 ping，10s 无 pong 则超时断线
        self._ws.run_forever(ping_interval=20, ping_timeout=10)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        logger.info("✅ 已连接，发送 aibot_subscribe…")
        _send_cmd(ws, "aibot_subscribe", {
            "bot_id": smart_config.bot_id,
            "secret": smart_config.secret,
        })

        # **应用层心跳**: 每 18s 发 JSON 帧，比协议 ping 更可靠
        # (协议级 ping 帧常被公司防火墙/NAT 丢弃)
        self._heartbeat_stop = threading.Event()

        def _app_heartbeat() -> None:
            while not self._heartbeat_stop.is_set():
                time.sleep(18)
                if self._heartbeat_stop.is_set():
                    break
                try:
                    if self._ws and self._ws.sock and self._ws.sock.connected:
                        self._ws.send("{}")
                    else:
                        break
                except Exception:
                    logger.warning("应用层心跳发送失败，WS 可能已断开")
                    break

        threading.Thread(target=_app_heartbeat, daemon=True).start()

    def _on_message(self, ws: websocket.WebSocketApp, raw_message: str) -> None:
        try:
            event = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.warning("非 JSON: %.200s", raw_message)
            return

        cmd = event.get("cmd", "")
        errcode = event.get("errcode", -1)

        if errcode == 0 and not cmd:
            if not self._subscribed:
                self._subscribed = True
                logger.info("✅ 鉴权成功")
            return

        if cmd == "aibot_msg_callback":
            threading.Thread(target=self._handle_callback,
                             args=(event,), daemon=True).start()
        elif cmd == "aibot_event_callback":
            self._handle_event(ws, event)
        else:
            logger.info("忽略: cmd=%r errcode=%s", cmd, errcode)

    def _handle_event(self, ws: websocket.WebSocketApp, event: dict[str, Any]) -> None:
        body = event.get("body", {})
        ev = body.get("event", {})
        if ev.get("eventtype") == "enter_chat":
            req_id = (event.get("headers") or {}).get("req_id", "")
            _send_cmd(ws, "aibot_respond_welcome_msg", {
                "msgtype": "text",
                "text": {"content": "您好！我是 InfoTest Engine 智能助手。可直接发送技术问题。"},
            }, req_id=req_id)

    def _on_error(self, ws: websocket.WebSocketApp, error: Exception) -> None:
        logger.error("WS 错误: %s", error)

    def _on_close(self, ws: websocket.WebSocketApp,
                  code: int | None, msg: str | None) -> None:
        logger.info("WS 关闭: code=%s msg=%s (活跃=%d)", code, msg, _active_count())

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    def _handle_callback(self, event: dict[str, Any]) -> None:
        body = event.get("body", {})
        msgtype = body.get("msgtype", "")
        from_info = body.get("from", {})
        user_id = from_info.get("userid", "unknown")
        headers = event.get("headers", {})
        req_id = headers.get("req_id", "")
        content = ""

        if msgtype == "text":
            content = (body.get("text", {}).get("content") or "").strip()
        elif msgtype == "mixed":
            items = body.get("mixed", {}).get("msg_item", [])
            for item in items:
                if item.get("msgtype") == "text":
                    content = (item.get("text", {}).get("content") or "").strip()
                    break

        logger.info("用户消息: user=%s type=%s content=%.100s",
                     user_id, msgtype, content)

        if not content:
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "stream",
                "stream": {"id": str(uuid.uuid4()), "finish": True,
                           "content": "暂不支持此消息类型"},
            }, req_id=req_id)
            return

        if content in ("停止", "/stop"):
            ok = _cancel_task(user_id)
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "stream",
                "stream": {"id": str(uuid.uuid4()), "finish": True,
                           "content": "⏹ 已终止" if ok else "ℹ 无运行中的任务"},
            }, req_id=req_id)
            return

        if content in ("帮助", "help"):
            tips = ["InfoTest Engine 智能助手\n直接发送技术问题即可。",
                    "• 停止 — 终止任务",
                    "• 帮助 — 显示帮助"]
            if server_config.mcp_doc_url:
                tips.append("• 报告 — 将上次结果生成文档")
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "stream",
                "stream": {"id": str(uuid.uuid4()), "finish": True,
                           "content": "\n".join(tips)},
            }, req_id=req_id)
            return

        if content in ("报告", "/report"):
            self._try_create_report(content, user_id, req_id)
            return

        stream_id = str(uuid.uuid4())
        cancel_evt = _register_task(user_id, stream_id)

        _send_stream(self._ws, stream_id, False,
                     "InfoTest 正在运行，请稍候…", req_id)

        heartbeat_running = True
        start_ts = time.monotonic()

        def _hb() -> None:
            msgs = ["⏳ 仍在处理中…（{elapsed} 分钟）",
                    "🔍 AI 正在检索分析，已等待 {elapsed} 分钟…",
                    "📝 正在整理结果，已过 {elapsed} 分钟…",
                    "⚙️ 执行中，已等待 {elapsed} 分钟…"]
            i = 0
            while heartbeat_running and not cancel_evt.is_set():
                time.sleep(300)
                if not heartbeat_running or cancel_evt.is_set():
                    break
                m = int((time.monotonic() - start_ts) / 60) or 1
                _send_stream(self._ws, stream_id, False,
                             msgs[i % len(msgs)].format(elapsed=m), req_id)
                i += 1

        threading.Thread(target=_hb, daemon=True).start()

        cleaned_query = _clean_content(content, user_id)
        try:
            answer = _call_ist_core(cleaned_query, user_id)
        except SystemExit:
            answer = "⏹ 任务已被终止。"
        except Exception:
            logger.exception("IST-Core 异常: user=%s", user_id)
            answer = "❌ 执行失败，请稍后重试。"
        finally:
            heartbeat_running = False

        if cancel_evt.is_set() and "已被终止" not in answer:
            answer = "⏹ 任务已被终止。"

        total_min = int((time.monotonic() - start_ts) / 60) or 0
        final_md = _format_markdown(content, answer, total_min)

        _last_result[user_id] = {"query": content, "answer": answer}

        _send_stream(self._ws, stream_id, True, final_md, req_id)
        _deregister_task(user_id)

        if len(answer) > 200 and server_config.mcp_doc_url:
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "markdown",
                "markdown": {
                    "content": "> 发送「**报告**」可将以上结果生成文档。",
                },
            }, req_id=_mk_req_id())

    # ------------------------------------------------------------------
    # 报告生成（MCP）
    # ------------------------------------------------------------------

    def _try_create_report(self, query: str, user_id: str, req_id: str) -> None:
        stream_id = str(uuid.uuid4())

        last = _last_result.get(user_id)
        if last:
            query = last["query"]
            answer = last["answer"]
        else:
            answer = ""

        if not answer or answer == "（无回答）":
            _send_stream(self._ws, stream_id, True,
                         "ℹ 还没有可用的分析结果。请先发送一个技术问题。", req_id)
            return

        if not server_config.mcp_doc_url:
            _send_stream(self._ws, stream_id, True,
                         "ℹ 报告功能未配置。请在企微后台授权后设置 WECOM_SMART_MCP_DOC_URL。", req_id)
            return

        _send_stream(self._ws, stream_id, False, "📄 正在生成报告文档…", req_id)

        try:
            from .tools import build_report_markdown
            tk = _get_doc_toolkit()
            if tk is None:
                _send_stream(self._ws, stream_id, True,
                             "❌ MCP 客户端初始化失败, 请检查 WECOM_SMART_MCP_DOC_URL", req_id)
                return

            report_md = build_report_markdown(query, answer)
            doc_url = tk.create_doc_with_content(
                f"InfoTest 报告 - {query[:50]}", report_md,
            )

            if doc_url:
                _send_stream(self._ws, stream_id, True,
                             f"✅ 报告已生成\n\n📄 [点击查看报告]({doc_url})", req_id)
            else:
                _send_stream(self._ws, stream_id, True, "❌ 文档创建失败，请查看日志", req_id)
        except Exception as e:
            logger.exception("报告生成失败")
            _send_stream(self._ws, stream_id, True, f"❌ 报告生成失败: {e}", req_id)


# ============================================================================
# 工具函数
# ============================================================================

def _send_stream(ws, stream_id: str, finish: bool,
                 content: str, req_id: str) -> None:
    _send_cmd(ws, "aibot_respond_msg", {
        "msgtype": "stream",
        "stream": {"id": stream_id, "finish": finish, "content": content},
    }, req_id=req_id)


def _clean_content(raw: str, user_id: str) -> str:
    import re
    cleaned = re.sub(r'@\S+\s*', '', raw).strip()
    return cleaned or raw


def _format_markdown(query: str, answer: str, elapsed_min: int) -> str:
    body = answer
    d = body.encode("utf-8")
    if len(d) > 20000:
        body = d[:20000].decode("utf-8", errors="ignore") + "\n\n> ⚠ 已截断"

    ft = (f"<font color=\"comment\">总耗时约 {elapsed_min} 分钟</font>"
          if elapsed_min > 0
          else "<font color=\"comment\">Powered by IST-Core</font>")

    return (f"## 📋 InfoTest Engine 结果\n"
            f"> **问题：**{query[:100]}\n---\n{body}\n---\n{ft}")
