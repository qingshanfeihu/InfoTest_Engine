r"""企业微信智能机器人 — WebSocket 长连接核心驱动。

基于官方文档:
  - 长连接协议: https://developer.work.weixin.qq.com/document/path/101463
  - 文档工具:    https://developer.work.weixin.qq.com/document/path/101468

保活: 网关不回 opcode 0x9 Pong，用 aibot_subscribe 文本帧 (opcode 0x1) 做心跳，间隔 45s。

会话管理: 空闲超时 30 分钟 或 单会话 20 轮 → 自动切分新会话，防止上下文膨胀/话题混杂。
"""

from __future__ import annotations

import json
import logging
import ctypes
import os
import queue
import threading
import time
import uuid
from collections.abc import Generator
from typing import Any

import websocket

from .config import smart_config, server_config
from .files import download_qywx_file, upload_and_send_file, notify_upload_response

logger = logging.getLogger("wecom_bot_smart.gateway")


# ============================================================================
# IST-Core 调用
# ============================================================================

def _call_ist_core(user_query: str, user_id: str = "smart_user",
                   thread_id: str = "") -> str:
    import os as _os
    _os.environ.setdefault("IST_NON_INTERACTIVE", "1")
    _os.environ.setdefault("IST_LLM_STREAMING", "0")

    from main.ist_core.runner import _ensure_env
    _ensure_env()

    from main.ist_core.graph import build_ist_core_graph
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import HumanMessage

    tid = thread_id or f"smart-{user_id or 'anon'}-{uuid.uuid4().hex[:8]}"
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

    final = result.get("final_answer") or ""
    logger.info("IST-Core 完成: thread=%s len=%d", tid, len(final))
    return final


