"""远程文件系统操作模块 (SSH/SFTP)。

通过 SSH/SFTP 连接远程服务器进行文件操作。
"""

import os
import stat
from pathlib import Path
from typing import Optional

import paramiko

# 远程服务器配置
REMOTE_HOST = os.getenv("IST_REMOTE_HOST", "172.16.2.90")
REMOTE_PORT = int(os.getenv("IST_REMOTE_PORT", "22"))
REMOTE_USER = os.getenv("IST_REMOTE_USER", "root")
REMOTE_PASS = os.getenv("IST_REMOTE_PASS", "click1")
REMOTE_BASE = os.getenv("IST_REMOTE_BASE", "/root/infotest_server/uploads/workspace")


def _get_client() -> paramiko.SSHClient:
    """获取 SSH 客户端连接。"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=REMOTE_HOST,
        port=REMOTE_PORT,
        username=REMOTE_USER,
        password=REMOTE_PASS,
        timeout=10,
    )
    return client


def _get_sftp() -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
    """获取 SFTP 客户端。"""
    client = _get_client()
    sftp = client.open_sftp()
    return client, sftp


def _remote_path(relative_path: str) -> str:
    """将相对路径转换为远程绝对路径。"""
    # 清理路径
    clean = relative_path.replace("\\", "/").strip("/")
    return f"{REMOTE_BASE}/{clean}" if clean else REMOTE_BASE


def ensure_dir(relative_path: str) -> None:
    """确保远程目录存在。"""
    client, sftp = _get_sftp()
    try:
        remote = _remote_path(relative_path)
        # 逐级创建目录
        parts = remote.split("/")
        current = ""
        for part in parts:
            if not part:
                current = "/"
                continue
            current = f"{current}{part}" if current == "/" else f"{current}/{part}"
            try:
                sftp.stat(current)
            except FileNotFoundError:
                sftp.mkdir(current)
    finally:
        sftp.close()
        client.close()


def list_dir(relative_path: str = "") -> list[dict]:
    """列出远程目录内容。返回 [{name, type, size}]。"""
    client, sftp = _get_sftp()
    try:
        remote = _remote_path(relative_path)
        items = []
        try:
            entries = sftp.listdir_attr(remote)
        except FileNotFoundError:
            return []

        for entry in sorted(entries, key=lambda e: e.filename):
            # 跳过隐藏文件
            if entry.filename.startswith("."):
                continue
            item = {"name": entry.filename}
            if stat.S_ISDIR(entry.st_mode):
                item["type"] = "dir"
                item["children"] = []  # 稍后递归填充
            else:
                item["type"] = "file"
                item["size"] = entry.st_size or 0
            items.append(item)
        return items
    finally:
        sftp.close()
        client.close()


def list_dir_tree(relative_path: str = "", max_depth: int = 3) -> list[dict]:
    """递归构建远程目录树。"""
    if max_depth <= 0:
        return []

    client, sftp = _get_sftp()
    try:
        return _build_tree(sftp, _remote_path(relative_path), max_depth)
    finally:
        sftp.close()
        client.close()


def _build_tree(sftp: paramiko.SFTPClient, remote_path: str, max_depth: int) -> list[dict]:
    """递归构建目录树（内部函数）。"""
    items = []
    try:
        entries = sftp.listdir_attr(remote_path)
    except FileNotFoundError:
        return []

    for entry in sorted(entries, key=lambda e: e.filename):
        if entry.filename.startswith("."):
            continue
        item = {"name": entry.filename}
        full_path = f"{remote_path}/{entry.filename}"

        if stat.S_ISDIR(entry.st_mode):
            item["type"] = "dir"
            if max_depth > 1:
                item["children"] = _build_tree(sftp, full_path, max_depth - 1)
            else:
                item["children"] = []
        else:
            item["type"] = "file"
            item["size"] = entry.st_size or 0
        items.append(item)

    return items


def upload_file(local_path: str, relative_path: str) -> str:
    """上传文件到远程服务器。返回远程路径。"""
    client, sftp = _get_sftp()
    try:
        remote = _remote_path(relative_path)
        # 确保目标目录存在
        remote_dir = "/".join(remote.split("/")[:-1])
        if remote_dir:
            _ensure_remote_dir(sftp, remote_dir)
        sftp.put(local_path, remote)
        return remote
    finally:
        sftp.close()
        client.close()


def download_file(relative_path: str, local_path: str) -> None:
    """从远程服务器下载文件。"""
    client, sftp = _get_sftp()
    try:
        remote = _remote_path(relative_path)
        # 确保本地目录存在
        local_dir = os.path.dirname(local_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)
        sftp.get(remote, local_path)
    finally:
        sftp.close()
        client.close()


def delete_file(relative_path: str) -> None:
    """删除远程文件。"""
    client, sftp = _get_sftp()
    try:
        remote = _remote_path(relative_path)
        sftp.remove(remote)
    finally:
        sftp.close()
        client.close()


def delete_dir(relative_path: str) -> None:
    """递归删除远程目录。"""
    client, sftp = _get_sftp()
    try:
        remote = _remote_path(relative_path)
        _rmdir_recursive(sftp, remote)
    finally:
        sftp.close()
        client.close()


def _rmdir_recursive(sftp: paramiko.SFTPClient, path: str) -> None:
    """递归删除目录（内部函数）。"""
    try:
        entries = sftp.listdir_attr(path)
    except FileNotFoundError:
        return

    for entry in entries:
        full = f"{path}/{entry.filename}"
        if stat.S_ISDIR(entry.st_mode):
            _rmdir_recursive(sftp, full)
        else:
            sftp.remove(full)
    sftp.rmdir(path)


def _ensure_remote_dir(sftp: paramiko.SFTPClient, path: str) -> None:
    """确保远程目录存在（内部函数）。"""
    parts = path.split("/")
    current = ""
    for part in parts:
        if not part:
            current = "/"
            continue
        current = f"{current}{part}" if current == "/" else f"{current}/{part}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)


def file_exists(relative_path: str) -> bool:
    """检查远程文件是否存在。"""
    client, sftp = _get_sftp()
    try:
        remote = _remote_path(relative_path)
        sftp.stat(remote)
        return True
    except FileNotFoundError:
        return False
    finally:
        sftp.close()
        client.close()
