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
import fcntl
import json
import logging
import os
import pty
import shutil
import signal
import struct
import sys
import termios
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger("ist_web")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_USERS_FILE = _PROJECT_ROOT / "ssh_users.json"
_SANDBOX = _PROJECT_ROOT / "workspace" / "inputs"
_WEB_DIR = Path(__file__).resolve().parent / "web"
_CONVERTIBLE = {".xlsx", ".xls"}
_ALLOWED = {
    ".conf", ".cfg", ".ini", ".yaml", ".yml", ".xml", ".log",
    ".md", ".txt", ".json", ".csv", ".pdf", ".doc", ".docx",
    ".xlsx", ".xls", ".ppt", ".pptx", ".html", ".htm",
}

app = FastAPI(title="IST-Core Web Terminal")

_sessions: dict[str, str] = {}


def _load_users() -> dict[str, dict]:
    if not _USERS_FILE.exists():
        return {}
    try:
        data = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
        return {u["username"]: u for u in data.get("users", []) if u.get("enabled", True)}
    except Exception:
        return {}


@app.post("/api/login")
async def login(body: dict):
    username = body.get("username", "")
    password = body.get("password", "")
    users = _load_users()
    user = users.get(username)
    if not user or user.get("password") != password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = uuid.uuid4().hex
    _sessions[token] = username
    return {"token": token, "username": username}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), token: str = ""):
    if not _sessions.get(token):
        raise HTTPException(status_code=401, detail="未登录")
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in _ALLOWED:
        raise HTTPException(400, f"不支持的文件类型: {suffix}")
    dest = _SANDBOX / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    if suffix in _CONVERTIBLE:
        try:
            from main.xlsx_to_markdown import convert_xlsx_to_markdown
            md = convert_xlsx_to_markdown(dest)
            md_path = dest.with_suffix(".md")
            md_path.write_text(md, encoding="utf-8")
            rel = md_path.relative_to(_PROJECT_ROOT / "knowledge" / "data").as_posix()
            return {"path": rel, "filename": file.filename, "converted": True}
        except Exception as e:
            rel = dest.relative_to(_PROJECT_ROOT / "knowledge" / "data").as_posix()
            return {"path": rel, "filename": file.filename, "error": str(e)}
    rel = dest.relative_to(_PROJECT_ROOT / "knowledge" / "data").as_posix()
    return {"path": rel, "filename": file.filename}


_OUTPUTS = _PROJECT_ROOT / "workspace" / "outputs"


@app.get("/api/files")
async def list_files(token: str = ""):
    if not _sessions.get(token):
        raise HTTPException(401, "未登录")
    if not _OUTPUTS.is_dir():
        return {"files": []}
    files = []
    for f in sorted(_OUTPUTS.iterdir()):
        if f.is_file():
            files.append({"name": f.name, "size": f.stat().st_size})
    return {"files": files}


@app.get("/api/download")
async def download_file(token: str = "", name: str = ""):
    if not _sessions.get(token):
        raise HTTPException(401, "未登录")
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    target = (_OUTPUTS / name).resolve()
    if not str(target).startswith(str(_OUTPUTS.resolve())):
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
    # 第一条消息：认证 token
    auth = await websocket.receive_json()
    token = auth.get("token", "")
    username = _sessions.get(token)
    if not username:
        await websocket.send_json({"type": "error", "msg": "未登录"})
        await websocket.close()
        return

    cols = auth.get("cols", 120)
    rows = auth.get("rows", 40)

    # 创建 PTY + spawn TUI
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
        sys.executable, "-u", "-m", "main.qa_agent.tui.cli",
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        env=env, cwd=str(_PROJECT_ROOT), start_new_session=True,
    )
    os.close(slave_fd)

    loop = asyncio.get_event_loop()

    # PTY → WebSocket
    async def pty_to_ws():
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            await websocket.send_bytes(data)

    # WebSocket → PTY
    async def ws_to_pty():
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.receive":
                    if "bytes" in msg and msg["bytes"]:
                        os.write(master_fd, msg["bytes"])
                    elif "text" in msg and msg["text"]:
                        # JSON 消息：resize 或文本输入
                        try:
                            d = json.loads(msg["text"])
                            if d.get("type") == "resize":
                                _set_winsize(master_fd, d.get("cols", cols), d.get("rows", rows))
                                if proc.pid:
                                    os.kill(proc.pid, signal.SIGWINCH)
                            elif d.get("type") == "input":
                                os.write(master_fd, d["data"].encode("utf-8"))
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
