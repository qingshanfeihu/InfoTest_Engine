"""APV MCP Server — Entry point.

Quick start:
    # Stdio mode (Claude Desktop, Cline, etc.)
    python server.py

    # HTTP mode (remote access)
    python server.py --http

    # SSE mode (legacy clients)
    python server.py --sse

Requires Python 3.8+.  Python 3.10+ 使用官方 mcp SDK，3.8/3.9 自动切换内置兼容层
(``_mcp_compat.py``) 实现 MCP JSON-RPC 协议，功能等价，无需额外依赖。

Configuration: 优先读取项目根目录下的 .env 文件，其次使用系统环境变量。
    APV_USERNAME           — SSH/Telnet username for APV devices (default: admin)
    APV_PASSWORD           — SSH/Telnet password for APV devices (default: admin)
    APV_ENABLE_PASSWORD    — Enable-mode password for APV devices (default: "")
    APV_RESTAPI_USERNAME   — REST API username (default: admin)
    APV_RESTAPI_PASSWORD   — REST API password (default: admin)
    LINUX_SSH_USERNAME     — SSH username for Linux servers (default: root)
    LINUX_SSH_PASSWORD     — SSH password for Linux servers (default: "click1")
    LINUX_SSH_KEY          — Path to SSH private key for Linux servers
    MCP_HOST               — HTTP/SSE listen address (default: 127.0.0.1)
    MCP_PORT               — HTTP/SSE listen port (default: 8000)
"""

import os
import sys
from pathlib import Path

# ── Python 版本检查 ─────────────────────────────────────────────────
_PY_VERSION = sys.version_info[:2]
if _PY_VERSION < (3, 8):
    sys.exit("ERROR: APV MCP Server requires Python 3.8 or newer.")

_MCP_AVAILABLE = _PY_VERSION >= (3, 10)
if not _MCP_AVAILABLE:
    print(
        "INFO: Running on Python {}.{} — using built-in MCP compat layer "
        "(official mcp SDK requires 3.10+).".format(*_PY_VERSION),
        file=sys.stderr,
    )

# 加载 .env 文件（优先级高于系统环境变量中已存在的值）
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass  # python-dotenv 未安装，跳过

_MCP_IMPORT_ERROR = None
try:
    from apv_mcp_server.server import main, main_http, main_sse
except ImportError as exc:
    _MCP_IMPORT_ERROR = exc

if __name__ == "__main__":
    if _MCP_IMPORT_ERROR is not None:
        sys.exit(
            f"ERROR: Cannot start MCP server on Python {_PY_VERSION[0]}.{_PY_VERSION[1]}.\n"
            f"The MCP FastMCP library requires Python 3.10+.\n"
            f"Import error: {_MCP_IMPORT_ERROR}\n\n"
            f"The client modules are still usable directly — import apv_mcp_server.ssh_apv "
            f"or apv_mcp_server.ssh_linux to use SSH/Telnet/REST clients without MCP."
        )
    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        main_http()
    elif len(sys.argv) > 1 and sys.argv[1] == "--sse":
        main_sse()
    else:
        main()