def _call_ist_core_stream(user_query: str, user_id: str = "smart_user",
                          thread_id: str = "") -> Generator[dict[str, Any], None, str]:
    """流式调用 IST-Core，通过 ``stream_and_collect`` + EventBus sink。

    使用 IST-Core 已有的 ``stream_and_collect`` 函数，它正确处理了
    ``_MainAgentProgressHandler`` 发出的 ``adispatch_custom_event`` 事件。

    作为 sync generator 使用::

        gen = _call_ist_core_stream(query, user_id, thread_id)
        for event in gen:
            if event["type"] == "delta":
                ws.send(event["content"])   # LLM 流式 delta
            elif event["type"] == "thought":
                ws.send(event["content"])   # 思考过程
            elif event["type"] == "tool":
                ws.send(event["content"])   # 工具调用
        # StopIteration.value 即为 final_answer
    """
    import os as _os
    _os.environ.setdefault("IST_NON_INTERACTIVE", "1")

    from main.ist_core.runner import _ensure_env
    _ensure_env()

    from main.ist_core.graph import build_ist_core_graph
    from main.ist_core.streaming import stream_and_collect
    from main.ist_core.events import IstCoreEvent, reset_default_bus
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import HumanMessage

    tid = thread_id or f"smart-{user_id or 'anon'}-{uuid.uuid4().hex[:8]}"
    logger.info("IST-Core 流式开始: thread=%s query=%.100s", tid, user_query)

    q: queue.Queue = queue.Queue()
    final_answer = ""

    def _sink(event: IstCoreEvent) -> None:
        """将 IstCoreEvent 转换为适合企微的 dict 格式放入 queue."""
        try:
            kind = event.get("kind", "")
            payload = event.get("payload", {})
            # DEBUG: 确认事件是否到达
            logger.debug("sink event: kind=%s payload_keys=%s", kind, list(payload.keys()))

            if kind == "llm_token":
                # LLM 流式 delta
                content = payload.get("content", "")
                if content:
                    q.put({"type": "delta", "content": content})
            elif kind == "thought":
                # 思考过程（从 llm_end 或 custom event）
                content = payload.get("content", "")
                if content:
                    q.put({"type": "thought", "content": f"💭 {content}"})
            elif kind == "tool_call" or kind == "tool_start":
                # 工具调用开始
                name = payload.get("name", "工具")
                inp = payload.get("input", {})
                # 格式化 input 显示（避免显示原始字典）
                input_preview = ""
                if isinstance(inp, dict):
                    # 提取关键信息
                    if "skill" in inp:
                        input_preview = inp.get("skill", "")
                        brief = inp.get("brief", "")
                        if brief:
                            input_preview += f" ({brief[:50]}...)" if len(brief) > 50 else f" ({brief})"
                    elif "raw" in inp:
                        raw = inp.get("raw", "")
                        input_preview = raw[:80] if len(raw) > 80 else raw
                    elif "query" in inp:
                        query = inp.get("query", "")
                        input_preview = query[:80] if len(query) > 80 else query
                    else:
                        # 其他情况，显示简短摘要
                        keys = list(inp.keys())[:3]
                        input_preview = ", ".join(keys)
                elif isinstance(inp, str):
                    input_preview = inp[:80] if len(inp) > 80 else inp
                tool_msg = f"🔧 调用 {name}"
                if input_preview:
                    tool_msg += f"\n{input_preview}"
                q.put({"type": "tool", "content": tool_msg})
            elif kind == "tool_result" or kind == "tool_end":
                # 工具调用结束
                name = payload.get("name", "工具")
                q.put({"type": "tool", "content": f"✅ {name} 完成"})
            elif kind == "phase_marker":
                # 阶段标记
                phase = payload.get("phase", "")
                if phase:
                    q.put({"type": "phase", "content": f"📍 {phase}"})
            elif kind == "error" or kind == "run_error":
                # 错误
                error_msg = payload.get("error", "") or payload.get("message", "")
                if error_msg:
                    q.put({"type": "error", "content": error_msg})
            # 其他事件类型忽略（node_start/node_end 等）
        except Exception as e:
            logger.error("_sink 处理异常: %s", e)

    def _run() -> None:
        nonlocal final_answer
        try:
            with InMemorySaver() as saver:
                graph = build_ist_core_graph(checkpointer=saver, checkpointer_mode="async")
                config: dict[str, Any] = {"configurable": {"thread_id": tid}}
                initial_state: dict[str, Any] = {
                    "task_type": "QA",
                    "user_input": user_query,
                    "messages": [HumanMessage(content=user_query)],
                }
                result = stream_and_collect(
                    graph, initial_state, config=config, sinks=[_sink]
                )
                final_answer = result.get("final_answer") or ""
        except Exception as exc:
            logger.exception("IST-Core 流式异常")
            q.put({"type": "error", "content": str(exc)})
        finally:
            q.put(None)  # 结束信号

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    last_event_ts = time.monotonic()
    try:
        while True:
            try:
                item = q.get(timeout=30)  # 30秒超时，保持活跃
            except queue.Empty:
                # 超时，发送心跳消息让用户知道还在运行
                elapsed_min = int((time.monotonic() - last_event_ts) / 60) or 1
                yield {"type": "heartbeat", "content": f"⏳ 仍在处理中（{elapsed_min} 分钟）…"}
                continue

            if item is None:
                break
            if item.get("type") == "error":
                logger.error("IST-Core 流式错误: %s", item["content"])
                final_answer = f"执行失败: {item['content']}"
                break
            last_event_ts = time.monotonic()
            yield item
    finally:
        t.join(timeout=10)

    logger.info("IST-Core 流式完成: thread=%s len=%d", tid, len(final_answer))
    return final_answer


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

# === SE_MANAGEMENT === 会话策略常量 ========================================
MAX_IDLE_SECONDS = 1800        # 30 分钟空闲超时自动切分
MAX_TURNS = 20                 # 单会话上限 20 轮
SESSION_CLEANUP_SECONDS = 7200 # 僵尸会话 2 小时后从内存清理
CLEANUP_INTERVAL = 600         # 每 10 分钟扫描一次

# === SE_MANAGEMENT === 会话元数据: user_id -> {thread_id,last_active,turn_count}
_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def _get_thread_id(user_id: str) -> tuple[str, str | None, int]:
    """返回 (thread_id, auto_split_reason | None, turn_count).

    切分条件:
      1. idle > 30 分钟
      2. turns >= 20 轮
    """
    now = time.time()
    with _sessions_lock:
        sess = _sessions.get(user_id)
        if sess is None:
            return (_new_session_locked(user_id), None, 1)

        idle = now - sess["last_active"]
        turns = sess["turn_count"]
        reason = None
        if idle > MAX_IDLE_SECONDS:
            reason = f"空闲超过 {idle / 60:.0f} 分钟"
        elif turns >= MAX_TURNS:
            reason = f"达到轮数上限（{MAX_TURNS} 轮）"

        if reason:
            logger.info("自动切分会话: user=%s reason=%s old_thread=%s",
                         user_id, reason, sess["thread_id"][-12:])
            tid = _new_session_locked(user_id)
            return (tid, reason, 1)

        # 正常复用
        sess["last_active"] = now
        sess["turn_count"] = turns + 1
        return (sess["thread_id"], None, turns + 1)


