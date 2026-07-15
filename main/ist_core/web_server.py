"""IST-Core Web Terminal server.

xterm.js 前端 + WebSocket PTY 后端：
- / GET：xterm.js 终端页面（含登录 + 文件上传/下载按钮）
- /api/login POST：验证用户（PG-backed SessionManager）
- /api/upload POST：文件上传到沙箱
- /api/files GET：列出 workspace/outputs/ 下可下载文件
- /api/download GET：下载 workspace/outputs/ 中的文件
- /ws/terminal WebSocket：PTY 桥接（spawn TUI 子进程）
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import sys
import termios
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from main.ist_core.events import get_default_bus

logger = logging.getLogger("ist_web")



_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SANDBOX = _PROJECT_ROOT / "workspace" / "inputs"
_WEB_DIR = Path(__file__).resolve().parent / "web"
_ALLOWED = {
    ".conf", ".cfg", ".ini", ".yaml", ".yml", ".xml", ".log",
    ".md", ".txt", ".json", ".csv", ".pdf", ".doc", ".docx",
    ".xlsx", ".xls", ".ppt", ".pptx", ".html", ".htm",
}

app = FastAPI(title="IST-Core Web Terminal")

# SessionManager 单例（延迟初始化）
_session_mgr = None


def _get_session_mgr():
    global _session_mgr
    if _session_mgr is None:
        from main.ist_core.auth.session_manager import SessionManager
        _session_mgr = SessionManager()
    return _session_mgr


def _validate_request(session_id: str, jwt_token: str) -> dict | None:
    """校验请求：返回 {"username", "role", "session_id"} 或 None。"""
    if not session_id or not jwt_token:
        return None
    return _get_session_mgr().validate_session(session_id, jwt_token)


def get_auth_token(username: str, session_id: str) -> str | None:
    """根据 username 和 session_id 获取 jwt_token。

    用于评分系统等内部组件调用 API 时获取认证 token。
    """
    from main.ist_core.auth.db import pg_cursor
    from datetime import datetime, timezone
    
    try:
        with pg_cursor() as cur:
            # 先通过 username 获取 user_id (UUID)
            cur.execute(
                """SELECT id FROM ist_audit.users WHERE username = %s""",
                (username,),
            )
            user_row = cur.fetchone()
            if not user_row:
                return None
            user_id = user_row["id"]
            
            # 再通过 user_id 和 session_id 获取 jwt_token
            cur.execute(
                """SELECT jwt_token, expires_at, is_valid
                   FROM ist_audit.sessions
                   WHERE user_id = %s AND session_id = %s AND is_valid = TRUE""",
                (user_id, session_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            # 检查是否过期
            if row["expires_at"] < datetime.now(timezone.utc):
                return None
            return row.get("jwt_token", "")
    except Exception as exc:
        logger.debug("get_auth_token 失败: %s", exc)
        return None


# 登录失败限流（按客户端 IP，滑动窗口）
_login_attempts: dict[str, list[float]] = {}
_LOGIN_MAX_FAILURES = int(os.environ.get("IST_WEB_LOGIN_MAX_FAILURES", "5"))
_LOGIN_WINDOW_SEC = int(os.environ.get("IST_WEB_LOGIN_WINDOW_SEC", "300"))

# 上传体积上限
_MAX_UPLOAD_BYTES = int(os.environ.get("IST_WEB_MAX_UPLOAD_MB", "50")) * 1024 * 1024

# RBAC：仅这些角色可写（上传）。reviewer 只读。
_WRITE_ROLES = {r.strip() for r in os.environ.get("IST_WEB_WRITE_ROLES", "admin,superadmin").split(",") if r.strip()}


def _client_ip(request: Request | None) -> str:
    if request is None or request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _rate_limited(ip: str) -> bool:
    """滑动窗口：窗口内失败次数达上限即拒。"""
    now = time.monotonic()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_WINDOW_SEC]
    _login_attempts[ip] = attempts
    return len(attempts) >= _LOGIN_MAX_FAILURES


def _record_failure(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(time.monotonic())


def _ensure_env() -> None:
    """加载项目根目录 environment 文件。"""
    try:
        from dotenv import load_dotenv
        env_path = _PROJECT_ROOT / "environment"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except Exception:  # noqa: BLE001
        pass


@app.post("/api/login")
async def login(body: dict, request: Request):
    ip = _client_ip(request)
    if _rate_limited(ip):
        logger.warning("login rate-limited for ip=%s", ip)
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
    username = body.get("username", "")
    password = body.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    # 从 PG 查找用户
    from main.ist_core.auth.db import pg_cursor
    from main.ist_core.auth.password import verify_password
    try:
        with pg_cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, role, account_status "
                "FROM ist_audit.users WHERE username = %s",
                (username,),
            )
            user = cur.fetchone()
    except Exception as exc:
        logger.error("login DB 查询失败: %s", exc)
        raise HTTPException(status_code=500, detail="服务暂时不可用")

    if not user:
        _record_failure(ip)
        logger.info("login failed user=%r (not found) ip=%s", username, ip)
        get_default_bus().emit(
            "auth_login_failed",
            payload={"username": username, "reason": "user_not_found"},
            tags={"source_ip": ip},
        )
        raise HTTPException(status_code=401, detail="用户名不存在")

    if user.get("account_status") != "normal":
        _record_failure(ip)
        logger.info("login failed user=%r (account locked/disabled) ip=%s", username, ip)
        get_default_bus().emit(
            "auth_login_failed",
            payload={"username": username, "reason": "account_locked", "account_status": user.get("account_status")},
            tags={"source_ip": ip},
        )
        raise HTTPException(status_code=403, detail="账号已被锁定或禁用")

    if not verify_password(user["password_hash"], password):
        _record_failure(ip)
        logger.info("login failed user=%r (wrong password) ip=%s", username, ip)
        get_default_bus().emit(
            "auth_login_failed",
            payload={"username": username, "reason": "wrong_password"},
            tags={"source_ip": ip},
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 创建会话（PG + Redis）
    role = user.get("role", "reviewer")
    try:
        session_id, jwt_token = _get_session_mgr().create_session(username, role, channel="web")
    except Exception as exc:
        logger.error("login create_session 失败: %s", exc)
        raise HTTPException(status_code=500, detail="会话创建失败")

    # 创建默认对话（关联到 auth session）
    conv = None
    try:
        conv = _get_session_mgr().create_conversation(username, session_id=session_id)
    except Exception as exc:
        logger.debug("login create_conversation 失败: %s", exc)

    logger.info("login ok user=%r role=%s session=%s ip=%s", username, role, session_id, ip)
    get_default_bus().emit(
        "auth_login",
        payload={"username": username, "role": role},
        tags={"session_id": session_id, "source_ip": ip, "session_user": username},
    )
    result = {"token": jwt_token, "session_id": session_id, "username": username, "role": role}
    if conv:
        result["conversation_id"] = conv["conversation_id"]
    return result


@app.post("/api/logout")
async def logout(body: dict):
    session_id = body.get("session_id", "")
    username = body.get("username", "")
    if session_id:
        try:
            _get_session_mgr().invalidate_session(session_id)
            get_default_bus().emit(
                "auth_logout",
                payload={"username": username},
                tags={"session_id": session_id, "session_user": username},
            )
        except Exception as exc:
            logger.debug("logout invalidate 失败: %s", exc)
    return {"ok": True}


@app.post("/api/chat/rating/submit")
async def submit_rating(body: dict, session_id: str = "", token: str = ""):
    """提交对话评分。

    业务逻辑：
    - 校验 score 在 0~5 区间
    - UPSERT 写入 sys_chat_rating：存在则更新，不存在插入
    - 异步更新 sys_dialog_chat.rating 冗余字段
    - 写入审计日志 audit_log，event_kind=chat_rating_submit
    """
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(status_code=401, detail="未登录")

    username = sess.get("username", "")
    if not username:
        raise HTTPException(400, "无法获取用户名")

    conversation_id = body.get("conversation_id", "")
    run_id = body.get("run_id", "")
    score = body.get("score")
    comment = body.get("comment", "")

    if not conversation_id or not run_id:
        raise HTTPException(400, "conversation_id 和 run_id 不能为空")

    if score is None or not isinstance(score, int) or score < 0 or score > 5:
        raise HTTPException(400, "score 必须在 0~5 之间")

    from main.ist_core.auth.db import pg_cursor

    try:
        with pg_cursor() as cur:
            cur.execute(
                """SELECT thread_id FROM ist_audit.sys_dialog_chat
                   WHERE username = %s AND conversation_id = %s AND run_id = %s""",
                (username, conversation_id, run_id),
            )
            row = cur.fetchone()
            thread_id = row.get("thread_id", "") if row else ""

            cur.execute(
                """INSERT INTO ist_audit.sys_chat_rating
                   (username, session_id, conversation_id, run_id, thread_id, score, comment)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (username, conversation_id, run_id)
                   DO UPDATE SET score = EXCLUDED.score, comment = EXCLUDED.comment, created_at = now()
                   RETURNING id""",
                (username, session_id, conversation_id, run_id, thread_id, score, comment),
            )

            cur.execute(
                """UPDATE ist_audit.sys_dialog_chat
                   SET rating = %s
                   WHERE username = %s AND conversation_id = %s AND run_id = %s""",
                (score, username, conversation_id, run_id),
            )

            get_default_bus().emit(
                "chat_rating_submit",
                payload={
                    "username": username,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "score": score,
                    "comment": comment,
                },
                tags={
                    "session_id": session_id,
                    "session_user": username,
                },
            )

        return {"ok": True, "score": score}
    except Exception as exc:
        logger.error("submit_rating 失败: %s", exc)
        raise HTTPException(500, "评分提交失败")


@app.get("/api/chat/rating/get")
async def get_rating(session_id: str = "", token: str = "", conversation_id: str = "", run_id: str = ""):
    """查询单轮对话评分。

    返回：分数 + 评价内容，无记录返回空。
    """
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(status_code=401, detail="未登录")

    username = sess.get("username", "")
    if not username:
        raise HTTPException(400, "无法获取用户名")

    if not conversation_id or not run_id:
        raise HTTPException(400, "conversation_id 和 run_id 不能为空")

    from main.ist_core.auth.db import pg_cursor

    try:
        with pg_cursor() as cur:
            cur.execute(
                """SELECT score, comment, created_at
                   FROM ist_audit.sys_chat_rating
                   WHERE username = %s AND conversation_id = %s AND run_id = %s""",
                (username, conversation_id, run_id),
            )
            row = cur.fetchone()

        if not row:
            return {"score": None, "comment": None, "created_at": None}

        return {
            "score": row.get("score"),
            "comment": row.get("comment"),
            "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
        }
    except Exception as exc:
        logger.error("get_rating 失败: %s", exc)
        raise HTTPException(500, "评分查询失败")


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(status_code=401, detail="未登录")
    if sess.get("role") not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="无上传权限")

    # 获取 username，创建用户专属目录
    username = sess.get("username", "")
    if not username:
        raise HTTPException(400, "无法获取用户名")
    user_sandbox = _SANDBOX / username
    user_sandbox.mkdir(parents=True, exist_ok=True)

    # 仅取 basename，剥离任何目录分量 → 防 ../../ 路径遍历
    raw_name = file.filename or "upload"
    safe_name = os.path.basename(raw_name.replace("\\", "/"))
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(400, "非法文件名")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, "不支持的文件类型")

    dest = (user_sandbox / safe_name).resolve()
    # 双保险：解析后必须仍在用户目录内
    if not str(dest).startswith(str(user_sandbox.resolve()) + os.sep):
        raise HTTPException(400, "非法文件名")

    # 流式写入并强制体积上限，超限即删除半成品
    written = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > _MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "文件过大")
            f.write(chunk)

    rel = dest.relative_to(_PROJECT_ROOT).as_posix()
    return {"path": rel, "filename": safe_name}


_OUTPUTS = _PROJECT_ROOT / "workspace" / "outputs"


def _get_user_outputs_dir(session_id: str, token: str) -> Path:
    """获取用户专属 outputs 目录，校验登录状态。"""
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    username = sess.get("username", "")
    if not username:
        raise HTTPException(400, "无法获取用户名")
    user_dir = _OUTPUTS / username
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


@app.get("/api/files")
async def list_files(session_id: str = "", token: str = ""):
    user_dir = _get_user_outputs_dir(session_id, token)
    files = []
    for f in sorted(user_dir.rglob("*")):
        if f.is_file() and not f.name.startswith("."):
            rel = f.relative_to(user_dir)
            files.append({"name": str(rel).replace("\\", "/"), "size": f.stat().st_size})
    return {"files": files}


@app.get("/api/download")
async def download_file(session_id: str = "", token: str = "", name: str = ""):
    user_dir = _get_user_outputs_dir(session_id, token)
    if not name or ".." in name:
        raise HTTPException(400, "非法文件名")
    # 统一用 / 分隔，拒绝 Windows 反斜杠绕过
    name = name.replace("\\", "/")
    target = (user_dir / name).resolve()
    # 双保险：解析后必须仍在用户目录内
    if not str(target).startswith(str(user_dir.resolve()) + os.sep) and target != user_dir.resolve():
        raise HTTPException(403, "路径越权")
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, filename=target.name)


def _set_winsize(fd: int, cols: int, rows: int):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


# ------------------------------------------------------------------
# 对话管理 API
# ------------------------------------------------------------------

@app.get("/api/conversations")
async def list_conversations(session_id: str = "", token: str = "", limit: int = 20, offset: int = 0):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    limit = max(1, min(limit, 100))
    items = _get_session_mgr().list_conversations(sess["username"], limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    conv = _get_session_mgr().get_conversation(sess["username"], conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")
    return conv


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    ok = _get_session_mgr().delete_conversation(sess["username"], conversation_id)
    if not ok:
        raise HTTPException(404, "对话不存在")
    return {"ok": True}


@app.put("/api/conversations/{conversation_id}/activate")
async def activate_conversation(conversation_id: str, session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    result = _get_session_mgr().activate_conversation(sess["username"], conversation_id)
    if not result:
        raise HTTPException(404, "对话不存在")
    return result


@app.put("/api/conversations/{conversation_id}/title")
async def rename_conversation(conversation_id: str, body: dict, session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    title = (body.get("title") or "").strip()[:200]
    if not title:
        raise HTTPException(400, "标题不能为空")
    ok = _get_session_mgr().rename_conversation(sess["username"], conversation_id, title)
    if not ok:
        raise HTTPException(404, "对话不存在")
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/context")
async def get_conversation_context(conversation_id: str, session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    username = sess["username"]
    conv = _get_session_mgr().get_conversation(username, conversation_id)
    if not conv:
        raise HTTPException(404, "对话不存在")

    thread_id = _get_session_mgr().build_thread_id(username, conversation_id) or f"{username}_{conversation_id}"
    working_memory = ""
    try:
        from main.ist_core.memory.store import MemoryStore
        from main.ist_core.memory.backend import get_default_root
        ms = MemoryStore(backend=None, root_disk=get_default_root())
        working_memory = ms.read_working(thread_id, max_lines=200)
    except Exception:
        pass

    checkpoint_summary = None
    try:
        from main.ist_core.graph import _make_checkpointer
        cp = _make_checkpointer()
        if cp:
            config = {"configurable": {"thread_id": thread_id}}
            state = cp.get(config)
            if state:
                values = state.get("values", {}) if isinstance(state, dict) else {}
                msgs = values.get("messages", []) if isinstance(values, dict) else []
                if msgs:
                    checkpoint_summary = {
                        "message_count": len(msgs),
                        "last_message": str(msgs[-1].content)[:200] if hasattr(msgs[-1], "content") else str(msgs[-1])[:200],
                    }
    except Exception:
        pass

    return {
        "conversation": conv,
        "checkpoint_summary": checkpoint_summary,
        "working_memory": working_memory,
    }


@app.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    """WebSocket PTY 桥接：spawn TUI 子进程，双向转发。"""
    await websocket.accept()

    auth = await websocket.receive_json()
    token = auth.get("token", "")
    session_id = auth.get("session_id", "")
    sess = _validate_request(session_id, token)
    if not sess:
        await websocket.send_json({"type": "error", "msg": "未登录或会话已过期"})
        await websocket.close()
        return
    username = sess["username"]
    conversation_id = auth.get("conversation_id", session_id)

    if not _get_session_mgr().is_conversation_active(username, conversation_id):
        await websocket.send_json({"type": "error", "msg": "该对话已关闭，无法发起新推理"})
        await websocket.close()
        return

    cols = auth.get("cols", 120)
    rows = auth.get("rows", 40)


    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, cols, rows)

    import tty as _tty
    _tty.setraw(slave_fd)
    _tty.setraw(master_fd)

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = str(cols)
    env["LINES"] = str(rows)
    env["LANG"] = env.get("LANG", "en_US.UTF-8")
    env["PYTHONIOENCODING"] = "utf-8"
    env["IST_SSH_USER"] = username
    env["IST_AUTH_SESSION_ID"] = session_id         # auth session_id，审计日志用
    env["IST_CONVERSATION_ID"] = conversation_id    # thread_id = {username}_{conversation_id}，审计日志用

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", "-m", "main.ist_core.tui.cli",
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        env=env, cwd=str(_PROJECT_ROOT), start_new_session=True,
    )
    os.close(slave_fd)

    loop = asyncio.get_event_loop()

    
    async def pty_to_ws():
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            await websocket.send_bytes(data)

    
    async def ws_to_pty():
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.receive":
                    if "bytes" in msg and msg["bytes"]:
                        os.write(master_fd, msg["bytes"])
                    elif "text" in msg and msg["text"]:
                        
                        try:
                            d = json.loads(msg["text"])
                            if d.get("type") == "resize":
                                _set_winsize(master_fd, d.get("cols", cols), d.get("rows", rows))
                                if proc.pid:
                                    os.kill(proc.pid, signal.SIGWINCH)
                            elif d.get("type") == "input":
                                os.write(master_fd, d["data"].encode("utf-8"))
                            elif d.get("type") == "upload":
                                # 带外上传信号：文件名 base64 后包成自定义 OSC 序列
                                # ESC ] 7001 ; <base64> BEL，由 TUI 的 ink 解析器
                                # 识别为 UploadEvent。不混进键盘输入文本流，杜绝下游
                                # 用正则在自由文本里猜文件名。
                                fname = (d.get("filename") or "").strip()
                                if fname:
                                    b64 = base64.b64encode(
                                        fname.encode("utf-8")
                                    ).decode("ascii")
                                    osc = f"\x1b]7001;{b64}\x07"
                                    os.write(master_fd, osc.encode("ascii"))
                            elif d.get("type") == "switch_conversation":
                                new_conv_id = d.get("conversation_id", "")
                                if new_conv_id:
                                    result = _get_session_mgr().activate_conversation(username, new_conv_id)
                                    if result:
                                        # 通过 OSC 7003 序列通知 TUI 切换上下文
                                        b64 = base64.b64encode(new_conv_id.encode("utf-8")).decode("ascii")
                                        osc = f"\x1b]7003;{b64}\x07"
                                        os.write(master_fd, osc.encode("ascii"))
                                        await websocket.send_json({
                                            "type": "switched",
                                            "conversation_id": new_conv_id,
                                            "thread_id": result.get("thread_id", ""),
                                            "title": d.get("title", ""),
                                        })
                                    else:
                                        await websocket.send_json({
                                            "type": "error",
                                            "msg": "对话不存在",
                                        })
                                continue
                        except (json.JSONDecodeError, KeyError):
                            os.write(master_fd, msg["text"].encode("utf-8"))
                elif msg["type"] == "websocket.disconnect":
                    break
        except WebSocketDisconnect:
            pass

    pty_task = asyncio.create_task(pty_to_ws())
    ws_task = asyncio.create_task(ws_to_pty())

    try:
        await proc.wait()
    finally:
        pty_task.cancel()
        ws_task.cancel()
        # 等被取消的任务真正收尾，避免后台残留 / fd 竞争
        await asyncio.gather(pty_task, ws_task, return_exceptions=True)
        # 显式终止子进程，防止卡死的 TUI 变僵尸 + 泄漏 master_fd
        if proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await asyncio.gather(proc.wait(), return_exceptions=True)
            except ProcessLookupError:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass


@app.get("/")
async def index():
    return FileResponse(_WEB_DIR / "index.html")


def serve(host: str = "127.0.0.1", port: int = 8080):
    import uvicorn
    import os
    # 将实际端口写入环境变量，供其他组件（如评分系统）读取
    os.environ["IST_WEB_HOST"] = host
    os.environ["IST_WEB_PORT"] = str(port)
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    _ensure_env()
    try:
        from main.ist_core.auth.db import ensure_schema
        ensure_schema()
    except Exception as exc:
        logger.warning("auth schema init failed: %s", exc)
    # 订阅 PgAuditSink 到默认 bus（捕获登录/登出等非 agent-run 事件）
    try:
        from main.ist_core.events import get_default_bus
        from main.ist_core.sinks.pg_sink import PgAuditSink
        get_default_bus().subscribe(PgAuditSink())
    except Exception as exc:
        logger.debug("PgAuditSink 注册到默认 bus 失败: %s", exc)
    logger.info("IST-Core Web Terminal on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    _ensure_env()
    serve(args.host, args.port)
