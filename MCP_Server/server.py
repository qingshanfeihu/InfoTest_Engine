"""APV MCP Server — Entry point.

Quick start:
    # Stdio mode (Claude Desktop, Cline, etc.)
    python server.py

    # HTTP mode (remote access)
    python server.py --http

    # SSE mode (legacy clients)
    python server.py --sse

Requires Python 3.11+.

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
from pathlib import Path

# 加载 .env 文件（优先级高于系统环境变量中已存在的值）
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass  # python-dotenv 未安装，跳过

from apv_mcp_server.server import main, main_http, main_sse

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--http":
        main_http()
    elif len(sys.argv) > 1 and sys.argv[1] == "--sse":
        main_sse()
    else:
        main()