def _new_session_locked(user_id: str) -> str:
    """新建会话元数据（需持 _sessions_lock）。"""
    import uuid
    tid = f"smart-{user_id}-{uuid.uuid4().hex[:8]}"
    _sessions[user_id] = {
        "thread_id": tid,
        "last_active": time.time(),
        "turn_count": 1,
    }
    logger.info("新会话: user=%s thread=%s", user_id, tid[-12:])
    return tid


# === SE_MANAGEMENT === 后台自洁线程 =======================================
_cleanup_started = False


def _start_cleanup_thread() -> None:
    """每 10 分钟扫描一次，清理空闲超 2 小时的僵尸会话。"""
    global _cleanup_started
    if _cleanup_started:
        return
    _cleanup_started = True

    def _cleaner() -> None:
        while True:
            time.sleep(CLEANUP_INTERVAL)
            now = time.time()
            with _sessions_lock:
                stale = [uid for uid, s in _sessions.items()
                         if now - s["last_active"] > SESSION_CLEANUP_SECONDS]
                for uid in stale:
                    s = _sessions.pop(uid)
                    logger.info("清理僵尸会话: user=%s thread=%s idle=%.1fh",
                                 uid, s["thread_id"][-12:],
                                 (now - s["last_active"]) / 3600)

    threading.Thread(target=_cleaner, daemon=True).start()
    logger.info("会话自洁线程已启动 (扫描间隔=%ds 清理阈值=%ds)",
                 CLEANUP_INTERVAL, SESSION_CLEANUP_SECONDS)


# ============================================================================
# WebSocket 网关
# ============================================================================

