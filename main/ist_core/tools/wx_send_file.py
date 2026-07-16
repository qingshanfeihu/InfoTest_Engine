"""企微发送文件工具：agent 调用后 gateway 自动将文件推送给用户。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 待发送文件队列（agent 写入，gateway 读取后清除）
_PENDING_FILES: list[dict[str, Any]] = []
_PENDING_LOCK = threading.Lock()


def pop_pending_files() -> list[dict[str, Any]]:
    """Gateway 调用：取出所有待发送文件并清空队列。"""
    with _PENDING_LOCK:
        files = list(_PENDING_FILES)
        _PENDING_FILES.clear()
        return files


@tool(parse_docstring=True)
def wx_send_file(file_path: str, note: str = "") -> str:
    """通过企业微信将文件发送给用户。

    当用户要求发送文件、或需要将生成的文件推送给用户时使用此工具。
    文件必须已存在于 workspace/outputs/ 目录下。

    Args:
        file_path: 文件路径（相对于项目根目录，如 workspace/outputs/xxx.txt）
        note: 可选的附带说明（如文件用途、内容摘要）
    """
    # 解析为绝对路径
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    if os.path.isabs(file_path):
        abs_path = file_path
    else:
        abs_path = os.path.join(project_root, file_path)

    abs_path = os.path.normpath(abs_path)

    if not os.path.isfile(abs_path):
        return f"错误：文件不存在 {file_path}"

    # 安全检查：只允许发送 workspace/outputs/ 下的文件
    outputs_dir = os.path.normpath(os.path.join(project_root, "workspace", "outputs"))
    if not abs_path.startswith(outputs_dir):
        return f"错误：只能发送 workspace/outputs/ 目录下的文件，当前路径 {file_path}"

    with _PENDING_LOCK:
        _PENDING_FILES.append({"path": abs_path, "note": note})

    fname = os.path.basename(abs_path)
    size_kb = os.path.getsize(abs_path) / 1024
    logger.info("文件已加入发送队列: %s (%.1f KB)", fname, size_kb)
    return f"文件 {fname}（{size_kb:.1f} KB）已加入发送队列，将在回复结束后推送给用户。"
