"""IST-Core Web Terminal server.

xterm.js frontend + WebSocket PTY backend:
- / GET: xterm.js terminal page (login + file upload/download)
- /api/login POST: PG-backed SessionManager auth
- /api/upload POST: file upload to remote server
- /api/files GET: list remote output files
- /api/download GET: download from remote server
- /ws/terminal WebSocket: PTY bridge (spawn TUI subprocess)
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import ipaddress
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

from . import remote_fs

logger = logging.getLogger("ist_web")


def _emit_langfuse_auth_trace(
    name: str,
    *,
    user_id: str = "",
    session_id: str = "",
    input_data: dict | None = None,
    output_data: dict | None = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> None:
    """Write an auth event trace to Langfuse (silent failure)."""
    try:
        from main.ist_core.sinks.langfuse_sink import get_langfuse_client
        client = get_langfuse_client()
        if client is None:
            return
        from langfuse import propagate_attributes
        with propagate_attributes(
            user_id=user_id or None,
            session_id=session_id or None,
            metadata=metadata or None,
            tags=tags or None,
        ):
            span = client.start_span(
                name=name,
                input=input_data,
                output=output_data,
            )
            span.end()
    except Exception:
        pass


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE = _PROJECT_ROOT / "workspace"
_WEB_DIR = Path(__file__).resolve().parent / "web"
_ALLOWED = {
    ".conf", ".cfg", ".ini", ".yaml", ".yml", ".xml", ".log",
    ".md", ".txt", ".json", ".csv", ".pdf", ".doc", ".docx",
    ".xlsx", ".xls", ".ppt", ".pptx", ".html", ".htm",
}

app = FastAPI(title="IST-Core Web Terminal")

# SessionManager singleton (lazy init)
_session_mgr = None


def _get_session_mgr():
    global _session_mgr
    if _session_mgr is None:
        from main.ist_core.auth.session_manager import SessionManager
        _session_mgr = SessionManager()
    return _session_mgr


def _validate_request(session_id: str, jwt_token: str) -> dict | None:
    """Validate request: returns {"username", "role", "session_id"} or None."""
    if not session_id or not jwt_token:
        return None
    return _get_session_mgr().validate_session(session_id, jwt_token)


def get_auth_token(username: str, session_id: str) -> str | None:
    """Get jwt_token by username and session_id (for internal API calls)."""
    from main.ist_core.auth.db import pg_cursor
    from datetime import datetime, timezone

    try:
        with pg_cursor() as cur:
            cur.execute(
                """SELECT id FROM ist_audit.users WHERE username = %s""",
                (username,),
            )
            user_row = cur.fetchone()
            if not user_row:
                return None
            user_id = user_row["id"]
            cur.execute(
                """SELECT jwt_token, expires_at, is_valid
                   FROM ist_audit.sessions
                   WHERE user_id = %s AND session_id = %s AND is_valid = TRUE""",
                (user_id, session_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            if row["expires_at"] < datetime.now(timezone.utc):
                return None
            return row.get("jwt_token", "")
    except Exception as exc:
        logger.debug("get_auth_token failed: %s", exc)
        return None


# Login rate limiting (per client IP, sliding window)
_login_attempts: dict[str, list[float]] = {}
_LOGIN_MAX_FAILURES = int(os.environ.get("IST_WEB_LOGIN_MAX_FAILURES", "5"))
_LOGIN_WINDOW_SEC = int(os.environ.get("IST_WEB_LOGIN_WINDOW_SEC", "300"))

# Upload size limit
_MAX_UPLOAD_BYTES = int(os.environ.get("IST_WEB_MAX_UPLOAD_MB", "50")) * 1024 * 1024

# RBAC: only these roles can write (upload). reviewer is read-only.
_WRITE_ROLES = {r.strip() for r in os.environ.get("IST_WEB_WRITE_ROLES", "admin,superadmin").split(",") if r.strip()}

# Trusted proxy IP list (comma-separated)
_TRUSTED_PROXIES: list[str] = [
    p.strip() for p in os.environ.get("IST_TRUSTED_PROXIES", "").split(",") if p.strip()
]


def _client_ip(request: Request | None) -> str:
    if request is None or request.client is None:
        return "unknown"
    direct = request.client.host or "unknown"
    if not _TRUSTED_PROXIES:
        return direct
    try:
        direct_ip = ipaddress.ip_address(direct)
    except ValueError:
        return direct
    trusted = any(
        direct_ip in ipaddress.ip_network(cidr, strict=False) for cidr in _TRUSTED_PROXIES
    )
    if not trusted:
        return direct
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return direct


def _rate_limited(ip: str) -> bool:
    """Sliding window: reject if failures exceed threshold."""
    now = time.monotonic()
    attempts = [t for t in _login_attempts.get(ip, []) if now - t < _LOGIN_WINDOW_SEC]
    _login_attempts[ip] = attempts
    return len(attempts) >= _LOGIN_MAX_FAILURES


def _record_failure(ip: str) -> None:
    _login_attempts.setdefault(ip, []).append(time.monotonic())


def _ensure_env() -> None:
    """Load environment file from project root."""
    try:
        from dotenv import load_dotenv
        env_path = _PROJECT_ROOT / "environment"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except Exception:
        pass


# ------------------------------------------------------------------
# Auth API
# ------------------------------------------------------------------

@app.post("/api/login")
async def login(body: dict, request: Request):
    ip = _client_ip(request)
    if _rate_limited(ip):
        logger.warning("login rate-limited for ip=%s", ip)
        raise HTTPException(status_code=429, detail="登录尝试过多,请稍后再试")
    username = body.get("username", "")
    password = body.get("password", "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    # Query user from PG
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
        logger.error("login DB query failed: %s", exc)
        raise HTTPException(status_code=500, detail="服务暂时不可用")

    if not user:
        _record_failure(ip)
        logger.info("login failed user=%r (not found) ip=%s", username, ip)
        get_default_bus().emit(
            "auth_login_failed",
            payload={"username": username, "reason": "user_not_found"},
            tags={"source_ip": ip},
        )
        _emit_langfuse_auth_trace("auth:login_failed", user_id=username,
                                  input_data={"username": username},
                                  output_data={"result": "user_not_found"},
                                  metadata={"source_ip": ip}, tags=["auth", "web"])
        raise HTTPException(status_code=401, detail="用户名不存在")

    if user.get("account_status") != "normal":
        _record_failure(ip)
        logger.info("login failed user=%r (account locked/disabled) ip=%s", username, ip)
        get_default_bus().emit(
            "auth_login_failed",
            payload={"username": username, "reason": "account_locked", "account_status": user.get("account_status")},
            tags={"source_ip": ip},
        )
        _emit_langfuse_auth_trace("auth:login_failed", user_id=username,
                                  input_data={"username": username},
                                  output_data={"result": "account_locked", "status": user.get("account_status")},
                                  metadata={"source_ip": ip}, tags=["auth", "web"])
        raise HTTPException(status_code=403, detail="账号已被锁定或禁用")

    if not verify_password(user["password_hash"], password):
        _record_failure(ip)
        logger.info("login failed user=%r (wrong password) ip=%s", username, ip)
        get_default_bus().emit(
            "auth_login_failed",
            payload={"username": username, "reason": "wrong_password"},
            tags={"source_ip": ip},
        )
        _emit_langfuse_auth_trace("auth:login_failed", user_id=username,
                                  input_data={"username": username},
                                  output_data={"result": "wrong_password"},
                                  metadata={"source_ip": ip}, tags=["auth", "web"])
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # Create session (PG + Redis)
    role = user.get("role", "reviewer")
    try:
        session_id, jwt_token = _get_session_mgr().create_session(username, role, channel="web")
    except Exception as exc:
        logger.error("login create_session failed: %s", exc)
        raise HTTPException(status_code=500, detail="会话创建失败")

    # Ensure local + remote user directories exist
    try:
        (_WORKSPACE / "inputs" / username).mkdir(parents=True, exist_ok=True)
        (_WORKSPACE / "outputs" / username).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning("ensure local workspace dirs error: %s", e)
    try:
        remote_fs.ensure_dir(f"inputs/{username}")
        remote_fs.ensure_dir(f"outputs/{username}")
    except Exception as e:
        logger.warning("ensure remote dirs error: %s", e)

    # Create default conversation
    conv = None
    try:
        conv = _get_session_mgr().create_conversation(username, session_id=session_id)
    except Exception as exc:
        logger.debug("login create_conversation failed: %s", exc)

    logger.info("login ok user=%r role=%s session=%s ip=%s", username, role, session_id, ip)
    get_default_bus().emit(
        "auth_login",
        payload={"username": username, "role": role},
        tags={"session_id": session_id, "source_ip": ip, "session_user": username},
    )
    _conv_id = conv["conversation_id"] if conv else ""
    _emit_langfuse_auth_trace(
        "auth:login", user_id=username, session_id=session_id,
        input_data={"username": username},
        output_data={"result": "success", "session_id": session_id, "conversation_id": _conv_id, "role": role},
        metadata={"source_ip": ip, "role": role, "conversation_id": _conv_id, "channel": "web"},
        tags=["auth", "web"],
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
            _emit_langfuse_auth_trace("auth:logout", user_id=username, session_id=session_id,
                                      input_data={"username": username, "session_id": session_id},
                                      output_data={"result": "success"},
                                      tags=["auth", "web"])
        except Exception as exc:
            logger.debug("logout invalidate failed: %s", exc)
    return {"ok": True}


# ------------------------------------------------------------------
# User management API (PG-backed)
# ------------------------------------------------------------------

@app.get("/api/users")
async def list_users(session_id: str = "", token: str = ""):
    """List users (admin only)."""
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    if sess.get("role") != "superadmin":
        raise HTTPException(403, "需要超级管理员权限")
    from main.ist_core.auth.db import pg_cursor
    try:
        with pg_cursor() as cur:
            cur.execute(
                "SELECT username, role FROM ist_audit.users WHERE account_status = 'normal' ORDER BY username"
            )
            rows = cur.fetchall()
        return {"users": [{"username": r["username"], "role": r["role"], "enabled": True} for r in rows]}
    except Exception as exc:
        logger.error("list_users failed: %s", exc)
        raise HTTPException(500, "查询失败")


@app.post("/api/users/create")
async def create_user(body: dict):
    """注册功能暂不可用."""
    raise HTTPException(501, "注册功能暂不可用,请联系管理员")


@app.post("/api/users/delete")
async def delete_user(body: dict, session_id: str = "", token: str = ""):
    """Delete user (admin only)."""
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    if sess.get("role") != "superadmin":
        raise HTTPException(403, "需要超级管理员权限")

    username = body.get("username", "").strip()
    if not username:
        raise HTTPException(400, "用户名不能为空")
    if username == sess["username"]:
        raise HTTPException(400, "不能删除自己")

    from main.ist_core.auth.db import pg_cursor
    try:
        with pg_cursor() as cur:
            cur.execute("DELETE FROM ist_audit.users WHERE username = %s", (username,))
            if cur.rowcount == 0:
                raise HTTPException(404, "用户不存在")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_user DB error: %s", exc)
        raise HTTPException(500, "删除失败")

    # Clean up local workspace directories
    import shutil
    for subdir in ("inputs", "outputs"):
        local_dir = _WORKSPACE / subdir / username
        if local_dir.is_dir():
            try:
                shutil.rmtree(local_dir)
                logger.info("deleted local dir: workspace/%s/%s", subdir, username)
            except Exception as e:
                logger.warning("delete local %s dir error: %s", subdir, e)

    # Clean up remote directories
    try:
        remote_fs.delete_dir(f"inputs/{username}")
        logger.info("deleted remote inputs dir: inputs/%s", username)
    except Exception as e:
        logger.warning("delete remote inputs dir error: %s", e)
    try:
        remote_fs.delete_dir(f"outputs/{username}")
        logger.info("deleted remote outputs dir: outputs/%s", username)
    except Exception as e:
        logger.warning("delete remote outputs dir error: %s", e)

    logger.info("user deleted: %r by %s", username, sess["username"])
    return {"ok": True, "message": "User deleted"}


@app.post("/api/users/reset-password")
async def reset_user_password(body: dict, session_id: str = "", token: str = ""):
    """Reset user password (admin only)."""
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")
    if sess.get("role") != "superadmin":
        raise HTTPException(403, "需要超级管理员权限")

    username = body.get("username", "").strip()
    new_password = body.get("password", "").strip()

    if not username:
        raise HTTPException(400, "用户名不能为空")
    if len(new_password) < 6:
        raise HTTPException(400, "密码至少6个字符")

    from main.ist_core.auth.db import pg_cursor
    from main.ist_core.auth.password import hash_password
    new_hash = hash_password(new_password)
    try:
        with pg_cursor() as cur:
            cur.execute(
                "UPDATE ist_audit.users SET password_hash = %s WHERE username = %s",
                (new_hash, username),
            )
            if cur.rowcount == 0:
                raise HTTPException(404, "用户不存在")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("reset_password DB error: %s", exc)
        raise HTTPException(500, "密码重置失败")

    logger.info("password reset: %r by %s", username, sess["username"])
    return {"ok": True, "message": f"Password reset for user {username}"}


# ------------------------------------------------------------------
# Chat rating API
# ------------------------------------------------------------------

@app.post("/api/chat/rating/submit")
async def submit_rating(body: dict, session_id: str = "", token: str = ""):
    """Submit chat rating.

    Business logic:
    - Validate score in 0~5 range
    - UPSERT into sys_chat_rating
    - Async update sys_dialog_chat.rating
    - Write audit log
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

        try:
            from main.ist_core.sinks.langfuse_sink import submit_langfuse_score
            submit_langfuse_score(
                run_id=run_id,
                name="user-rating",
                value=float(score),
                comment=comment,
            )
        except Exception:
            pass

        return {"ok": True, "score": score}
    except Exception as exc:
        logger.error("submit_rating failed: %s", exc)
        raise HTTPException(500, "评分提交失败")