class SmartBotGateway:

    def __init__(self) -> None:
        self._ws: websocket.WebSocketApp | None = None
        self._running = False
        self._subscribed = False
        self._heartbeat: threading.Event = threading.Event()

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        self._running = True
        # === SE_MANAGEMENT === 启动会话自洁
        _start_cleanup_thread()
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
            for _ in range(int(backoff * 2)):
                if not self._running:
                    break
                time.sleep(0.5)
            backoff = min(backoff * 2, 30)

    def shutdown(self) -> None:
        self._running = False
        self._heartbeat.set()
        if self._ws:
            self._ws.close()

    # ------------------------------------------------------------------
    # 连接 + 鉴权
    # ------------------------------------------------------------------

    def _connect_and_serve(self) -> None:
        logger.info("正在连接企微网关…")
        self._ws = websocket.WebSocketApp(
            smart_config.gateway_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws.run_forever(ping_interval=0)  # gateway never replies to opcode 0x9 pong

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        logger.info("已连接，发送 aibot_subscribe…")
        _send_cmd(ws, "aibot_subscribe", {
            "bot_id": smart_config.bot_id,
            "secret": smart_config.secret,
        })

        self._heartbeat.clear()

        def _keeper() -> None:
            while not self._heartbeat.wait(45):
                if self._heartbeat.is_set():
                    break
                try:
                    if self._ws and self._ws.sock and self._ws.sock.connected:
                        _send_cmd(self._ws, "aibot_subscribe", {
                            "bot_id": smart_config.bot_id,
                            "secret": smart_config.secret,
                        })
                except Exception:
                    break

        threading.Thread(target=_keeper, daemon=True).start()

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
                logger.info("鉴权成功")
            return

        if cmd == "aibot_msg_callback":
            threading.Thread(target=self._handle_callback,
                             args=(event,), daemon=True).start()
        elif cmd == "aibot_event_callback":
            self._handle_event(ws, event)
        elif cmd in ("aibot_upload_media_init", "aibot_upload_media_chunk",
                     "aibot_upload_media_finish"):
            hdrs = event.get("headers", {})
            rid = hdrs.get("req_id", "")
            notify_upload_response(ws, rid, event.get("body", {}))
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
    # 文件消息处理
    # ------------------------------------------------------------------

    def _handle_file_msg(self, body: dict, user_id: str,
                         msgtype: str, req_id: str) -> None:
        media_info = body.get(msgtype, {})
        file_url = media_info.get("url", "")
        aeskey = media_info.get("aeskey", "")
        if not file_url or not aeskey:
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "stream",
                "stream": {"id": str(uuid.uuid4()), "finish": True,
                           "content": f"无法下载{msgtype}消息"},
            }, req_id=req_id)
            return
        stream_id = str(uuid.uuid4())
        _send_stream(self._ws, stream_id, False, f"正在接收{msgtype}文件...", req_id)
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            save_dir = os.path.join(project_root, "workspace", "inputs", _safe_user_dir(user_id))
            save_path = download_qywx_file(file_url, aeskey, save_dir)
            size_kb = os.path.getsize(save_path) / 1024
            _send_stream(self._ws, stream_id, True,
                         f"文件已保存\n{os.path.basename(save_path)} ({size_kb:.1f} KB)\n\n"
                         f"正在调用 IST-Core 分析文件内容...", req_id)
            rel_path = os.path.relpath(save_path, project_root).replace("\\", "/")
            agent_query = (
                f"用户通过企业微信发送了一个文件: {rel_path}\n"
                f"文件大小: {size_kb:.1f} KB\n"
                f"请用 fs_read 读取此文件，分析其内容并告知用户。"
            )
            self._run_agent_task(user_id, agent_query, req_id)
        except Exception as e:
            logger.exception("文件下载失败")
            _send_stream(self._ws, stream_id, True, f"文件下载失败: {e}", req_id)

    def _run_agent_task(self, user_id: str, query: str, req_id: str) -> None:
        # === SE_MANAGEMENT === 取/建会话，获取 thread_id + 切分提示
        tid, split_reason, turn_count = _get_thread_id(user_id)

        stream_id = str(uuid.uuid4())
        cancel_evt = _register_task(user_id, stream_id)
        start_ts = time.monotonic()

        # --- 流式调用 IST-Core，逐 delta 发送到企微 ---
        # 首先发送初始提示
        seq = 0
        _send_stream_delta(self._ws, stream_id, seq, "InfoTest 正在运行，请稍候…", False, req_id)

        answer = ""
        gen = _call_ist_core_stream(query, user_id, thread_id=tid)
        try:
            while True:
                try:
                    event = next(gen)
                except StopIteration as exc:
                    answer = exc.value or ""
                    break

                if cancel_evt.is_set():
                    gen.close()
                    answer = "任务已被终止。"
                    break

                # 根据事件类型处理
                event_type = event.get("type", "")
                event_content = event.get("content", "")

                if event_type == "delta":
                    # LLM 流式 delta，直接发送
                    seq += 1
                    _send_stream_delta(self._ws, stream_id, seq, event_content, False, req_id)
                elif event_type == "heartbeat":
                    # 心跳消息，不增加 seq（保持流式序列）
                    _send_stream_delta(self._ws, stream_id, seq, event_content, False, req_id)
                elif event_type in ("thought", "tool", "phase"):
                    # 中间过程，作为独立消息发送
                    seq += 1
                    _send_stream_delta(self._ws, stream_id, seq, event_content, False, req_id)

        except SystemExit:
            answer = "任务已被终止。"
        except Exception:
            logger.exception("IST-Core 流式异常: user=%s", user_id)
            answer = "执行失败，请稍后重试。"
        finally:
            try:
                gen.close()
            except Exception:
                pass

        if cancel_evt.is_set() and "已被终止" not in answer:
            answer = "任务已被终止。"

        total_min = int((time.monotonic() - start_ts) / 60) or 0
        final_md = _format_markdown(
            query[:100], answer, total_min, split_reason=split_reason,
            turn_count=turn_count,
        )
        _last_result[user_id] = {"query": query[:100], "answer": answer}

        # 发送最终流式消息（is_end=True），附带完整格式化 markdown
        _send_stream_delta(self._ws, stream_id, seq + 1, final_md, True, req_id)
        _deregister_task(user_id)

    def _send_file_result(self, local_path: str, user_id: str,
                          req_id: str, note: str = "") -> None:
        stream_id = str(uuid.uuid4())
        if not os.path.isfile(local_path):
            _send_stream(self._ws, stream_id, True, f"文件不存在: {local_path}", req_id)
            return
        _send_stream(self._ws, stream_id, False,
                     f"正在上传: {os.path.basename(local_path)}...", req_id)
        try:
            media_id = upload_and_send_file(
                self._ws, local_path, stream_id, req_id, user_id,
            )
            if media_id:
                fname = os.path.basename(local_path)
                fsize_kb = os.path.getsize(local_path) / 1024
                _send_stream(self._ws, stream_id, True,
                             f"{note}\n{fname} ({fsize_kb:.1f} KB)", req_id)
        except Exception as e:
            logger.exception("文件上传失败")
            _send_stream(self._ws, stream_id, True, f"文件上传失败: {e}", req_id)

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

        if msgtype in ("file", "image", "voice", "video"):
            self._handle_file_msg(body, user_id, msgtype, req_id)
            return

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

        if content in ("停止", "终止", "强制终止", "/stop", "/kill", "/abort"):
            ok = _cancel_task(user_id)
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "stream",
                "stream": {"id": str(uuid.uuid4()), "finish": True,
                           "content": "✅ 已强制终止任务" if ok else "⚠️ 无运行中的任务"},
            }, req_id=req_id)
            return

        if content in ("新对话", "新会话", "重置", "/new", "/reset"):
            # 手动重置会话：先取消正在跑的任务，再新建 thread
            _cancel_task(user_id)
            new_tid = _new_session_locked(user_id)
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "stream",
                "stream": {"id": str(uuid.uuid4()), "finish": True,
                           "content": f"已开启新对话\nThread: {new_tid[-12:]}"},
            }, req_id=req_id)
            return

        if content in ("帮助", "help"):
            tips = [
                "InfoTest Engine 智能助手",
                "",
                "直接发送技术问题即可获得解答。",
                "",
                "命令列表:",
                "  新会话 / 新对话 -- 开启新对话",
                "  停止 / 终止 -- 强制终止当前任务",
                "  帮助 -- 显示此帮助",
            ]
            if server_config.mcp_doc_url:
                tips.append("  报告 -- 将结果生成文档")
            _send_cmd(self._ws, "aibot_respond_msg", {
                "msgtype": "stream",
                "stream": {"id": str(uuid.uuid4()), "finish": True,
                           "content": "\n".join(tips)},
            }, req_id=req_id)
            return

        if content in ("报告", "/report"):
            self._try_create_report(content, user_id, req_id)
            return

        # === SE_MANAGEMENT === 取/建会话，获取 thread_id + 切分提示
        tid, split_reason, turn_count = _get_thread_id(user_id)

        stream_id = str(uuid.uuid4())
        cancel_evt = _register_task(user_id, stream_id)
        start_ts = time.monotonic()

        cleaned_query = _clean_content(content, user_id)

        # --- 流式调用 IST-Core，逐 delta 发送到企微 ---
        # 首先发送初始提示
        seq = 0
        _send_stream_delta(self._ws, stream_id, seq, "InfoTest 正在运行，请稍候…", False, req_id)

        answer = ""
        gen = _call_ist_core_stream(cleaned_query, user_id, thread_id=tid)
        try:
            while True:
                try:
                    event = next(gen)
                except StopIteration as exc:
                    answer = exc.value or ""
                    break

                if cancel_evt.is_set():
                    gen.close()
                    answer = "任务已被终止。"
                    break

                # 根据事件类型处理
                event_type = event.get("type", "")
                event_content = event.get("content", "")

                if event_type == "delta":
                    # LLM 流式 delta，直接发送
                    seq += 1
                    _send_stream_delta(self._ws, stream_id, seq, event_content, False, req_id)
                elif event_type == "heartbeat":
                    # 心跳消息，不增加 seq（保持流式序列）
                    _send_stream_delta(self._ws, stream_id, seq, event_content, False, req_id)
                elif event_type in ("thought", "tool", "phase"):
                    # 中间过程，作为独立消息发送
                    seq += 1
                    _send_stream_delta(self._ws, stream_id, seq, event_content, False, req_id)

        except SystemExit:
            answer = "任务已被终止。"
        except Exception:
            logger.exception("IST-Core 流式异常: user=%s", user_id)
            answer = "执行失败，请稍后重试。"
        finally:
            try:
                gen.close()
            except Exception:
                pass

        if cancel_evt.is_set() and "已被终止" not in answer:
            answer = "任务已被终止。"

        total_min = int((time.monotonic() - start_ts) / 60) or 0
        # === SE_MANAGEMENT === 自动切分时在回复中追加弱提示
        final_md = _format_markdown(
            content, answer, total_min, split_reason=split_reason,
            turn_count=turn_count,
        )

        _last_result[user_id] = {"query": content, "answer": answer}

        # 发送最终流式消息（is_end=True），附带完整格式化 markdown
        _send_stream_delta(self._ws, stream_id, seq + 1, final_md, True, req_id)
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
        if not answer:
            _send_stream(self._ws, stream_id, True,
                         "还没有可用的分析结果。请先发送一个技术问题。", req_id)
            return
        if not server_config.mcp_doc_url:
            _send_stream(self._ws, stream_id, True,
                         "报告功能未配置。请在企微后台授权后设置 WECOM_SMART_MCP_DOC_URL。", req_id)
            return
        _send_stream(self._ws, stream_id, False, "正在生成报告文档…", req_id)
        try:
            from .tools import build_report_markdown
            tk = _get_doc_toolkit()
            if tk is None:
                _send_stream(self._ws, stream_id, True,
                             "MCP 客户端初始化失败, 请检查 WECOM_SMART_MCP_DOC_URL", req_id)
                return
            report_md = build_report_markdown(query, answer)
            doc_url = tk.create_doc_with_content(
                f"InfoTest 报告 - {query[:50]}", report_md,
            )
            if doc_url:
                _send_stream(self._ws, stream_id, True,
                             f"报告已生成\n\n[点击查看报告]({doc_url})", req_id)
            else:
                _send_stream(self._ws, stream_id, True, "文档创建失败，请查看日志", req_id)
        except Exception as e:
            logger.exception("报告生成失败")
            _send_stream(self._ws, stream_id, True, f"报告生成失败: {e}", req_id)


