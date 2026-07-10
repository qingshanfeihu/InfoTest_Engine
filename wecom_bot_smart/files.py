"""文件收发——接收走 SDK decrypt_file，上传走官方 SDK。"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import requests
from wecom_aibot_sdk.crypto import decrypt_file

logger = logging.getLogger("wecom_bot_smart.files")

CHUNK_SIZE = 512 * 1024  # 512KB（SDK 标准分片大小）
_MAX_FILE_BYTES = 100 * 1024 * 1024  # 100MB


# ============================================================================
# 文件接收（下载 + SDK AES 解密）
# ============================================================================

def download_qywx_file(file_url: str, aes_key_b64: str, save_dir: str) -> str:
    """下载企微加密文件并解密保存。

    Returns:
        保存后的文件路径
    """
    os.makedirs(save_dir, exist_ok=True)

    resp = requests.get(file_url, timeout=60)
    resp.raise_for_status()
    encrypted = resp.content

    # 使用 SDK 内置解密（处理 base64 padding + PKCS#7 32 字节块）
    data = decrypt_file(encrypted, aes_key_b64)

    # 从 URL 或 Content-Disposition 提取文件名
    fname = os.path.basename(file_url.split("?")[0]) or "downloaded_file"
    cd = resp.headers.get("Content-Disposition", "")
    if "filename" in cd:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\s]+)', cd)
        if m:
            fname = requests.utils.unquote(m.group(1))

    save_path = os.path.join(save_dir, fname)
    # 避免覆盖
    if os.path.exists(save_path):
        base, ext = os.path.splitext(fname)
        save_path = os.path.join(save_dir, f"{base}_{os.urandom(4).hex()}{ext}")

    with open(save_path, "wb") as f:
        f.write(data)

    logger.info("文件已保存: %s (%d bytes)", save_path, len(data))
    return save_path


# ============================================================================
# 文件上传（官方 SDK）
# ============================================================================

def validate_file(file_path: str) -> str:
    """校验文件是否可上传。返回空字符串=OK，非空=错误信息。"""
    if not os.path.isfile(file_path):
        return f"文件不存在: {file_path}"
    fsize = os.path.getsize(file_path)
    if fsize > _MAX_FILE_BYTES:
        return f"文件过大（{fsize / 1024 / 1024:.0f}MB > 100MB）"
    if fsize < 5:
        return f"文件过小（{fsize}字节，最少5字节）"
    return ""