@app.get("/api/chat/rating/get")
async def get_rating(session_id: str = "", token: str = "", conversation_id: str = "", run_id: str = ""):
    """Query single chat rating."""
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
        logger.error("get_rating failed: %s", exc)
        raise HTTPException(500, "评分查询失败")


# ------------------------------------------------------------------
# File API (remote_fs)
# ------------------------------------------------------------------

@app.post("/api/upload")
async def upload(file: UploadFile = File(...), session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(status_code=401, detail="未登录")
    if sess.get("role") not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="无上传权限")

    username = sess.get("username", "")
    if not username:
        raise HTTPException(400, "无法获取用户名")

    # Sanitize filename
    raw_name = file.filename or "upload"
    safe_name = os.path.basename(raw_name.replace("\\", "/"))
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(400, "非法文件名")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, "不支持的文件类型")

    # Stream to temp file, then save locally + upload to remote
    import tempfile
    tmp_path = None
    try:
        written = 0
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "文件过大")
                tmp.write(chunk)

        # Save to local workspace/inputs/{username}/
        local_dir = _WORKSPACE / "inputs" / username
        local_dir.mkdir(parents=True, exist_ok=True)
        local_dest = local_dir / safe_name
        import shutil
        shutil.copy2(tmp_path, local_dest)

        # Upload to remote server
        remote_rel = f"inputs/{username}/{safe_name}"
        remote_fs.upload_file(tmp_path, remote_rel)

        return {"path": remote_rel, "filename": safe_name}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("upload error: %s", exc)
        raise HTTPException(500, "上传失败")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/api/files")
