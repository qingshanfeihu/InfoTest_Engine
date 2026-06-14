"""qa_ssh tool: SSH to APV devices under strict safety controls.

Runs in-process (not via qa_exec subprocess), bypassing the sandbox network
block for the specific purpose of device verification and safe configuration.

Safety gates (applied in order):
1. Mode validation (show / config only)
2. Device IP validation (must exist in network topology)
3. Shell metachar rejection (no pipes, redirects, chaining)
4. High-risk command blacklist (reboot, shutdown, ip mod, user mod, clear)
5. Command whitelist (show mode: show/list/display; config mode: safe subset)
6. Timeout clamping (connect ≤30s, command ≤120s)
"""

from __future__ import annotations

import importlib.util
import logging
import os
import re
from pathlib import Path
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
from main import knowledge_paths as _kp
_TOPOLOGY_PATH = _kp.KNOWLEDGE_AUTO_ENV_TOPOLOGY
_APV_SSH_CLIENT_PATH = (
    Path(__file__).resolve().parents[2]
    / "skills" / "device-verify" / "scripts" / "apv_ssh_client.py"
)

# ── Timeout constants ────────────────────────────────────────────────────

_DEFAULT_CONNECT_TIMEOUT = 15
_MAX_CONNECT_TIMEOUT = 30
_DEFAULT_COMMAND_TIMEOUT = 30
_MAX_COMMAND_TIMEOUT = 120

# ── Shell metachar rejection ─────────────────────────────────────────────

_DENIED_METACHARS: tuple[str, ...] = (
    "|", ">", "<", ";", "&", "`", "$(", "${", "&&", "||", "<<", ">>",
)

# ── High-risk command blacklist (substring match, case-insensitive) ──────

_HIGH_RISK_COMMANDS: tuple[tuple[str, str], ...] = (
    # (pattern, explanation)
    ("system reboot", "device-level destruction (reboot)"),
    ("system shutdown", "device-level destruction (shutdown)"),
    ("ip address", "IP/interface modification (may cause loss of connectivity)"),
    ("no ip address", "IP/interface modification (may cause loss of connectivity)"),
    ("segment ip address", "IP/interface modification (may cause loss of connectivity)"),
    ("interface shutdown", "IP/interface modification (may cause loss of connectivity)"),
    ("no segment interface", "IP/interface modification (may cause loss of connectivity)"),
    ("no ip route", "routing table modification"),
    ("clear ip route", "routing table modification"),
    ("username", "user/permission modification (credentials change)"),
    ("segment user", "user/permission modification (credentials change)"),
    ("aaa", "authentication configuration modification"),
    ("tacacs", "authentication configuration modification"),
    ("radius", "authentication configuration modification"),
    ("clear config", "global configuration clear"),
)

# ── Allowed read-only command prefixes ───────────────────────────────────

_READ_ONLY_PREFIXES: tuple[str, ...] = (
    "show", "list", "display",
)

# ── Allowed config command prefixes (safe subset) ────────────────────────

_SAFE_CONFIG_PREFIXES: tuple[str, ...] = (
    # Core service modules — all sub-commands covered by module prefix.
    # Dangerous exceptions (system reboot/shutdown, ip address, etc.)
    # are caught by _HIGH_RISK_COMMANDS blacklist before whitelist check.
    "slb", "sdns", "segment", "ssl", "ha",
    # System (safe subset; dangerous entries blocked by blacklist)
    "hostname", "ntp", "syslog", "snmp",
    "log", "system",
    # Persistence
    "write memory", "write segment",
    # Deletion / clear — prefix match covers all sub-resources
    "no slb", "clear slb",
    "no sdns", "clear sdns",
    "no segment", "clear segment",
    "no ssl", "clear ssl",
    "no ha", "clear ha",
)

# ── IP validation cache ──────────────────────────────────────────────────

_valid_ips: set[str] | None = None


