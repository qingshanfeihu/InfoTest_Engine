"""任务处理逻辑：解析企微消息 → 调用 IST-Core → 推送结果。"""

from __future__ import annotations

import logging
import os
import ctypes
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from typing import Any, Callable

from .config import server_config
from .wecom_api import get_api_client

logger = logging.getLogger("wecom_bot.task")


# ============================================================================
# 消息解析
# ============================================================================

def parse_message_xml(xml_string: str) -> dict[str, str]:
    root = ET.fromstring(xml_string)
    fields: dict[str, str] = {}
    for child in root:
        fields[child.tag] = (child.text or "")
    return fields


def build_text_reply_xml(touser: str, fromuser: str, content: str) -> str:
    timestamp = str(int(time.time()))
    return (
        "<xml>\n"
        f"<ToUserName><![CDATA[{touser}]]></ToUserName>\n"
        f"<FromUserName><![CDATA[{fromuser}]]></FromUserName>\n"
        f"<CreateTime>{timestamp}</CreateTime>\n"
        "<MsgType><![CDATA[text]]></MsgType>\n"
        f"<Content><![CDATA[{content}]]></Content>\n"
        "</xml>"
    )


# ============================================================================
# 会话管理（多轮对话支持）
# ============================================================================

_sessions: dict[str, str] = {}
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CHECKPOINT_DB = os.path.join(_PROJECT_ROOT, "runtime", "wecom_checkpoints.db")
os.makedirs(os.path.dirname(_CHECKPOINT_DB), exist_ok=True)


def _get_thread_id(user_id: str) -> str:
    if user_id in _sessions:
        return _sessions[user_id]
    return _new_session(user_id)


def _new_session(user_id: str) -> str:
    import uuid
    tid = f"wecom-{user_id}-{uuid.uuid4().hex[:8]}"
    _sessions[user_id] = tid
    logger.info("新会话: user=%s thread=%s", user_id, tid)
    return tid


# ============================================================================
# 任务追踪 & 取消（/stop）
# ============================================================================

_active_tasks: dict[str, dict[str, Any]] = {}
_active_lock = threading.Lock()


def _kill_thread(t: threading.Thread) -> bool:
    tid = t.ident
    if tid is None:
        return False
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
        ctypes.c_long(tid), ctypes.py_object(SystemExit)
    )
    if res == 0:
        logger.warning("线程 %s 已不存在", tid)
        return False
    if res > 1:
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)
        logger.warning("线程 %s 注入了多个异常，已回滚", tid)
        return False
    logger.info("线程 %s 已终止", tid)
    return True


def _cancel_active_task(user_id: str) -> bool:
    with _active_lock:
        task = _active_tasks.pop(user_id, None)
    if task is None:
        return False
    cancel_evt: threading.Event = task["cancel"]
    cancel_evt.set()
    t: threading.Thread = task["thread"]
    logger.info("取消任务: user=%s thread_id=%s", user_id, t.ident)
    return _kill_thread(t)


# ============================================================================
# IST-Core 调用
# ============================================================================

def _call_ist_core(user_query: str, user_id: str = "", thread_id: str = "") -> dict[str, Any]:
    from main.ist_core.runner import _ensure_env
    _ensure_env()

    os.environ.setdefault("IST_NON_INTERACTIVE", "1")
    os.environ.setdefault("IST_LLM_STREAMING", "0")

    from main.ist_core.graph import build_ist_core_graph
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langchain_core.messages import HumanMessage
    import uuid

    tid = thread_id or f"wecom-{user_id or 'anon'}-{uuid.uuid4().hex[:8]}"

    logger.info("IST-Core 调用开始: thread=%s query=%.100s", tid, user_query)
    t0 = time.monotonic()
    try:
        with SqliteSaver.from_conn_string(_CHECKPOINT_DB) as saver:
            graph = build_ist_core_graph(checkpointer=saver, checkpointer_mode="sync")
            config: dict[str, Any] = {"configurable": {"thread_id": tid}}
            initial_state: dict[str, Any] = {
                "task_type": "QA",
                "user_input": user_query,
                "messages": [HumanMessage(content=user_query)],
            }
            result = graph.invoke(initial_state, config)
        elapsed = time.monotonic() - t0
        logger.info("IST-Core 调用完成: thread=%s elapsed=%.1fs", tid, elapsed)
    except Exception:
        elapsed = time.monotonic() - t0
        logger.exception("IST-Core 调用失败: thread=%s elapsed=%.1fs", tid, elapsed)
        raise

    return result