async def list_files(session_id: str = "", token: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")

    username = sess["username"]

    try:
        if username == "admin":
            files = remote_fs.list_dir_tree("outputs")
        else:
            files = remote_fs.list_dir_tree(f"outputs/{username}")
    except Exception as e:
        logger.error("list files error: %s", e)
        return {"files": []}

    return {"files": files}


@app.get("/api/download")
async def download_file(session_id: str = "", token: str = "", name: str = ""):
    sess = _validate_request(session_id, token)
    if not sess:
        raise HTTPException(401, "未登录")

    username = sess.get("username", "")
    if not username:
        raise HTTPException(400, "无法获取用户名")

    if not name or ".." in name:
        raise HTTPException(400, "非法文件名")
    name = name.replace("\\", "/")

    # Path security: normal users can only download from their own directory
    if username != "admin":
        if not name.startswith(f"{username}/") and name != username:
            raise HTTPException(403, "路径越权")

    # Download from remote to temp file, then serve
    import tempfile
    suffix = Path(name).suffix
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
        remote_fs.download_file(f"outputs/{name}", tmp_path)
        filename = Path(name).name
        return FileResponse(tmp_path, filename=filename)
    except FileNotFoundError:
        raise HTTPException(404, "文件不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("download error: %s", e)
        raise HTTPException(500, "下载失败")


# ------------------------------------------------------------------
# PTY helpers
# ------------------------------------------------------------------

def _set_winsize(fd: int, cols: int, rows: int):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


# ------------------------------------------------------------------
# Conversation management API
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


# ------------------------------------------------------------------
# WebSocket PTY bridge
# ------------------------------------------------------------------

@app.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    """WebSocket PTY bridge: spawn TUI subprocess, bidirectional forwarding."""
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
        await websocket.send_json({"type": "error", "msg": "该对话已关闭,无法发起新推理"})
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
    env["IST_AUTH_SESSION_ID"] = session_id
    env["IST_CONVERSATION_ID"] = conversation_id

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
        await asyncio.gather(pty_task, ws_task, return_exceptions=True)
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
    try:
        from main.ist_core.events import get_default_bus
        from main.ist_core.sinks.pg_sink import PgAuditSink
        get_default_bus().subscribe(PgAuditSink())
    except Exception as exc:
        logger.debug("PgAuditSink registration failed: %s", exc)
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