def _load_valid_ips() -> set[str]:
    """Parse network_topology_rag.md and extract all known device IPs."""
    if not _TOPOLOGY_PATH.exists():
        logger.warning("Topology file not found at %s; IP validation skipped.", _TOPOLOGY_PATH)
        return set()
    text = _TOPOLOGY_PATH.read_text(encoding="utf-8")
    ips: set[str] = set()
    for m in re.finditer(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", text):
        ips.add(m.group(1))
    for m in re.finditer(r"\b([0-9a-fA-F:]+:+[0-9a-fA-F:]+)\b", text):
        ips.add(m.group(1))
    return ips


def _validate_device_ip(host: str) -> tuple[bool, str]:
    """Check whether *host* (IP address) appears in the network topology."""
    global _valid_ips
    if _valid_ips is None:
        _valid_ips = _load_valid_ips()
    if not _valid_ips:
        return True, ""  # topology file missing → permissive (avoid blocking)
    if host in _valid_ips:
        return True, ""
    return False, (
        f"Device IP '{host}' not found in network topology ({_TOPOLOGY_PATH}). "
        "Refusing connection to unknown device."
    )


def _validate_command(command: str, mode: str) -> tuple[bool, str]:
    """Security checks for *command* in the given *mode*.

    Returns (allowed, reason).  *reason* is empty when allowed.
    """
    command = command.strip()
    if not command:
        return False, "empty command"

    # 1. Shell metachar check
    for mc in _DENIED_METACHARS:
        if mc in command:
            return False, f"shell metachar not allowed in qa_ssh: {mc!r}"

    # 2. High-risk blacklist check
    cmd_lower = " ".join(command.lower().split())
    for pattern, explanation in _HIGH_RISK_COMMANDS:
        if pattern in cmd_lower:
            return False, f"high-risk command rejected ({explanation}): {command!r}"

    # 3. Whitelist check by mode
    cmd_lower = command.lower().strip()
    if mode == "show":
        if any(cmd_lower.startswith(p) for p in _READ_ONLY_PREFIXES):
            return True, ""
        return False, (
            f"show mode only allows commands starting with: "
            f"{', '.join(_READ_ONLY_PREFIXES)}. Got: {command!r}"
        )
    else:  # config mode
        if any(cmd_lower.startswith(p) for p in _SAFE_CONFIG_PREFIXES):
            return True, ""
        if any(cmd_lower.startswith(p) for p in _READ_ONLY_PREFIXES):
            return True, ""
        return False, (
            f"config mode only allows the safe config subset. "
            f"Command {command!r} not in the whitelist."
        )


def _get_apv_ssh_client_class():
    """Lazy-load APVSSHClient from filesystem path (directory name has hyphen)."""
    spec = importlib.util.spec_from_file_location(
        "apv_ssh_client", str(_APV_SSH_CLIENT_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec from {_APV_SSH_CLIENT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.APVSSHClient


# ── Tool ─────────────────────────────────────────────────────────────────


@tool(parse_docstring=True)
def qa_ssh(
    host: str,
    command: str,
    username: str = "",
    password: str = "",
    enable_password: str = "",
    mode: str = "show",
    connect_timeout: int = _DEFAULT_CONNECT_TIMEOUT,
    command_timeout: int = _DEFAULT_COMMAND_TIMEOUT,
) -> str:
    """SSH to an APV device and execute a CLI command under strict safety controls.

    **PREFER qa_restapi instead.** REST API is faster (single HTTP call, no
    shell interaction). Only use this tool when qa_restapi is unavailable
    (connection refused, HTTP 401, or device doesn't support REST API).
    SSH is the fallback — not the first choice.

    **PREREQUISITE** — before calling this tool, you MUST grep
    ``knowledge/data/markdown/product/*cli__part*.md`` to confirm the exact
    command name and syntax. The device runs InfosecOS, NOT Cisco IOS.

    Data may live on the device, but COMMAND SYNTAX lives in the CLI manual.
    "I need to check the device for X" is NOT an excuse to guess a command
    name — grep the manual first for the correct show/list/display command,
    then use it. Common WRONG guesses: ``show ip interface brief``,
    ``show interface vlan``, ``show running-config interface``.
    All of these are Cisco commands that do not exist on InfosecOS — they will fail and waste turns.

    Safety gates applied in order:
    1. Target IP must exist in the known network topology.
    2. The command must not contain shell metacharacters (no pipes, redirects,
       semicolons, or command chaining).
    3. The command must not match any high-risk blacklist entry (reboot,
       shutdown, IP modification, user/password changes, clear config).
    4. The command must match the allowed prefixes for the requested mode:
       - show mode: only show/list/display commands.
       - config mode: only the safe whitelisted config subset (SLB, SDNS,
         segment, SSL, HA, hostname, NTP, syslog, SNMP, single-object
         deletion, write memory).

    Credentials are resolved from environment variables first, then from
    arguments: ``APV_USERNAME``, ``APV_PASSWORD``, ``APV_ENABLE_PASSWORD``.

    Use this tool for:
    - Read-only device check: ``host="172.16.34.70" command="show slb virtual all"``
    - Safe config deploy: ``host="172.16.34.70" command="slb virtual http v1 172.16.34.100 80 arp 0" mode="config"``

    Args:
        host: Target device IP address (must exist in network topology).
        command: Single CLI command to execute (no pipes/chains). Connection
            to the same host is kept alive across calls for speed.
        username: SSH username (falls back to APV_USERNAME env var, then "admin").
        password: SSH password (falls back to APV_PASSWORD env var, then "admin").
        enable_password: Enable-mode password (env APV_ENABLE_PASSWORD, default "").
        mode: "show" for read-only checks or "config" for safe changes (default: "show").
        connect_timeout: SSH connection timeout in seconds (1..30, default 15).
        command_timeout: Command execution timeout in seconds (1..120, default 30).

    Returns:
        Structured output with host, mode, command, status, and device output.
    """
    # 1. Validate mode
    mode = (mode or "show").strip().lower()
    if mode not in ("show", "config"):
        return f"error: invalid mode {mode!r}. Must be 'show' or 'config'."

    # 2. Validate host IP
    ok, reason = _validate_device_ip(host)
    if not ok:
        return f"error: {reason}"

    # 3. Validate command
    command = (command or "").strip()
    if not command:
        return "error: empty command"
    ok, reason = _validate_command(command, mode)
    if not ok:
        return f"error: {reason}"

    # 4. Clamp timeouts
    connect_timeout = max(
        1, min(int(connect_timeout or _DEFAULT_CONNECT_TIMEOUT), _MAX_CONNECT_TIMEOUT)
    )
    command_timeout = max(
        1, min(int(command_timeout or _DEFAULT_COMMAND_TIMEOUT), _MAX_COMMAND_TIMEOUT)
    )

    # 5. Resolve credentials
    resolved_user = username or os.environ.get("APV_USERNAME", "admin")
    resolved_pass = password or os.environ.get("APV_PASSWORD", "admin")
    resolved_enable = enable_password or os.environ.get("APV_ENABLE_PASSWORD", "")

    # 6. Import and execute via APVSSHClient
    try:
        APVSSHClient = _get_apv_ssh_client_class()
    except ImportError as exc:
        return f"error: failed to load APVSSHClient — is paramiko installed? ({exc})"
    except Exception as exc:
        return f"error: failed to load APVSSHClient: {exc}"

    client = APVSSHClient(
        host=host,
        username=resolved_user,
        password=resolved_pass,
        timeout=connect_timeout,
        command_timeout=command_timeout,
    )

    try:
        client.connect()
    except Exception as exc:
        return f"error: SSH connection to {host} failed: {exc}"

    results: list[dict[str, str]] = []
    try:
        if mode == "show":
            results = client.execute_show_commands([command])
        else:
            results = client.execute_config_commands([command])
    except Exception as exc:
        return f"error: SSH command execution failed on {host}: {exc}"
    finally:
        client.disconnect()

    # 7. Format output
    if not results:
        return f"=== qa_ssh ===\nhost={host}  mode={mode}\ncommand: {command}\nstatus: no results"

    r = results[0]
    header = (
        f"=== qa_ssh ===\n"
        f"host={host}  mode={mode}\n"
        f"command: {r['command']}\n"
        f"status: {r['status']}\n"
        f"--- output ---\n"
        f"{r['output']}"
    )
    return header