# ============================================================================
# 公开入口
# ============================================================================

def handle_message(msg: dict[str, str]) -> tuple[str, Callable[[], None] | None]:
    msg_type = msg.get("MsgType", "")
    content = (msg.get("Content") or "").strip()
    from_user = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")

    logger.info("收到消息: MsgType=%s FromUser=%s Content=%.100s", msg_type, from_user, content)

    if msg_type != "text":
        return build_text_reply_xml(to_user, from_user, "暂不支持此消息类型"), None

    if not content:
        return build_text_reply_xml(to_user, from_user, "请输入指令。\n支持：直接提问 / 帮助 / 状态"), None

    # ---- 帮助 ----
    if content in ("帮助", "help", "/help"):
        return build_text_reply_xml(to_user, from_user,
            "InfoTest Engine 机器人\n"
            "直接发送技术问题即可，AI 会自动分析并回复。\n\n"
            "【对话控制】\n"
            "  新对话 / 新会话 / 重置\n"
            "    -> 清空上下文，开启全新会话\n"
            "  停止\n"
            "    -> 终止当前正在执行的后台任务\n"
            "  会话\n"
            "    -> 查看当前会话 ID\n\n"
            "【查询】\n"
            "  状态 -> 查看服务运行状态\n"
            "  帮助 -> 显示本帮助\n\n"
            "提示：\n"
            "- 复杂任务会先回复「已收到」，完成后主动推送结果\n"
            "- 多轮对话自动续接上下文，发送「新对话」可重置\n"
            "- 长时间无响应可发送「停止」终止任务后重试"), None

    # ---- 状态 ----
    if content in ("状态", "status", "/status"):
        return build_text_reply_xml(to_user, from_user,
            f"🟢 InfoTest Engine 在线\nModel: {os.environ.get('IST_MODEL', 'default')}"), None

    # ---- 新对话 ----
    if content in ("新对话", "新会话", "重置", "/new", "/reset"):
        _cancel_active_task(from_user)
        tid = _new_session(from_user)
        return build_text_reply_xml(to_user, from_user, f"✅ 已开启新对话\nThread: {tid[-12:]}"), None

    # ---- 停止 ----
    if content in ("停止", "/stop", "/cancel"):
        if _cancel_active_task(from_user):
            return build_text_reply_xml(to_user, from_user, "⏹ 已终止当前任务。发送新消息即可开始新任务。"), None
        else:
            return build_text_reply_xml(to_user, from_user, "ℹ️ 当前没有正在执行的任务。"), None

    # ---- 会话查询 ----
    if content in ("会话", "/session"):
        tid = _get_thread_id(from_user)
        return build_text_reply_xml(to_user, from_user, f"📋 当前会话: {tid[-12:]}\n发送「新对话」可重置"), None

    # ---- 其他 → 异步 ----
    tid = _get_thread_id(from_user)
    ack = f"⏳ 已收到，正在处理…\n> {content[:100]}"
    if from_user in _sessions and _sessions[from_user] == tid:
        ack += f"\n\n💬 会话续接中 ({tid[-12:]})"
    bg_task = _make_bg_task(content, from_user, tid)
    return build_text_reply_xml(to_user, from_user, ack), bg_task


# ============================================================================
# 后台任务构造
# ============================================================================

