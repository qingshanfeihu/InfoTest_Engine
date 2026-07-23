"""远程文件同步模块。

当 IST_REMOTE_OUTPUT=1 时，workspace/outputs/ 下的文件变更会自动同步到远程服务器。
用于 Web UI 场景，本地 TUI 不受影响。
"""

import logging
import os
import shutil
from pathlib import Path

from . import remote_fs

logger = logging.getLogger("ist_remote_sync")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_ROOT = _PROJECT_ROOT / "workspace"
_OUTPUTS_ROOT = _WORKSPACE_ROOT / "outputs"

# 是否启用远程同步
_ENABLED = bool(os.environ.get("IST_REMOTE_OUTPUT"))


def is_enabled() -> bool:
    """检查远程同步是否启用。"""
    return bool(os.environ.get("IST_REMOTE_OUTPUT"))


def sync_file(local_path: str | Path) -> bool:
    """同步单个文件到远程服务器。

    Args:
        local_path: 本地文件路径（绝对路径或相对于项目根目录）

    Returns:
        True if synced successfully, False otherwise.
    """
    if not is_enabled():
        return False

    local = Path(local_path)
    if not local.is_absolute():
        local = _PROJECT_ROOT / local

    try:
        # 计算相对于 workspace/outputs 的路径
        rel = local.relative_to(_OUTPUTS_ROOT)
        remote_rel = f"outputs/{rel}".replace("\\", "/")
        remote_fs.upload_file(str(local), remote_rel)
        logger.debug("synced: %s -> %s", local, remote_rel)
        return True
    except ValueError:
        # 不在 outputs/ 目录下，跳过
        return False
    except Exception as e:
        logger.warning("sync failed for %s: %s", local, e)
        return False


def sync_dir(local_dir: str | Path) -> int:
    """同步整个目录到远程服务器。

    Args:
        local_dir: 本地目录路径

    Returns:
        Number of files synced.
    """
    if not is_enabled():
        return 0

    local = Path(local_dir)
    if not local.is_absolute():
        local = _PROJECT_ROOT / local

    if not local.is_dir():
        return 0

    count = 0
    for file in local.rglob("*"):
        if file.is_file() and not file.name.startswith("."):
            if sync_file(file):
                count += 1
    return count


def sync_outputs() -> int:
    """同步整个 outputs 目录到远程服务器。

    Returns:
        Number of files synced.
    """
    return sync_dir(_OUTPUTS_ROOT)


def sync_user_outputs(username: str) -> int:
    """同步指定用户的输出目录到远程服务器。

    Args:
        username: 用户名

    Returns:
        Number of files synced.
    """
    user_dir = _OUTPUTS_ROOT / username
    return sync_dir(user_dir)


def sync_dir_to_user(local_dir: str | Path, username: str) -> int:
    """同步本地目录到远程服务器的指定用户目录下。

    Args:
        local_dir: 本地目录路径（如 workspace/outputs/数据中心改造/）
        username: 目标用户名

    Returns:
        Number of files synced.
    """
    if not is_enabled():
        return 0

    local = Path(local_dir)
    if not local.is_absolute():
        local = _PROJECT_ROOT / local

    if not local.is_dir():
        return 0

    # 获取目录名（如 "数据中心改造"）
    dir_name = local.name
    count = 0
    for file in local.rglob("*"):
        if file.is_file() and not file.name.startswith("."):
            try:
                # 计算相对于本地目录的路径
                rel = file.relative_to(local)
                rel_str = str(rel).replace("\\", "/")
                # 远程路径：outputs/{username}/{dir_name}/{rel}
                remote_rel = f"outputs/{username}/{dir_name}/{rel_str}"
                remote_fs.upload_file(str(file), remote_rel)
                logger.debug("synced: %s -> %s", file, remote_rel)
                count += 1
            except Exception as e:
                logger.warning("sync failed for %s: %s", file, e)
    return count
