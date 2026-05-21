"""反向 SFTP：通过 SSH 连回客户端拉取文件。

当用户从 Windows SSH 到 Mac 并拖拽文件时，终端粘贴的是 Windows 路径。
本模块通过 asyncssh 反向 SFTP 连回客户端的 OpenSSH Server 拉取文件到沙箱。

要求：客户端 Windows 需启用 OpenSSH Server（设置→系统→可选功能→OpenSSH 服务器）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path, PureWindowsPath

import asyncssh

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SANDBOX = _PROJECT_ROOT / "knowledge" / "data" / "markdown" / "qa"
_USERS_FILE = _PROJECT_ROOT / "ssh_users.json"


def _get_client_credentials(ssh_user: str) -> dict:
    """从 ssh_users.json 读取客户端连接信息。"""
    if not _USERS_FILE.exists():
        return {}
    try:
        data = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
        for u in data.get("users", []):
            if u.get("username") == ssh_user:
                return {
                    "client_os_user": u.get("client_os_user", ""),
                    "client_os_password": u.get("client_os_password", ""),
                    "client_ssh_port": u.get("client_ssh_port", 22),
                }
    except Exception:  # noqa: BLE001
        pass
    return {}


async def fetch_file_from_client(
    client_ip: str,
    remote_path: str,
    *,
    ssh_user: str = "",
    password: str | None = None,
    port: int = 22,
) -> Path | None:
    """反向 SFTP 连回客户端拉取文件。

    Args:
        client_ip: 客户端 IP
        remote_path: 客户端上的文件路径（Windows 格式）
        ssh_user: IST SSH 用户名（用于查找 client_os_user）
        password: Windows 密码（优先使用；为 None 时从配置读取）
        port: 客户端 SSH 端口

    Returns:
        沙箱内的本地路径，失败返回 None。
    """
    _SANDBOX.mkdir(parents=True, exist_ok=True)
    filename = PureWindowsPath(remote_path).name
    local_dest = _SANDBOX / filename

    # 读取客户端凭据
    creds = _get_client_credentials(ssh_user)
    os_user = creds.get("client_os_user") or ssh_user
    os_password = password or creds.get("client_os_password") or None
    os_port = creds.get("client_ssh_port") or port

    try:
        async with asyncssh.connect(
            client_ip,
            port=os_port,
            username=os_user,
            password=os_password,
            known_hosts=None,
            connect_timeout=10,
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                await sftp.get(remote_path, str(local_dest))
        logger.info("reverse sftp ok: %s → %s", remote_path, local_dest)
        return local_dest
    except Exception as exc:  # noqa: BLE001
        logger.warning("reverse sftp failed (%s@%s:%d): %s",
                       os_user, client_ip, os_port, exc)
        return None
