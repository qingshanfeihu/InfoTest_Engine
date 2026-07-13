"""dev_rest tool: Execute CLI commands on APV/NSAE devices via REST API.

Much faster than SSH — a single HTTP POST per call, no shell interaction overhead.
Supports auto-detection of device type (APV vs NSAE) from host or topology.

Safety gates (reused from ssh.py):
1. Device IP validation (must exist in network topology)
2. Shell metachar rejection (no pipes, redirects, chaining)
3. High-risk command blacklist
4. Command whitelist (safe config subset)
5. Timeout clamping
"""

from __future__ import annotations

import json
import logging
import os
import re

import requests
from langchain_core.tools import tool

from main.ist_core.tools.device.device_errors import has_cli_error
from main.ist_core.tools.device.ssh import (
    _DENIED_METACHARS,
    _HIGH_RISK_COMMANDS,
    _READ_ONLY_PREFIXES,
    _SAFE_CONFIG_PREFIXES,
    _validate_command,
    _validate_device_ip,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

_DEFAULT_RESTAPI_PORT = 9997
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120

# ── Tool ─────────────────────────────────────────────────────────────────


@tool(parse_docstring=True)
def dev_rest(
    host: str,
    command: str,
    username: str = "",
    password: str = "",
    port: int = _DEFAULT_RESTAPI_PORT,
    device_type: str = "apv",
    timeout: int = _DEFAULT_TIMEOUT,
) -> str:
    """Execute CLI commands on APV/NSAE devices via REST API (much faster than SSH).

    **PREREQUISITE** — before calling this tool, you MUST grep
    ``knowledge/data/markdown/product/cli_*_Chapter*.md`` +
    ``cli_*_Appendix*.md`` to confirm the exact
    command name and syntax. The device runs InfosecOS, NOT Cisco IOS.
    Correct commands come ONLY from the CLI manual — never guess and probe.

    Endpoint: ``https://<host>:<port>/rest/<device_type>/cli_extend``
    Method: POST
    Auth: Basic (REST API credentials, NOT SSH credentials)
    Body: ``{"cmd": "<cli command>"}``

    **IMPORTANT**: REST API executes commands directly — no enable/config mode
    needed. Do NOT prepend ``enable\\n`` or ``enable\\nconfig\\n``. Just send
    the actual command text itself (a show form, or a config form taken from
    the version manual / a verified precedent — not from this docstring).

    ``command`` can contain ``\\n`` for interactive commands (e.g. a command
    whose echo asks for a literal confirmation word)::

        "<command that prompts for confirmation>\\nYES\\n"

    Credentials from env: ``APV_RESTAPI_USERNAME``, ``APV_RESTAPI_PASSWORD``.
    Port from env: ``APV_RESTAPI_PORT`` (default 9997).

    Args:
        host: Target device IP address (must exist in network topology).
        command: CLI command to execute. Use ``\\n`` for multi-step interactive
            commands (each ``\\n`` is a separate line sent to the CLI).
        username: REST API username (env APV_RESTAPI_USERNAME, default "admin").
        password: REST API password (env APV_RESTAPI_PASSWORD, default "admin").
        port: REST API port (env APV_RESTAPI_PORT, default 9997).
        device_type: "apv" or "nsae" (default "apv").
        timeout: Request timeout in seconds (1..120, default 30).

    Returns:
        Structured output with host, command, status, and device response.
    """
    # 1. Validate device type
    device_type = (device_type or "apv").strip().lower()
    if device_type not in ("apv", "nsae"):
        return f"error: invalid device_type {device_type!r}. Must be 'apv' or 'nsae'."

    # 2. Validate host IP
    ok, reason = _validate_device_ip(host)
    if not ok:
        return f"error: {reason}"

    # 3. Validate command (reuse shared validation)
    command = (command or "").strip()
    if not command:
        return "error: empty command"

    # Split by newline and validate each segment (same gates as dev_ssh)
    segments = command.split("\n") if "\n" in command else [command]
    clean_segments = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        clean_segments.append(seg)
        # Check metachars (per-line, since \n is our separator)
        for mc in _DENIED_METACHARS:
            if mc in seg:
                return f"error: shell metachar {mc!r} in segment {seg!r}"
    if not clean_segments:
        return "error: empty command after splitting"

    # Full command validation against blacklist and whitelist
    # Use the first segment as primary command for whitelist check
    primary = clean_segments[0]
    # Check blacklist on all segments
    for seg in clean_segments:
        cmd_lower = " ".join(seg.lower().split())
        for pattern, explanation in _HIGH_RISK_COMMANDS:
            if pattern in cmd_lower:
                return f"error: high-risk command rejected ({explanation}): {seg!r}"

    # Whitelist check on primary command
    cmd_lower = primary.lower().strip()
    allowed = False
    for p in _SAFE_CONFIG_PREFIXES:
        if cmd_lower.startswith(p):
            allowed = True
            break
    if not allowed:
        for p in _READ_ONLY_PREFIXES:
            if cmd_lower.startswith(p):
                allowed = True
                break
    if not allowed:
        return (
            f"error: command {primary!r} not in the allowed whitelist. "
            f"Must start with a safe config prefix or show/list/display."
        )

    # 4. Clamp timeout and port
    timeout = max(1, min(int(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))
    port = max(1, min(int(port or _DEFAULT_RESTAPI_PORT), 65535))

    # 5. Resolve credentials
    resolved_user = username or os.environ.get("APV_RESTAPI_USERNAME", "")
    resolved_pass = password or os.environ.get("APV_RESTAPI_PASSWORD", "")
    if not resolved_user or not resolved_pass:
        return "error: REST API credentials not configured (set APV_RESTAPI_USERNAME and APV_RESTAPI_PASSWORD)"

    # 6. Build URL and body
    url = f"https://{host}:{port}/rest/{device_type}/cli_extend"
    body = {"cmd": command}
    auth = (resolved_user, resolved_pass)

    # 7. Execute
    try:
        resp = requests.post(
            url,
            json=body,
            auth=auth,
            timeout=timeout,
            verify=False,  # devices use self-signed certs
        )
    except requests.exceptions.Timeout:
        return f"error: REST API request to {host}:{port} timed out after {timeout}s"
    except requests.exceptions.ConnectionError as exc:
        return f"error: REST API connection to {host}:{port} failed: {exc}"
    except Exception as exc:
        return f"error: REST API request to {host}:{port} failed: {exc}"

    # 8. Parse response
    if resp.status_code == 401:
        return f"error: REST API authentication failed for {host}:{port} (HTTP 401)"
    if resp.status_code != 200:
        return (
            f"error: REST API returned HTTP {resp.status_code} for {host}:{port}\n"
            f"response: {resp.text[:500]}"
        )

    try:
        data = resp.json()
    except json.JSONDecodeError:
        data = {"contents": resp.text}

    contents = data.get("contents", "")

    # Detect CLI errors in response（收口到共享 device_errors）
    has_error = has_cli_error(contents)

    status = "error" if has_error else "success"

    # 9. Format output
    return (
        f"=== dev_rest ===\n"
        f"host={host}:{port}  device={device_type}\n"
        f"command: {command[:200]}\n"
        f"status: {status}\n"
        f"--- output ---\n"
        f"{contents if contents else '(empty — command executed successfully)'}"
    )