# ============================================================================
# 工具函数
# ============================================================================

def _send_stream(ws, stream_id: str, finish: bool,
                 content: str, req_id: str) -> None:
    _send_cmd(ws, "aibot_respond_msg", {
        "msgtype": "stream",
        "stream": {"id": stream_id, "finish": finish, "content": content},
    }, req_id=req_id)


def _send_stream_delta(ws, stream_id: str, stream_seq: int, content: str,
                       is_end: bool, req_id: str) -> None:
    """发送流式 delta 报文（企业微信规范）。

    每个 delta 报文包含:
      - ``is_stream=True``  标识流式消息
      - ``stream_seq``      严格递增的序号
      - ``is_end``          完毕时置为 ``True``
      - ``finish``          与 is_end 同步，兼容旧版
    """
    _send_cmd(ws, "aibot_respond_msg", {
        "msgtype": "stream",
        "stream": {
            "id": stream_id,
            "finish": is_end,
            "content": content,
            "is_stream": True,
            "stream_seq": stream_seq,
            "is_end": is_end,
        },
    }, req_id=req_id)


def _safe_user_dir(user_id: str) -> str:
    import re
    return re.sub(r'[<>:"/\\|?*]', '_', user_id.strip()) or "unknown"


def _clean_content(raw: str, user_id: str) -> str:
    import re
    cleaned = re.sub(r'@\S+\s*', '', raw).strip()
    return cleaned or raw


# === SE_MANAGEMENT === 切分提示注入
def _format_markdown(query: str, answer: str, elapsed_min: int,
                     split_reason: str | None = None,
                     turn_count: int = 0) -> str:
    body = answer
    d = body.encode("utf-8")
    if len(d) > 20000:
        body = d[:20000].decode("utf-8", errors="ignore") + "\n\n> 已截断"

    prefix = ""
    if split_reason:
        prefix = (
            f"> <font color=\"warning\">系统提示：由于当前会话{split_reason}，"
            f"已自动为您开启新对话以保障响应速度与准确度。</font>\n\n"
        )

    # 显示轮数（如 5/20）
    turn_info = f"会话轮数: {turn_count}/{MAX_TURNS}" if turn_count > 0 else ""

    ft = (f"<font color=\"comment\">总耗时约 {elapsed_min} 分钟</font>"
          if elapsed_min > 0
          else "<font color=\"comment\">Powered by IST-Core</font>")

    footer = ft
    if turn_info:
        footer = f"{turn_info} | {ft}"

    return (f"## InfoTest Engine 结果\n"
            f"{prefix}"
            f"> **问题：**{query[:100]}\n---\n{body}\n---\n{footer}")