def _make_bg_task(query: str, user_id: str, thread_id: str = "") -> Callable[[], None]:
    def _run_and_push() -> None:
        logger.info("后台任务开始: user=%s thread=%s query=%.100s", user_id, thread_id, query)
        api = get_api_client()
        cancel_evt = threading.Event()

        current_thread = threading.current_thread()
        with _active_lock:
            _active_tasks[user_id] = {"thread": current_thread, "cancel": cancel_evt}

        try:
            # 初始状态
            _push_progress(api, user_id, "thinking")

            # 心跳线程
            heartbeat_running = True
            start_ts = time.monotonic()

            def _heartbeat_loop() -> None:
                interval = 300
                messages = [
                    "⏳ 仍在处理中，请耐心等待…（{elapsed} 分钟）",
                    "🔍 AI 正在检索和分析，已等待 {elapsed} 分钟…",
                    "📝 正在整理结果，已过 {elapsed} 分钟…",
                    "⚙️ 任务执行中，已等待 {elapsed} 分钟…",
                ]
                idx = 0
                while heartbeat_running and not cancel_evt.is_set():
                    time.sleep(interval)
                    if not heartbeat_running or cancel_evt.is_set():
                        break
                    elapsed_min = int((time.monotonic() - start_ts) / 60) or 1
                    msg = messages[idx % len(messages)].format(elapsed=elapsed_min)
                    idx += 1
                    try:
                        api.send_text(msg, touser=user_id)
                    except Exception:
                        logger.warning("心跳推送失败: user=%s", user_id)

            hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
            hb_thread.start()

            # IST-Core
            try:
                result = _call_ist_core(query, user_id, thread_id=thread_id)
                final_answer = result.get("final_answer") or "（无回答）"
            except SystemExit:
                final_answer = "⏹ 任务已被用户终止。"
                logger.info("任务被用户取消: user=%s", user_id)
            except Exception:
                final_answer = f"❌ 任务执行异常:\n{traceback.format_exc()[-800:]}"
                logger.exception("后台 IST-Core 异常: user=%s", user_id)
            finally:
                heartbeat_running = False
                with _active_lock:
                    _active_tasks.pop(user_id, None)

            if cancel_evt.is_set() and "任务已被用户终止" not in final_answer:
                final_answer = "⏹ 任务已被用户终止。"

            total_min = int((time.monotonic() - start_ts) / 60) or 0
            md = _format_as_wecom_markdown(query, final_answer, elapsed_min=total_min)
            _push_final(api, user_id, md, final_answer)
        finally:
            with _active_lock:
                _active_tasks.pop(user_id, None)

    return _run_and_push


def _push_progress(api, user_id: str, stage: str) -> None:
    tips = {"thinking": "🤔 AI 正在分析你的问题，预计需要 30-120 秒，请耐心等待…"}
    msg = tips.get(stage, "⏳ 处理中…")
    try:
        api.send_text(msg, touser=user_id)
    except Exception:
        logger.warning("进度推送失败: user=%s", user_id)


def _push_final(api, user_id: str, md: str, fallback_text: str) -> None:
    try:
        api.send_markdown(md, touser=user_id)
        logger.info("后台任务完成并推送: user=%s", user_id)
    except Exception:
        logger.exception("Markdown 推送失败，降级为文本: user=%s", user_id)
        try:
            short = _truncate(fallback_text, max_bytes=1500)
            api.send_text(f"📋 处理结果:\n\n{short}", touser=user_id)
        except Exception:
            logger.exception("文本降级推送也失败: user=%s", user_id)


# ============================================================================
# Markdown 格式化
# ============================================================================

def _format_as_wecom_markdown(query: str, answer: str, elapsed_min: int = 0) -> str:
    body = _truncate(answer, max_bytes=1700)
    if elapsed_min > 0:
        footer = f"<font color=\"comment\">总耗时约 {elapsed_min} 分钟 · {_now_str()}</font>"
    else:
        footer = f"<font color=\"comment\">Powered by IST-Core · {_now_str()}</font>"
    return (
        f"## 📋 InfoTest Engine 结果\n"
        f"> **问题：**{query[:100]}\n"
        f"---\n"
        f"{body}\n"
        f"---\n"
        f"{footer}"
    )


def _truncate(text: str, max_bytes: int) -> str:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    return data[:max_bytes].decode("utf-8", errors="ignore") + "\n\n> ⚠️ 输出过长已截断"


def _now_str() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
