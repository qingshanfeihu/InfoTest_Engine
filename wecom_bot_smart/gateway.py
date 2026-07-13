r"""企业微信智能机器人 — 基于官方 wecom-aibot-sdk。

用 WSClient 管理 WS 连接（鉴权/心跳/重连/消息路由），
业务层专注 IST-Core 流式调用、会话管理、ask_user 集成。
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import queue
import re
import threading
import time
import uuid
from collections.abc import Generator
from typing import Any

from .config import smart_config, server_config
from .presentation import UserVisibleEvent, UserEventType, ThoughtRenderer

logger = logging.getLogger("wecom_bot_smart.gateway")


# ============================================================================
# IST-Core 调用（不变）
# ============================================================================

def _call_ist_core_stream(user_query: str, user_id: str = "smart_user",
                          thread_id: str = "",
                          written_files: list | None = None) -> Generator[dict[str, Any], None, str]:
    """流式调用 IST-Core，通过 ``stream_and_collect`` + EventBus sink。"""
    import os as _os
    _os.environ["IST_WECOM_BOT"] = "1"

    from main.ist_core.runner import _ensure_env
    _ensure_env()

    from main.ist_core.graph import build_ist_core_graph
    from main.ist_core.streaming import stream_and_collect
    from main.ist_core.events import IstCoreEvent
    from langgraph.checkpoint.memory import InMemorySaver
    from langchain_core.messages import HumanMessage

    tid = thread_id or f"smart-{user_id or 'anon'}-{uuid.uuid4().hex[:8]}"
    logger.info("IST-Core 流式开始: thread=%s query=%.100s", tid, user_query)

    q: queue.Queue = queue.Queue()
    final_answer = ""

    def _sink(event: IstCoreEvent) -> None:
        """将 IstCoreEvent 转换为 UserVisibleEvent 推入队列。

        内部工具名、原始参数、LLM 思考文本均不进入队列。
        written_files 追踪逻辑保留（文件发送功能依赖）。
        """
        try:
            kind = event.get("kind", "")
            payload = event.get("payload", {})
            logger.debug("sink event: kind=%s", kind)

            # --- 工具调用开始 ---
            if kind == "tool_call" or kind == "tool_start":
                name = payload.get("name", "")
                # written_files 追踪（保留，不因抽象而丢失）
                inp = payload.get("input", {})
                wf = ""
                if written_files is not None and name in ("fs_write", "fs_edit"):
                    fp = inp.get("path") or inp.get("file_path") or ""
                    if fp:
                        written_files.append(fp)
                        wf = fp
                        logger.info("sink 追踪到文件写入: %s", fp)
                q.put(UserVisibleEvent(
                        type=UserEventType.TOOL_STATUS,
                        tool_name=name,
                        metadata={"input": inp} if isinstance(inp, dict) else {},
                        written_file=wf,
                    ))

            # --- 工具调用结束 ---
            elif kind == "tool_result" or kind == "tool_end":
                name = payload.get("name", "")
                q.put(UserVisibleEvent(
                    type=UserEventType.TOOL_STATUS,
                    tool_name=name,
                    metadata={"status": "done"},
                ))

            # --- LLM 思考（thought / final_thought） ---
            elif kind == "llm_end" and payload.get("name") in ("thought", "final_thought"):
                q.put(UserVisibleEvent(type=UserEventType.THINKING))

            # --- 阶段标记 ---
            elif kind == "phase_marker":
                q.put(UserVisibleEvent(type=UserEventType.THINKING))

            # --- 错误 ---
            elif kind == "error" or kind == "run_error":
                error_msg = payload.get("error", "") or payload.get("message", "")
                if error_msg:
                    q.put(UserVisibleEvent(
                        type=UserEventType.ERROR,
                        content=error_msg,
                    ))

            # --- ask_user ---
            elif kind == "ask_user_request":
                q.put(UserVisibleEvent(
                    type=UserEventType.ASK_USER,
                    metadata=payload,
                ))

            # llm_token / info / node_start/end → 不进入用户通道
        except Exception as e:
            logger.error("_sink 处理异常: %s", e)

    def _run() -> None:
        nonlocal final_answer
        try:
            with InMemorySaver() as saver:
                graph = build_ist_core_graph(checkpointer=saver, checkpointer_mode="async")
                config: dict[str, Any] = {"configurable": {"thread_id": tid, "wx_user_id": user_id}}
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
            logger.exception("IST-Core 流式异常 (thread)")
            q.put(UserVisibleEvent(type=UserEventType.ERROR, content=str(exc)))
        finally:
            q.put(None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    last_event_ts = time.monotonic()
    try:
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                elapsed_min = int((time.monotonic() - last_event_ts) / 60) or 1
                yield UserVisibleEvent(
                    type=UserEventType.HEARTBEAT,
                    content=f"⏳ 仍在处理中（{elapsed_min} 分钟）…",
                )
                continue
            if item is None:
                break
            if isinstance(item, UserVisibleEvent) and item.type == UserEventType.ERROR:
                logger.error("IST-Core 流式错误: %s", item.content)
                final_answer = f"执行失败: {item.content}"
                break
            last_event_ts = time.monotonic()
            yield item
        # --- generator 主循环结束 ---
        # 排空 queue 中剩余事件（防止 race condition：generator 先返回，
        # ASK_USER 等事件还在 queue 中未被 drain 消费）
        drained = 0
        while not q.empty():
            leftover = q.get_nowait()
            if leftover is None or not isinstance(leftover, UserVisibleEvent):
                continue
            logger.debug("generator: 排空残留事件 type=%s tool=%s",
                        leftover.type.value, leftover.tool_name)
            yield leftover
            drained += 1
        if drained:
            logger.debug("generator: 共排空 %d 个残留事件", drained)
    finally:
        t.join(timeout=10)

    logger.info("IST-Core 流式完成: thread=%s len=%d", tid, len(final_answer))
    return final_answer


# ============================================================================
# 任务注册表（不变）
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
# 会话管理（不变）
# ============================================================================

MAX_IDLE_SECONDS = 1800
MAX_TURNS = 20
SESSION_CLEANUP_SECONDS = 7200
CLEANUP_INTERVAL = 600

_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def _get_thread_id(user_id: str) -> tuple[str, str | None, int]:
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
            logger.info("自动切分会话: user=%s reason=%s", user_id, reason)
            tid = _new_session_locked(user_id)
            return (tid, reason, 1)
        sess["last_active"] = now
        sess["turn_count"] = turns + 1
        return (sess["thread_id"], None, turns + 1)


def _new_session_locked(user_id: str) -> str:
    tid = f"smart-{user_id}-{uuid.uuid4().hex[:8]}"
    _sessions[user_id] = {
        "thread_id": tid,
        "last_active": time.time(),
        "turn_count": 1,
    }
    logger.info("新会话: user=%s thread=%s", user_id, tid[-12:])
    return tid


_cleanup_started = False


def _start_cleanup_thread() -> None:
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
                    logger.info("清理僵尸会话: user=%s idle=%.1fh",
                                uid, (now - s["last_active"]) / 3600)

    threading.Thread(target=_cleaner, daemon=True).start()


# ============================================================================
# 工具函数
# ============================================================================

_last_result: dict[str, dict[str, str]] = {}

_FILE_DELIVERY_KEYWORDS = (
    "发过来", "发一下", "发给我", "发来", "发个文件", "发文件",
    "把文件", "把excel", "把xlsx", "把csv", "把文档", "把报告",
    "发excel", "发xlsx", "发csv", "发文档", "发报告",
    "文件发", "excel发", "文档发", "报告发",
    "下载文件", "给我文件", "给我excel", "给我文档",
    "文件下载", "发送文件", "send file", "send the file",
)


def _wants_file(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _FILE_DELIVERY_KEYWORDS)


def _safe_user_dir(user_id: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', user_id.strip()) or "unknown"


def _clean_content(raw: str, user_id: str) -> str:
    cleaned = re.sub(r'@\S+\s*', '', raw).strip()
    return cleaned or raw


def _format_markdown(query: str, answer: str, elapsed_min: int,
                     split_reason: str | None = None,
                     turn_count: int = 0,
                     process_summary: str = "") -> str:
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
    turn_info = f"🔄 会话轮数: {turn_count}/{MAX_TURNS}" if turn_count > 0 else ""
    ft = (f"⏱ 总耗时约 {elapsed_min} 分钟"
          if elapsed_min > 0
          else "🚀 Powered by IST-Core")
    footer = f"{turn_info} | {ft}" if turn_info else ft
    process_section = f"\n{process_summary}\n" if process_summary else ""
    return (f"## InfoTest Engine 结果\n{prefix}"
            f"> **问题：**{query[:100]}\n---\n{body}\n---"
            f"{process_section}\n---\n{footer}")


# MCP 文档客户端
_doc_toolkit = None


def _get_doc_toolkit():
    global _doc_toolkit
    mcp_url = server_config.mcp_doc_url
    if mcp_url and _doc_toolkit is None:
        try:
            from .tools import DocMcpClient, DocToolKit
            c = DocMcpClient(mcp_url)
            c.initialize()
            _doc_toolkit = DocToolKit(c)
            logger.info("MCP 文档客户端已就绪")
        except Exception:
            logger.exception("MCP 文档客户端初始化失败")
            return None
    return _doc_toolkit


# 用户目录缓存
_user_display_cache: dict[str, str] = {}
_access_token: str = ""
_access_token_expires_at: float = 0.0
_access_token_lock = threading.Lock()


def _get_or_fetch_access_token() -> str:
    global _access_token, _access_token_expires_at
    now = time.time()
    if _access_token and now < _access_token_expires_at - 120:
        return _access_token
    with _access_token_lock:
        if _access_token and now < _access_token_expires_at - 120:
            return _access_token
        import requests as _req
        resp = _req.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": smart_config.corp_id or "",
                    "corpsecret": smart_config.secret},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode", -1) != 0:
            logger.warning("获取 access_token 失败: %s", data.get("errmsg", ""))
            return ""
        _access_token = data["access_token"]
        _access_token_expires_at = now + data.get("expires_in", 7200)
        return _access_token


def _resolve_user_dir(user_id: str) -> str:
    if user_id and not user_id.startswith(("wm", "wo", "wp")):
        return _safe_user_dir(user_id)
    if user_id in _user_display_cache:
        return _user_display_cache[user_id]
    display = _safe_user_dir(user_id)
    try:
        import requests as _req
        token = _get_or_fetch_access_token()
        if token:
            resp = _req.get(
                "https://qyapi.weixin.qq.com/cgi-bin/user/get",
                params={"access_token": token, "userid": user_id},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errcode") == 0:
                    name = data.get("name", "")
                    if name:
                        display = _safe_user_dir(name)
                        logger.info("用户 %s → 目录名 %s", user_id, display)
    except Exception:
        logger.debug("查询用户信息失败: %s", user_id, exc_info=True)
    _user_display_cache[user_id] = display
    return display


# ============================================================================
# SmartBotGateway — 基于官方 SDK
# ============================================================================

class SmartBotGateway:

    def __init__(self) -> None:
        self._client = None  # WSClient, lazy init in run_async
        self._loop: asyncio.AbstractEventLoop | None = None  # SDK event loop
        self._running = False
        # 保存最近的 frame 引用（用于 reply 获取 req_id）
        self._last_frame: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------

    def run_forever(self) -> None:
        """同步入口，内部启动 asyncio event loop。"""
        self._running = True
        _start_cleanup_thread()
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        """异步主循环：创建 WSClient、注册事件、连接。"""
        from wecom_aibot_sdk import WSClient

        self._loop = asyncio.get_running_loop()
        self._main_task = asyncio.current_task()

        self._client = WSClient(
            bot_id=smart_config.bot_id,
            secret=smart_config.secret,
            ws_url=smart_config.gateway_url or "",
        )

        self._setup_events()

        logger.info("正在连接企微网关…")
        await self._client.connect()
        logger.info("已连接")

        # 保持运行直到被 shutdown() 取消
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("正在断开连接…")
            await self._client.disconnect()
            logger.info("已断开")

    def shutdown(self) -> None:
        self._running = False
        task = getattr(self, "_main_task", None)
        loop = getattr(self, "_loop", None)
        if task and loop and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)

    # ------------------------------------------------------------------
    # SDK 事件注册
    # ------------------------------------------------------------------

    def _setup_events(self) -> None:
        c = self._client
        gw = self  # 闭包引用

        async def _on_auth():
            logger.info("鉴权成功")

        async def _on_message(frame):
            gw._last_frame = frame
            threading.Thread(target=gw._handle_callback,
                             args=(frame,), daemon=True).start()

        async def _on_enter_chat(frame):
            try:
                await c.reply_welcome(frame, {
                    "msgtype": "text",
                    "text": {"content": "您好！我是 InfoTest Engine 智能助手。可直接发送技术问题。"},
                })
            except Exception:
                logger.debug("欢迎消息发送失败", exc_info=True)

        async def _on_disconnect(reason):
            logger.info("WS 断开: %s (活跃=%d)", reason, _active_count())

        async def _on_error(error):
            logger.error("WS 错误: %s", error)

        c.on("authenticated", _on_auth)
        c.on("message.text", _on_message)
        c.on("message.mixed", _on_message)
        c.on("message.file", _on_message)
        c.on("message.image", _on_message)
        c.on("message.voice", _on_message)
        c.on("message.video", _on_message)
        c.on("event.enter_chat", _on_enter_chat)
        c.on("disconnected", _on_disconnect)
        c.on("error", _on_error)

    # ------------------------------------------------------------------
    # 异步 → 同步桥接
    # ------------------------------------------------------------------

    def _run_coro(self, coro) -> Any:
        """从 sync 线程调 async 方法。异常直接传播。"""
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.error("event loop 不可用")
            return None
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=30)

    # ------------------------------------------------------------------
    # 流式推送（SDK reply_stream）
    # ------------------------------------------------------------------

    def _reply_stream(self, frame: dict, stream_id: str,
                      content: str, finish: bool = False) -> tuple[bool, str]:
        """通过 SDK 发流式消息。返回 (success, stream_id)。

        企微流式消息 10 分钟过期（errcode=846608），自动用新 stream_id 重试。
        """
        try:
            result = self._run_coro(
                self._client.reply_stream(frame, stream_id, content, finish=finish)
            )
            if result is not None:
                return True, stream_id
        except Exception as e:
            if "846608" in str(e):
                logger.info("stream 过期（10分钟），创建新 stream 重试")
                new_sid = str(uuid.uuid4())
                try:
                    result = self._run_coro(
                        self._client.reply_stream(frame, new_sid, content, finish=finish)
                    )
                    if result is not None:
                        return True, new_sid
                except Exception:
                    logger.exception("重试发送失败")
            else:
                logger.exception("异步调用失败")
        return False, stream_id

    def _reply(self, frame: dict, body: dict) -> bool:
        """通过 SDK 发普通回复。"""
        try:
            result = self._run_coro(
                self._client.reply(frame, body)
            )
            return result is not None
        except Exception:
            logger.exception("reply 失败")
            return False

    def _reply_markdown(self, frame: dict, content: str) -> bool:
        """发 markdown 普通消息。"""
        return self._reply(frame, {
            "msgtype": "markdown",
            "markdown": {"content": content},
        })

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    def _handle_callback(self, frame: dict[str, Any]) -> None:
        body = frame.get("body", {})
        msgtype = body.get("msgtype", "")
        from_info = body.get("from", {})
        user_id = from_info.get("userid", "unknown")
        req_id = frame.get("headers", {}).get("req_id", "")
        content = ""

        if msgtype in ("file", "image", "voice", "video"):
            self._handle_file_msg(frame, body, user_id, msgtype, req_id)
            return

        if msgtype == "text":
            content = (body.get("text", {}).get("content") or "").strip()
        elif msgtype == "mixed":
            items = body.get("mixed", {}).get("msg_item", [])
            for item in items:
                if item.get("msgtype") == "text":
                    content = (item.get("text", {}).get("content") or "").strip()
                    break

        logger.info("用户消息: user=%s type=%s content=%.100s", user_id, msgtype, content)

        if not content:
            self._reply_stream(frame, str(uuid.uuid4()), "暂不支持此消息类型", finish=True)
            return

        # ask_user 拦截
        from main.ist_core.tools.ask_user import list_pending_questions, submit_answers
        pending = list_pending_questions()
        if pending:
            pq = pending[0]
            qid = pq.get("question_id", "")
            questions = pq.get("questions") or []
            answers = {}
            for q_item in questions:
                q_text = q_item.get("question", "")
                opts = q_item.get("options") or []
                matched = False
                for idx, opt in enumerate(opts):
                    label = opt.get("label", "")
                    if content.strip() == str(idx + 1) or label in content:
                        answers[q_text] = label
                        matched = True
                        break
                if not matched:
                    answers[q_text] = content.strip()
            if qid:
                submit_answers(qid, answers)
                self._reply_stream(frame, str(uuid.uuid4()),
                                   f"✅ 已收到您的回答：{content.strip()}", finish=True)
                logger.info("ask_user 答案已提交: qid=%s answer=%.100s", qid, content)
            return

        # 命令
        if content in ("停止", "终止", "强制终止", "/stop", "/kill", "/abort"):
            ok = _cancel_task(user_id)
            self._reply_stream(frame, str(uuid.uuid4()),
                               "✅ 已强制终止任务" if ok else "⚠️ 无运行中的任务",
                               finish=True)
            return

        if content in ("新对话", "新会话", "重置", "/new", "/reset"):
            _cancel_task(user_id)
            new_tid = _new_session_locked(user_id)
            self._reply_stream(frame, str(uuid.uuid4()),
                               f"已开启新对话\nThread: {new_tid[-12:]}", finish=True)
            return

        if content in ("帮助", "help"):
            tips = [
                "InfoTest Engine 智能助手", "",
                "直接发送技术问题即可获得解答。", "",
                "命令列表:",
                "  新会话 / 新对话 -- 开启新对话",
                "  停止 / 终止 -- 强制终止当前任务",
                "  帮助 -- 显示此帮助",
            ]
            if server_config.mcp_doc_url:
                tips.append("  报告 -- 将结果生成文档")
            self._reply_stream(frame, str(uuid.uuid4()), "\n".join(tips), finish=True)
            return

        if content in ("报告", "/report"):
            self._try_create_report(frame, content, user_id, req_id)
            return

        # 正常查询
        self._run_query(frame, user_id, content, req_id)

    # ------------------------------------------------------------------
    # 文件消息处理
    # ------------------------------------------------------------------

    def _handle_file_msg(self, frame: dict, body: dict, user_id: str,
                         msgtype: str, req_id: str) -> None:
        from .files import download_qywx_file
        media_info = body.get(msgtype, {})
        file_url = media_info.get("url", "")
        aeskey = media_info.get("aeskey", "")
        if not file_url or not aeskey:
            self._reply_stream(frame, str(uuid.uuid4()),
                               f"无法下载{msgtype}消息", finish=True)
            return
        stream_id = str(uuid.uuid4())
        self._reply_stream(frame, stream_id, f"正在接收{msgtype}文件...")
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            save_dir = os.path.join(project_root, "workspace", "inputs", _resolve_user_dir(user_id))
            save_path = download_qywx_file(file_url, aeskey, save_dir)
            size_kb = os.path.getsize(save_path) / 1024
            size_mb = size_kb / 1024
            if size_kb <= 200:
                read_first_kb = 0
            elif size_mb <= 5:
                read_first_kb = 80
            else:
                read_first_kb = 100
            self._reply_stream(frame, stream_id,
                               f"文件已保存\n{os.path.basename(save_path)} ({size_kb:.1f} KB)\n\n"
                               f"正在调用 IST-Core 分析文件内容...", finish=True)
            rel_path = os.path.relpath(save_path, project_root).replace("\\", "/")
            if read_first_kb > 0:
                read_cmd = (
                    f"请用 `fs_read({rel_path!r}, offset=0, limit={read_first_kb * 1024})` "
                    f"只读前 {read_first_kb}KB。读完把内容结构和关键信息回显给用户，"
                    f"询问是否需要深入特定部分的详细内容。"
                )
            else:
                read_cmd = f"请用 fs_read 读取 {rel_path!r}，分析其内容并告知用户。"
            agent_query = (
                f"用户通过企业微信发送了一个文件: {rel_path}\n"
                f"文件大小: {size_mb:.1f} MB\n{read_cmd}"
            )
            self._run_query(frame, user_id, agent_query, req_id)
        except Exception as e:
            logger.exception("文件下载失败")
            self._reply_stream(frame, stream_id, f"文件下载失败: {e}", finish=True)

    # ------------------------------------------------------------------
    # 核心查询流程
    # ------------------------------------------------------------------

    def _run_query(self, frame: dict, user_id: str, query: str, req_id: str) -> None:
        tid, split_reason, turn_count = _get_thread_id(user_id)

        stream_id = str(uuid.uuid4())
        cancel_evt = _register_task(user_id, stream_id)
        start_ts = time.monotonic()

        # 初始提示
        self._reply_stream(frame, stream_id, "InfoTest 正在运行，请稍候…")

        written_files: list[str] = []
        tool_names: list[str] = []
        tool_details: dict[str, str] = {}
        ask_user_triggered = False
        gen = _call_ist_core_stream(query, user_id, thread_id=tid, written_files=written_files)
        try:
            answer, stream_id, tool_names, tool_details, ask_user_triggered = self._drain_stream(
                gen, stream_id, cancel_evt, frame, user_id)
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
        renderer = ThoughtRenderer()
        process_summary = renderer.render_summary(tool_names, tool_details)
        final_md = _format_markdown(
            query[:100], answer, total_min,
            split_reason=split_reason, turn_count=turn_count,
            process_summary=process_summary,
        )
        _last_result[user_id] = {"query": query[:100], "answer": answer}

        # ask_user 触发且无答案时，不发空的最终消息（通知已单独发送）
        if ask_user_triggered and not answer.strip():
            logger.info("ask_user 已触发，跳过空结果消息")
            _deregister_task(user_id)
            return

        # 最终流式消息
        ok, stream_id = self._reply_stream(frame, stream_id, final_md, finish=True)
        if not ok:
            new_sid = str(uuid.uuid4())
            self._reply_stream(frame, new_sid, final_md, finish=True)
        _deregister_task(user_id)

        # 完成通知（红点）
        try:
            self._reply_markdown(frame, f"✅ **回答完成**（{total_min}分钟）")
        except Exception:
            logger.debug("完成通知发送失败", exc_info=True)

        # 文件发送
        logger.info("文件发送检查: written_files=%s wants_file=%s query=%.50s",
                     written_files, _wants_file(query), query)
        if written_files and _wants_file(query):
            self._send_written_files(frame, written_files, user_id, start_ts)

        # wx_send_file 工具排队的文件
        from main.ist_core.tools.wx_send_file import pop_pending_files
        pending = pop_pending_files()
        for pf in pending:
            fp = pf.get("path", "")
            note = pf.get("note", "")
            if fp and os.path.isfile(fp):
                try:
                    self._send_single_file(frame, fp, note=note)
                except Exception:
                    logger.exception("wx_send_file 发送失败: %s", fp)

    # ------------------------------------------------------------------
    # 流式消费（drain stream）
    # ------------------------------------------------------------------

    _STREAM_KEEPALIVE_S = 15

    def _drain_stream(
        self,
        gen: Generator,
        stream_id: str,
        cancel_evt: threading.Event,
        frame: dict,
        user_id: str = "",
    ) -> tuple[str, str, list[str]]:
        """消费 generator，经 ThoughtRenderer 渲染后推送企微流式消息。

        返回 (answer, stream_id, tool_names)。
        tool_names 用于最终消息的处理过程摘要。
        """
        answer = ""
        renderer = ThoughtRenderer()
        tool_names: list[str] = []
        tool_details: dict[str, str] = {}
        ask_user_triggered = False
        status_lines: list[str] = []   # 累积状态行

        def _send_status() -> None:
            """发送累积的状态内容到企微流式消息。"""
            nonlocal stream_id
            if status_lines:
                content = "\n".join(status_lines)
                ok, stream_id = self._reply_stream(frame, stream_id, content)
                if not ok:
                    new_sid = str(uuid.uuid4())
                    self._reply_stream(frame, new_sid, content)

        while True:
            try:
                event = gen.send(None)
            except StopIteration as exc:
                answer = exc.value or ""
                break
            except AttributeError:
                try:
                    event = next(gen)
                except StopIteration as exc:
                    answer = exc.value or ""
                    break

            if cancel_evt.is_set():
                gen.close()
                answer = "任务已被终止。"
                break

            # event 现在是 UserVisibleEvent
            if not isinstance(event, UserVisibleEvent):
                logger.debug("drain: 非 UserVisibleEvent: %r", type(event))
                continue

            etype = event.type

            # --- 保活 ---
            if etype == UserEventType.HEARTBEAT:
                if status_lines:
                    # 耗时追加到累积状态末尾
                    heartbeat_suffix = event.content  # "⏳ 仍在处理中（X 分钟）…"
                    combined = "\n".join(status_lines + [heartbeat_suffix])
                    _, stream_id = self._reply_stream(frame, stream_id, combined)
                else:
                    _, stream_id = self._reply_stream(frame, stream_id, event.content)

            # --- 等待用户输入 ---
            elif etype == UserEventType.ASK_USER:
                ask_user_triggered = True
                self._send_ask_user_notification(frame, event.metadata, user_id)

            # --- 工具状态（经 ThoughtRenderer 渲染） ---
            elif etype == UserEventType.TOOL_STATUS:
                tname = event.tool_name
                if tname:
                    tool_names.append(tname)
                inp = event.metadata.get("input")
                if isinstance(inp, dict):
                    input_data = inp
                elif isinstance(inp, str) and inp:
                    # streaming.py 把 input 转成了字符串，尝试还原
                    try:
                        import json as _json
                        input_data = _json.loads(inp)
                    except (ValueError, TypeError):
                        input_data = {"raw": inp}
                else:
                    input_data = {}
                # 收集 detail 用于最终摘要
                detail = renderer._extract_detail(tname, input_data)
                if detail and tname and tname not in tool_details:
                    tool_details[tname] = detail
                logger.info("drain TOOL_STATUS: name=%s phase=%s last=%s input_keys=%s",
                            tname, renderer.current_phase.value,
                            renderer._last_shown_tool,
                            list(input_data.keys())[:3] if input_data else [])
                rendered = renderer.process_event(
                    "tool_call" if not event.metadata.get("status") else "tool_result",
                    {"name": tname},
                    input_data=input_data,
                )
                if rendered is not None and rendered.content:
                    status_lines.append(rendered.content)
                    _send_status()

            # --- 思考阶段（经 ThoughtRenderer 渲染） ---
            elif etype == UserEventType.THINKING:
                rendered = renderer.process_event(
                    "llm_end", {"name": "thought", "content": ""})
                if rendered is not None and rendered.content:
                    status_lines.append(rendered.content)
                    _send_status()

            # --- 错误 ---
            elif etype == UserEventType.ERROR:
                answer = f"执行失败: {event.content}"
                break

        return answer, stream_id, tool_names, tool_details, ask_user_triggered

    def _send_ask_user_notification(self, frame: dict, payload: dict, user_id: str) -> None:
        """发送 ask_user 通知给用户。payload 为 ask_user_request 的原始 payload。"""
        questions = payload.get("questions") or []
        lines = [f"<@{user_id}> 🚨 【等待您的回答】", ""]
        for i, q_item in enumerate(questions, 1):
            question_text = q_item.get("question", "")
            lines.append(f"**Q{i}.** {question_text}")
            opts = q_item.get("options") or []
            for j, opt in enumerate(opts, 1):
                label = opt.get("label", "")
                desc = opt.get("description", "")
                lines.append(f"  {j}. **{label}**" + (f" — {desc}" if desc else ""))
            lines.append("")
        lines.append("请在下方输入框中回复（如选项编号或文字），以便任务继续执行。")
        try:
            self._reply_markdown(frame, "\n".join(lines))
        except Exception:
            logger.debug("ask_user 通知发送失败", exc_info=True)

    # ------------------------------------------------------------------
    # 文件发送
    # ------------------------------------------------------------------

    def _send_written_files(self, frame: dict, written_files: list[str],
                            user_id: str, agent_start_ts: float) -> None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        seen: set[str] = set()
        sent: list[str] = []
        for fp in written_files:
            abs_fp = fp if os.path.isabs(fp) else os.path.join(project_root, fp)
            norm = os.path.normpath(abs_fp)
            if norm in seen or not os.path.isfile(norm):
                continue
            try:
                if os.path.getmtime(norm) < agent_start_ts - 5:
                    continue
            except OSError:
                continue
            seen.add(norm)
            fname = os.path.basename(norm)
            size_kb = os.path.getsize(norm) / 1024
            try:
                self._send_single_file(frame, norm, note=f"📄 {fname} ({size_kb:.1f} KB)")
                sent.append(fname)
            except Exception:
                logger.exception("文件发送失败: %s", fname)
        if sent:
            logger.info("已发送 %d 个文件给用户 %s: %s", len(sent), user_id, sent)

    def _send_single_file(self, frame: dict, local_path: str, note: str = "") -> None:
        """上传文件并发送给用户（复用 gateway 的 SDK 连接）。"""
        from .files import validate_file
        stream_id = str(uuid.uuid4())
        if not os.path.isfile(local_path):
            self._reply_stream(frame, stream_id, f"文件不存在: {local_path}", finish=True)
            return
        err = validate_file(local_path)
        if err:
            self._reply_stream(frame, stream_id, err, finish=True)
            return
        self._reply_stream(frame, stream_id,
                           f"正在上传: {os.path.basename(local_path)}...")
        try:
            media_id = self._sdk_upload(local_path)
            if media_id:
                self._run_coro(
                    self._client.reply_media(frame, "file", media_id)
                )
                fname = os.path.basename(local_path)
                fsize_kb = os.path.getsize(local_path) / 1024
                self._reply_stream(frame, stream_id,
                                   f"{note}\n{fname} ({fsize_kb:.1f} KB)", finish=True)
            else:
                self._reply_stream(frame, stream_id, "文件上传失败", finish=True)
        except Exception as e:
            logger.exception("文件上传失败")
            self._reply_stream(frame, stream_id, f"文件上传失败: {e}", finish=True)

    def _sdk_upload(self, file_path: str) -> str | None:
        """通过 gateway 的 SDK 连接上传文件。"""
        from pathlib import Path
        fname = os.path.basename(file_path)
        file_data = Path(file_path).read_bytes()
        logger.info("SDK 上传: %s (%d bytes)", fname, len(file_data))

        async def _do():
            result = await self._client.upload_media(
                file_data, type="file", filename=fname,
            )
            return result.get("media_id", "") if isinstance(result, dict) else ""

        media_id = self._run_coro(_do())
        if media_id:
            logger.info("SDK 上传成功: media_id=%s", media_id)
        return media_id or None

    # ------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------

    def _try_create_report(self, frame: dict, query: str,
                           user_id: str, req_id: str) -> None:
        stream_id = str(uuid.uuid4())
        last = _last_result.get(user_id)
        if last:
            query = last["query"]
            answer = last["answer"]
        else:
            answer = ""
        if not answer:
            self._reply_stream(frame, stream_id,
                               "还没有可用的分析结果。请先发送一个技术问题。", finish=True)
            return
        if not server_config.mcp_doc_url:
            self._reply_stream(frame, stream_id,
                               "报告功能未配置。请在企微后台授权后设置 WECOM_SMART_MCP_DOC_URL。",
                               finish=True)
            return
        self._reply_stream(frame, stream_id, "正在生成报告文档…")
        try:
            from .tools import build_report_markdown
            tk = _get_doc_toolkit()
            if tk is None:
                self._reply_stream(frame, stream_id,
                                   "MCP 客户端初始化失败", finish=True)
                return
            report_md = build_report_markdown(query, answer)
            doc_url = tk.create_doc_with_content(
                f"InfoTest 报告 - {query[:50]}", report_md,
            )
            if doc_url:
                self._reply_stream(frame, stream_id,
                                   f"报告已生成\n\n[点击查看报告]({doc_url})", finish=True)
            else:
                self._reply_stream(frame, stream_id, "文档创建失败", finish=True)
        except Exception as e:
            logger.exception("报告生成失败")
            self._reply_stream(frame, stream_id, f"报告生成失败: {e}", finish=True)
