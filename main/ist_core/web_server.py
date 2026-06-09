"""IST-Core Web Terminal server.

xterm.js 前端 + WebSocket PTY 后端：
- / GET：xterm.js 终端页面（含登录 + 文件上传/下载按钮）
- /api/login POST：验证用户
- /api/upload POST：文件上传到沙箱
- /api/files GET：列出 workspace/outputs/ 下可下载文件
- /api/download GET：下载 workspace/outputs/ 中的文件
- /ws/terminal WebSocket：PTY 桥接（spawn TUI 子进程）
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import hmac
import json
import logging
import os
import pty
import secrets
import signal
import struct
import sys
import termios
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

logger = logging.getLogger("ist_web")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_USERS_FILE = _PROJECT_ROOT / "ssh_users.json"
_SANDBOX = _PROJECT_ROOT / "workspace" / "inputs"
_WEB_DIR = Path(__file__).resolve().parent / "web"
_ALLOWED = {
    ".conf", ".cfg", ".ini", ".yaml", ".yml", ".xml", ".log",
    ".md", ".txt", ".json", ".csv", ".pdf", ".doc", ".docx",
    ".xlsx", ".xls", ".ppt", ".pptx", ".html", ".htm",
}

app = FastAPI(title="IST-Core Web Terminal")

# token -> {"username", "role", "expires_at"}
_sessions: dict[str, dict] = {}
_SESSION_TTL_SEC = int(os.environ.get("IST_WEB_SESSION_TTL_SEC", str(8 * 3600)))

# 登录失败限流（按客户端 IP，滑动窗口）
_login_attempts: dict[str, list[float]] = {}
_LOGIN_MAX_FAILURES = int(os.environ.get("IST_WEB_LOGIN_MAX_FAILURES", "5"))
_LOGIN_WINDOW_SEC = int(os.environ.get("IST_WEB_LOGIN_WINDOW_SEC", "300"))

# 上传体积上限
_MAX_UPLOAD_BYTES = int(os.environ.get("IST_WEB_MAX_UPLOAD_MB", "50")) * 1024 * 1024

# RBAC：仅这些角色可写（上传）。reviewer 只读。
_WRITE_ROLES = {r.strip() for r in os.environ.get("IST_WEB_WRITE_ROLES", "admin").split(",") if r.strip()}

_PBKDF2_ITERATIONS = 200_000


def _load_users() -> dict[str, dict]:
    if not _USERS_FILE.exists():
        return {}
    try:
        data = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
        return {u["username"]: u for u in data.get("users", []) if u.get("enabled", True)}
    except Exception:
        return {}


def _verify_password(user: dict, password: str) -> bool:
    """恒定时间校验密码。

    支持两种存储：
    - ``password_hash``: ``pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>``（推荐）
    - ``password``: 明文（向后兼容，登录时打 warning 提示尽快迁移）
    """
    stored_hash = user.get("password_hash")
    if stored_hash:
        try:
            algo, iters, salt_hex, want_hex = stored_hash.split("$", 3)
            if algo != "pbkdf2_sha256":
                return False
            dk = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                bytes.fromhex(salt_hex), int(iters),
            )
            return hmac.compare_digest(dk.hex(), want_hex)
        except Exception:
            return False
    # 明文兜底（恒定时间比较，避免时序侧信道）
    plain = user.get("password")
    if plain is None:
        return False
    logger.warning(
        "user %r authenticated via plaintext password; migrate to password_hash",
        user.get("username", "?"),
    )
    return hmac.compare_digest(str(plain), password)


def hash_password(password: str) -> str:
    """生成 password_hash 字符串。供运维脚本 / 文档调用。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


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


def _new_session(username: str, role: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "role": role,
        "expires_at": time.time() + _SESSION_TTL_SEC,
    }
    return token


def _resolve_session(token: str) -> dict | None:
    """校验 token：不存在 / 过期 → None（过期顺手清理）。"""
    sess = _sessions.get(token)
    if not sess:
        return None
    if time.time() >= sess.get("expires_at", 0):
        _sessions.pop(token, None)
        return None
    return sess


@app.post("/api/login")
async def login(body: dict, request: Request):
    ip = _client_ip(request)
    if _rate_limited(ip):
        logger.warning("login rate-limited for ip=%s", ip)
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
    username = body.get("username", "")
    password = body.get("password", "")
    users = _load_users()
    user = users.get(username)
    if not user or not _verify_password(user, password):
        _record_failure(ip)
        logger.info("login failed user=%r ip=%s", username, ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    role = user.get("role", "reviewer")
    token = _new_session(username, role)
    logger.info("login ok user=%r role=%s ip=%s", username, role, ip)
    return {"token": token, "username": username, "role": role}


@app.post("/api/logout")
async def logout(body: dict):
    token = body.get("token", "")
    _sessions.pop(token, None)
    return {"ok": True}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), token: str = ""):
    sess = _resolve_session(token)
    if not sess:
        raise HTTPException(status_code=401, detail="未登录")
    if sess.get("role") not in _WRITE_ROLES:
        raise HTTPException(status_code=403, detail="无上传权限")
    _SANDBOX.mkdir(parents=True, exist_ok=True)

    # 仅取 basename，剥离任何目录分量 → 防 ../../ 路径遍历
    raw_name = file.filename or "upload"
    safe_name = os.path.basename(raw_name.replace("\\", "/"))
    if not safe_name or safe_name in (".", ".."):
        raise HTTPException(400, "非法文件名")
    suffix = Path(safe_name).suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, "不支持的文件类型")

    dest = (_SANDBOX / safe_name).resolve()
    # 双保险：解析后必须仍在 _SANDBOX 内
    if not str(dest).startswith(str(_SANDBOX.resolve()) + os.sep):
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


@app.get("/api/files")
async def list_files(token: str = ""):
    if not _resolve_session(token):
        raise HTTPException(401, "未登录")
    if not _OUTPUTS.is_dir():
        return {"files": []}
    files = []
    for f in sorted(_OUTPUTS.iterdir()):
        # 跳过隐藏文件（.gitkeep 等占位/元数据），不作为可下载产物列出
        if f.is_file() and not f.name.startswith("."):
            files.append({"name": f.name, "size": f.stat().st_size})
    return {"files": files}


@app.get("/api/download")
async def download_file(token: str = "", name: str = ""):
    if not _resolve_session(token):
        raise HTTPException(401, "未登录")
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    target = (_OUTPUTS / name).resolve()
    if not str(target).startswith(str(_OUTPUTS.resolve()) + os.sep):
        raise HTTPException(403, "路径越权")
    if not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target, filename=name)


def _set_winsize(fd: int, cols: int, rows: int):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


@app.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    """WebSocket PTY 桥接：spawn TUI 子进程，双向转发。"""
    await websocket.accept()

    auth = await websocket.receive_json()
    token = auth.get("token", "")
    sess = _resolve_session(token)
    if not sess:
        await websocket.send_json({"type": "error", "msg": "未登录或会话已过期"})
        await websocket.close()
        return
    username = sess["username"]

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


def serve(host: str = "0.0.0.0", port: int = 8080):
    import uvicorn
    logger.info("IST-Core Web Terminal on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    serve(args.host, args.port)
