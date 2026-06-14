"""跳转机 MCP server 部署（SFTP 推送 server 代码到 /home/test/mcp_server/）。

FIX-8 / 阶段 F：server 代码 git-track 在 IST-Core `main/device_mcp_server/`，
sftp 部署到跳转机 `/home/test/mcp_server/`（与 apv_src 物理隔离）。

- 只推 server 三件套（server.py / tools.py / result_db.py），不碰 apv_src。
- 凭据复用 device_mcp_client（env IST_JUMPHOST_PASS，不落盘）。
- 长驻进程注意：server 每次被 SSH exec 启动一个新进程（无状态），故部署=覆盖文件即可，
  无需重启常驻进程。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from main.case_compiler.config import get_config
from main.case_compiler.device_mcp_client import _connect

_LOCAL_DIR = Path(__file__).resolve().parent
_FILES = ["server.py", "tools.py", "result_db.py"]


def deploy(remote_dir: Optional[str] = None, verbose: bool = True) -> dict:
    """把 server 三件套 SFTP 推到跳转机。返回 {pushed: [...], remote_dir}。"""
    cfg = get_config()
    remote_dir = remote_dir or os.path.dirname(cfg.jumphost.server_path)
    c = _connect()
    pushed = []
    try:
        sftp = c.open_sftp()
        # 确保远端目录存在
        try:
            sftp.stat(remote_dir)
        except IOError:
            # 逐级建
            parts = remote_dir.strip("/").split("/")
            cur = ""
            for p in parts:
                cur += "/" + p
                try:
                    sftp.stat(cur)
                except IOError:
                    sftp.mkdir(cur)
        for fname in _FILES:
            local = _LOCAL_DIR / fname
            if not local.is_file():
                continue
            remote = remote_dir.rstrip("/") + "/" + fname
            sftp.put(str(local), remote)
            pushed.append(remote)
            if verbose:
                print("pushed %s -> %s" % (fname, remote))
        sftp.close()
    finally:
        c.close()
    return {"pushed": pushed, "remote_dir": remote_dir}


if __name__ == "__main__":
    import json
    print(json.dumps(deploy(), ensure_ascii=False, indent=2))
