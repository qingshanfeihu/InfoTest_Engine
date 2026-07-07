"""文件收发工具——严格按照官方文档 §101463 协议。

接收文件:
  用户在企微发文件 → aibot_msg_callback(msgtype="file")
  → body.file = {url, aeskey}
  → HTTP GET url 下载加密文件 → AES-256-CBC 解密

发送文件（WebSocket 原生上传，三阶段）:
  1. aibot_upload_media_init  → {type, filename, total_chunks} → {upload_id}
  2. aibot_upload_media_chunk → {upload_id, chunk_index, chunk_content(b64)}
  3. aibot_upload_media_finish → {upload_id} → {type, media_id}
  4. aibot_respond_msg(msgtype="file", media_id=...)  → 推送给用户
"""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import os
import secrets
import time
from typing import Any

import requests

logger = logging.getLogger("wecom_bot_smart.files")

# ============================================================================
# 分片参数
# ============================================================================

CHUNK_SIZE = 5 * 1024 * 1024   # 每个分片 5MB
_MAX_FILE_BYTES = 100 * 1024 * 1024  # 单文件上限 100MB


# ============================================================================
# 文件接收（下载 + 解密）
# ============================================================================

def download_qywx_file(url: str, aeskey: str, save_dir: str = ".") -> str:
    """下载并解密用户发送的文件。

    根据官方文档 §101463「多媒体资源解密」:
      - 加密方式: AES-256-CBC
      - PKCS#7 填充至 32 字节倍数
      - IV = aeskey 前 16 字节
      - URL 5 分钟内有效

    Args:
        url: 文件下载地址（来自 body.file.url）
        aeskey: 解密密钥（来自 body.file.aeskey）
        save_dir: 保存目录

    Returns:
        解密后的文件保存路径
    """
    # 1. 下载加密文件
    logger.info("下载文件: url=%.80s…", url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    encrypted_data = resp.content

    # 2. AES-256-CBC 解密
    key = base64.b64decode(aeskey + "===")  # 补缺失的 Base64 填充
    iv = key[:16]  # IV 取 aeskey 前 16 字节

    from Crypto.Cipher import AES
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    decrypted = cipher.decrypt(encrypted_data)

    # 3. PKCS#7 去填充 (块大小 32)
    pad_len = decrypted[-1]
    if 1 <= pad_len <= 32:
        decrypted = decrypted[:-pad_len]

    # 4. 落盘
    filename = _safe_filename(url)
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)

    with open(save_path, "wb") as f:
        f.write(decrypted)

    logger.info("文件已保存: %s (%d bytes)", save_path, len(decrypted))
    return save_path


def _safe_filename(url: str) -> str:
    """从 URL 末尾取文件名，加上时间戳避免冲突。"""
    ts = int(time.time())
    # 冒号之后的通常是真实文件名（或随机 hash）
    base = os.path.basename(url.split("?")[0])
    if not base or base == "/":
        base = f"qywx_file_{ts}"
    return f"{ts}_{base}"


# ============================================================================
# 文件发送（WS 原生上传 → 发送消息）
# ============================================================================

def upload_and_send_file(
    ws,
    file_path: str,
    stream_id: str,
    req_id: str,
    user_id: str = "",
) -> str | None:
    """通过 WS 原生协议上传文件并发送给用户。

    完整流程:
      1. init → 获取 upload_id
      2. chunk (N 个分片)
      3. finish → 获取 media_id
      4. aibot_respond_msg(file, media_id=media_id)

    Args:
        ws: WebSocketApp 实例
        file_path: 本地文件路径
        stream_id: 流式消息 stream.id
        req_id: 透传的 req_id
        user_id: 接收者 userid

    Returns:
        media_id 或 None（失败时）
    """
    if not os.path.isfile(file_path):
        logger.error("文件不存在: %s", file_path)
        _send_error(ws, stream_id, req_id, "文件不存在")
        return None

    fsize = os.path.getsize(file_path)
    fname = os.path.basename(file_path)
    if fsize > _MAX_FILE_BYTES:
        logger.error("文件过大: %d bytes", fsize)
        _send_error(ws, stream_id, req_id, f"文件过大 ({fsize / 1024 / 1024:.0f}MB > 100MB)")
        return None

    if fsize == 0:
        logger.error("文件为空: %s", file_path)
        _send_error(ws, stream_id, req_id, "文件为空")
        return None

    total_chunks = max(1, math.ceil(fsize / CHUNK_SIZE))
    logger.info("上传文件: %s (%d bytes, %d chunks)", fname, fsize, total_chunks)

    # 1. init
    upload_id = _upload_init(ws, fname, total_chunks)
    if not upload_id:
        _send_error(ws, stream_id, req_id, "上传初始化失败")
        return None

    # 2. 分片上传
    try:
        with open(file_path, "rb") as f:
            for i in range(total_chunks):
                chunk = f.read(CHUNK_SIZE)
                chunk_b64 = base64.b64encode(chunk).decode("ascii")
                ok = _upload_chunk(ws, upload_id, i, chunk_b64)
                if not ok:
                    _send_error(ws, stream_id, req_id, f"分片 {i + 1}/{total_chunks} 上传失败")
                    return None
    except Exception as e:
        logger.exception("读取文件失败")
        _send_error(ws, stream_id, req_id, f"读取文件失败: {e}")
        return None

    # 3. finish → 获取 media_id
    media_id = _upload_finish(ws, upload_id)
    if not media_id:
        _send_error(ws, stream_id, req_id, "上传完成确认失败")
        return None

    logger.info("上传完成: media_id=%s", media_id)

    # 4. 通过 aibot_respond_msg 发送文件消息
    _send_file_msg(ws, stream_id, media_id, req_id)
    return media_id


