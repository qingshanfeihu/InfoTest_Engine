"""APV device REST API client.

Executes CLI commands on APV/NSAE devices via REST API (much faster than SSH/Telnet).

Endpoint: https://<host>:<port>/rest/<device_type>/cli_extend
Method: POST
Auth: Basic (REST API credentials, separate from SSH credentials)

Based on the reference implementation from InfoTest_Engine's restapi.py.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Default REST API port for APV devices
DEFAULT_RESTAPI_PORT = 9997
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120


def _detect_cli_error(contents: str) -> bool:
    """Check if CLI response contains an error indicator."""
    if not contents.strip():
        return False

    lower = contents.lower()
    if any(kw in lower for kw in (
        "% invalid", "% error", "% unknown", "% unrecognized",
        "syntax error", "invalid input", "command not found",
        "failed to execute",  # 设备统一失败裁决（不穷举业务措辞；"% Invalid input" 已被 "% invalid" 覆盖）
    )):
        return True

    # Caret on its own line indicates CLI syntax error
    for line in contents.splitlines():
        s = line.strip()
        if s == "^" or (len(s) <= 3 and "^" in s):
            return True

    return False


def execute_restapi(
    host: str,
    command: str,
    username: str = "admin",
    password: str = "admin",
    port: int = DEFAULT_RESTAPI_PORT,
    device_type: str = "apv",
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = False,
) -> dict:
    """Execute a CLI command on an APV device via REST API.

    Args:
        host: Device IP address.
        command: CLI command to execute. Use \\n for multi-step interactive commands.
        username: REST API username.
        password: REST API password.
        port: REST API port (default 9997).
        device_type: "apv" or "nsae".
        timeout: Request timeout in seconds.
        verify_ssl: Whether to verify SSL certificates (devices use self-signed certs).

    Returns:
        dict with keys: host, port, device_type, command, status, contents, error
    """
    # Validate device_type
    device_type = (device_type or "apv").strip().lower()
    if device_type not in ("apv", "nsae"):
        return {
            "host": host,
            "port": port,
            "device_type": device_type,
            "command": command,
            "status": "error",
            "contents": "",
            "error": f"Invalid device_type '{device_type}'. Must be 'apv' or 'nsae'.",
        }

    # Clamp values
    timeout = max(1, min(int(timeout or DEFAULT_TIMEOUT), MAX_TIMEOUT))
    port = max(1, min(int(port or DEFAULT_RESTAPI_PORT), 65535))

    # Build request
    url = f"https://{host}:{port}/rest/{device_type}/cli_extend"
    body = {"cmd": command}

    try:
        response = httpx.post(
            url,
            json=body,
            auth=(username, password),
            timeout=timeout,
            verify=verify_ssl,
        )
    except httpx.TimeoutException:
        return {
            "host": host,
            "port": port,
            "device_type": device_type,
            "command": command,
            "status": "error",
            "contents": "",
            "error": f"REST API request to {host}:{port} timed out after {timeout}s",
        }
    except httpx.ConnectError as exc:
        return {
            "host": host,
            "port": port,
            "device_type": device_type,
            "command": command,
            "status": "error",
            "contents": "",
            "error": f"REST API connection to {host}:{port} failed: {exc}",
        }
    except Exception as exc:
        return {
            "host": host,
            "port": port,
            "device_type": device_type,
            "command": command,
            "status": "error",
            "contents": "",
            "error": f"REST API request failed: {exc}",
        }

    # Handle HTTP errors
    if response.status_code == 401:
        return {
            "host": host,
            "port": port,
            "device_type": device_type,
            "command": command,
            "status": "error",
            "contents": "",
            "error": f"REST API authentication failed for {host}:{port} (HTTP 401)",
        }

    if response.status_code != 200:
        return {
            "host": host,
            "port": port,
            "device_type": device_type,
            "command": command,
            "status": "error",
            "contents": "",
            "error": (
                f"REST API returned HTTP {response.status_code} for {host}:{port}\n"
                f"response: {response.text[:500]}"
            ),
        }

    # Parse response body
    try:
        data = response.json()
    except json.JSONDecodeError:
        data = {"contents": response.text}

    contents = data.get("contents", "")

    # Detect CLI errors
    has_error = _detect_cli_error(contents)
    status = "error" if has_error else "success"

    return {
        "host": host,
        "port": port,
        "device_type": device_type,
        "command": command,
        "status": status,
        "contents": contents,
        "error": "",
    }