# ============================================================================
# 上传三阶段 — 通过 WS 发送 cmd 并收集响应（同步等待）
# ============================================================================

def _upload_init(ws, filename: str, total_chunks: int) -> str:
    """初始化上传 → 返回 upload_id。"""
    rid = _mk_req_id()
    _send_cmd(ws, "aibot_upload_media_init", {
        "type": "file",
        "filename": filename,
        "total_chunks": total_chunks,
    }, req_id=rid)
    # 等待同一个 req_id 的响应（WS 回调需要配合——见下方 upload 事件处理）
    result = _wait_response(ws, rid, timeout=30)
    if result:
        return result.get("upload_id", "")
    return ""


def _upload_chunk(ws, upload_id: str, chunk_index: int, chunk_content_b64: str) -> bool:
    """上传一个分片。"""
    rid = _mk_req_id()
    _send_cmd(ws, "aibot_upload_media_chunk", {
        "upload_id": upload_id,
        "chunk_index": chunk_index,
        "chunk_content": chunk_content_b64,
    }, req_id=rid)
    result = _wait_response(ws, rid, timeout=30)
    return result is not None and result.get("errcode", -1) == 0


def _upload_finish(ws, upload_id: str) -> str:
    """完成上传 → 返回 media_id。"""
    rid = _mk_req_id()
    _send_cmd(ws, "aibot_upload_media_finish", {
        "upload_id": upload_id,
    }, req_id=rid)
    result = _wait_response(ws, rid, timeout=30)
    if result:
        return result.get("media_id", "")
    return ""


# ============================================================================
# 同步等待响应（WS 回调是异步的，需要用 req_id 匹配）
# ============================================================================

# ws_instance → {req_id: response_event}
_pending_uploads: dict[int, dict[str, Any]] = {}
import threading as _th
_pending_lock = _th.Lock()


def _wait_response(ws, req_id: str, timeout: int) -> dict[str, Any] | None:
    """同步等待特定 req_id 的 WS 响应。"""
    ws_id = id(ws)
    event = _th.Event()
    key = f"{ws_id}:{req_id}"
    with _pending_lock:
        _pending_uploads[key] = {"event": event, "result": None}

    if not event.wait(timeout):
        with _pending_lock:
            _pending_uploads.pop(key, None)
        logger.warning("等待响应超时: req_id=%s", req_id)
        return None

    with _pending_lock:
        entry = _pending_uploads.pop(key, None)
    return entry["result"] if entry else None


def notify_upload_response(ws, req_id: str, result: dict[str, Any]) -> None:
    """在 _on_message 中收到 upload 相关响应时调用，
    唤醒 _wait_response 中的等待线程。"""
    ws_id = id(ws)
    key = f"{ws_id}:{req_id}"
    with _pending_lock:
        entry = _pending_uploads.get(key)
    if entry:
        entry["result"] = result
        entry["event"].set()
    else:
        logger.debug("无等待方: req_id=%s", req_id)


# ============================================================================
# 发送文件消息（通过 WS）
# ============================================================================

def _send_file_msg(ws, stream_id: str, media_id: str, req_id: str) -> None:
    """通过 aibot_respond_msg 发送文件消息给用户。

    官方文档 §101463「回复普通消息」— 文件消息格式:
      body.msgtype = "file"
      body.file = {"media_id": "..."}
    """
    _send_cmd(ws, "aibot_respond_msg", {
        "msgtype": "file",
        "file": {"media_id": media_id},
    }, req_id=req_id)
    logger.info("文件消息已发送: stream=%s media_id=%s", stream_id, media_id)


# ============================================================================
# 错误回复
# ============================================================================

def _send_error(ws, stream_id: str, req_id: str, msg: str) -> None:
    _send_cmd(ws, "aibot_respond_msg", {
        "msgtype": "stream",
        "stream": {"id": stream_id, "finish": True, "content": f"❌ {msg}"},
    }, req_id=req_id)


# ============================================================================
# 工具函数
# ============================================================================

def _mk_req_id() -> str:
    import uuid
    return uuid.uuid4().hex[:16]


def _send_cmd(ws, cmd: str, body: dict, req_id: str | None = None) -> str:
    rid = req_id or _mk_req_id()
    ws.send(json.dumps({"cmd": cmd, "headers": {"req_id": rid}, "body": body},
                       ensure_ascii=False))
    return rid


import json
