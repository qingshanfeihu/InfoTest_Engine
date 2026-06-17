"""FastMCP server: register all device management tools.

Tools provided:
  1. apv_ssh_execute      — SSH to APV device, execute CLI command
  2. apv_telnet_execute   — Telnet to APV device, execute CLI command
  3. apv_restapi_execute  — REST API to APV device, execute CLI command
  4. linux_ssh_execute    — SSH to Linux server, execute shell command

Session management (for persistent connections):
  5. device_session_open  — Open a persistent session to a device
  6. device_session_exec  — Execute command on an open session
  7. device_session_close — Close a session
  8. device_session_list  — List all open sessions

Requires Python 3.10+ (FastMCP SDK constraint). Core client modules
(ssh_apv, telnet_apv, restapi_apv, ssh_linux) work on Python 3.8+.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]
except ImportError:
    from apv_mcp_server._mcp_compat import FastMCP  # Python 3.8/3.9 fallback

from apv_mcp_server.ssh_apv import APVSSHClient
from apv_mcp_server.telnet_apv import APVTelnetClient
from apv_mcp_server.restapi_apv import execute_restapi
from apv_mcp_server.ssh_linux import LinuxSSHClient

logger = logging.getLogger(__name__)

# ── FastMCP application ────────────────────────────────────────────────

mcp = FastMCP(
    name="APV Device Manager",
    instructions=(
        "MCP server for remote device management — SSH/Telnet/REST API for APV devices and SSH for Linux. "
        "Use apv_restapi_execute as the preferred method when available; fall back to apv_ssh_execute "
        "or apv_telnet_execute. For Linux servers, use linux_ssh_execute."
    ),
)

# ── Session store (in-memory) ──────────────────────────────────────────

_sessions: dict[str, dict[str, Any]] = {}


def _make_session_id() -> str:
    return uuid.uuid4().hex[:12]


# ═══════════════════════════════════════════════════════════════════════
# Tool 1: APV SSH Execute
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def apv_ssh_execute(
    host: str,
    command: str,
    username: str = "admin",
    password: str = "admin",
    enable_password: str = "",
    mode: str = "show",
    port: int = 22,
    connect_timeout: int = 15,
    command_timeout: int = 30,
) -> str:
    """SSH to an APV/InfosecOS device and execute a CLI command.

    Connects interactively, handles enable mode, config mode, and --More-- pagination
    automatically. Each call creates a fresh connection, executes, and disconnects.

    For APV devices, command syntax follows InfosecOS (NOT Cisco IOS):
    - show commands: "show slb virtual all", "show interface", "show running-config"
    - config commands: "slb virtual http v1 172.16.34.100 80 arp 0"

    Credentials can also be set via environment variables:
    APV_USERNAME, APV_PASSWORD, APV_ENABLE_PASSWORD

    Args:
        host: Device IP address (e.g., "172.16.34.70")
        command: CLI command to execute (single command, no pipes or chaining)
        username: SSH username (env APV_USERNAME, default "admin")
        password: SSH password (env APV_PASSWORD, default "admin")
        enable_password: Enable-mode password (env APV_ENABLE_PASSWORD, default "")
        mode: Execution mode — "show" for read-only checks, "config" for configuration changes
        port: SSH port (default 22)
        connect_timeout: SSH connection timeout in seconds (1-30)
        command_timeout: Command execution timeout in seconds (1-120)
    """
    resolved_user = username or os.environ.get("APV_USERNAME", "admin")
    resolved_pass = password or os.environ.get("APV_PASSWORD", "admin")
    resolved_enable = enable_password or os.environ.get("APV_ENABLE_PASSWORD", "")

    mode = (mode or "show").strip().lower()
    if mode not in ("show", "config"):
        return f"error: invalid mode '{mode}'. Must be 'show' or 'config'."

    connect_timeout = max(1, min(int(connect_timeout), 30))
    command_timeout = max(1, min(int(command_timeout), 120))

    loop = asyncio.get_running_loop()

    def _run():
        client = APVSSHClient(
            host=host, username=resolved_user, password=resolved_pass,
            port=port, timeout=connect_timeout, command_timeout=command_timeout,
        )
        try:
            client.connect()
            if mode == "show":
                results = client.execute_show_commands([command])
            else:
                results = client.execute_config_commands([command])
            if not results:
                return f"=== apv_ssh_execute ===\nhost={host}  mode={mode}\ncommand: {command}\nstatus: no results"
            r = results[0]
            return (
                f"=== apv_ssh_execute ===\nhost={host}  mode={mode}\n"
                f"command: {r['command']}\nstatus: {r['status']}\n--- output ---\n{r['output']}"
            )
        except Exception as exc:
            return f"error: SSH to {host} failed: {exc}"
        finally:
            client.disconnect()

    return await loop.run_in_executor(None, _run)


# ═══════════════════════════════════════════════════════════════════════
# Tool 2: APV Telnet Execute
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def apv_telnet_execute(
    host: str,
    command: str,
    username: str = "admin",
    password: str = "admin",
    enable_password: str = "",
    mode: str = "show",
    port: int = 23,
    connect_timeout: int = 15,
    command_timeout: int = 30,
) -> str:
    """Telnet to an APV/InfosecOS device and execute a CLI command.

    Connects via Telnet, handles login (user/password), enable mode,
    config terminal, and --More-- pagination automatically.

    The typical workflow:
    1. Telnet connect → login prompt → send username
    2. Password prompt → send password
    3. Send "enable" → send enable password if prompted
    4. If config mode: send "config terminal"
    5. Execute command
    6. Exit and disconnect

    Credentials can also be set via environment variables:
    APV_USERNAME, APV_PASSWORD, APV_ENABLE_PASSWORD

    Args:
        host: Device IP address
        command: CLI command to execute (single command)
        username: Login username (env APV_USERNAME, default "admin")
        password: Login password (env APV_PASSWORD, default "admin")
        enable_password: Enable-mode password (env APV_ENABLE_PASSWORD, default "")
        mode: Execution mode — "show" or "config"
        port: Telnet port (default 23)
        connect_timeout: Connection timeout in seconds (1-30)
        command_timeout: Command execution timeout in seconds (1-120)
    """
    resolved_user = username or os.environ.get("APV_USERNAME", "admin")
    resolved_pass = password or os.environ.get("APV_PASSWORD", "admin")
    resolved_enable = enable_password or os.environ.get("APV_ENABLE_PASSWORD", "")

    mode = (mode or "show").strip().lower()
    if mode not in ("show", "config"):
        return f"error: invalid mode '{mode}'. Must be 'show' or 'config'."

    connect_timeout = max(1, min(int(connect_timeout), 30))
    command_timeout = max(1, min(int(command_timeout), 120))

    loop = asyncio.get_running_loop()

    def _run():
        client = APVTelnetClient(
            host=host, username=resolved_user, password=resolved_pass,
            port=port, timeout=connect_timeout, command_timeout=command_timeout,
        )
        try:
            client.connect()
            client.enter_enable_mode(resolved_enable)
            if mode == "show":
                results = client.execute_show_commands([command])
            else:
                results = client.execute_config_commands([command])
            if not results:
                return f"=== apv_telnet_execute ===\nhost={host}  mode={mode}\ncommand: {command}\nstatus: no results"
            r = results[0]
            return (
                f"=== apv_telnet_execute ===\nhost={host}  mode={mode}\n"
                f"command: {r['command']}\nstatus: {r['status']}\n--- output ---\n{r['output']}"
            )
        except Exception as exc:
            return f"error: Telnet to {host} failed: {exc}"
        finally:
            client.disconnect()

    return await loop.run_in_executor(None, _run)


# ═══════════════════════════════════════════════════════════════════════
# Tool 3: APV REST API Execute
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def apv_restapi_execute(
    host: str,
    command: str,
    username: str = "admin",
    password: str = "admin",
    port: int = 9997,
    device_type: str = "apv",
    timeout: int = 30,
) -> str:
    """Execute a CLI command on an APV/NSAE device via REST API (fastest method).

    This is the PREFERRED method for APV devices. REST API is much faster than
    SSH or Telnet — a single HTTP POST, no shell interaction overhead.

    Endpoint: https://<host>:<port>/rest/<device_type>/cli_extend
    Auth: HTTP Basic (REST API credentials)

    IMPORTANT: REST API executes commands directly — no enable/config mode needed.
    Do NOT prepend "enable" or "config terminal". Just send the actual command:
      - "show slb virtual all"
      - "slb virtual http v1 172.16.34.100 80 arp 0"

    Use \\n for multi-step interactive commands.
    Credentials from env: APV_RESTAPI_USERNAME, APV_RESTAPI_PASSWORD

    Args:
        host: Device IP address
        command: CLI command to execute
        username: REST API username (env APV_RESTAPI_USERNAME, default "admin")
        password: REST API password (env APV_RESTAPI_PASSWORD, default "admin")
        port: REST API port (default 9997)
        device_type: "apv" (Application Platform) or "nsae" (Network Security)
        timeout: Request timeout in seconds (1-120, default 30)
    """
    resolved_user = username or os.environ.get("APV_RESTAPI_USERNAME", "admin")
    resolved_pass = password or os.environ.get("APV_RESTAPI_PASSWORD", "admin")

    result = execute_restapi(
        host=host, command=command, username=resolved_user, password=resolved_pass,
        port=port, device_type=device_type, timeout=timeout, verify_ssl=False,
    )

    if result["status"] == "error" and result["error"]:
        return (
            f"=== apv_restapi_execute ===\nhost={host}:{port}  device={result['device_type']}\n"
            f"command: {command[:200]}\nstatus: error\n--- error ---\n{result['error']}"
        )

    contents = result.get("contents", "")
    return (
        f"=== apv_restapi_execute ===\nhost={host}:{port}  device={result['device_type']}\n"
        f"command: {command[:200]}\nstatus: {result['status']}\n--- output ---\n"
        f"{contents if contents else '(empty — command executed successfully)'}"
    )


# ═══════════════════════════════════════════════════════════════════════
# Tool 4: Linux SSH Execute
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def linux_ssh_execute(
    host: str,
    command: str,
    username: str = "root",
    password: str = "click1",
    port: int = 22,
    connect_timeout: int = 15,
    command_timeout: int = 30,
    key_file: str = "",
) -> str:
    """SSH to a generic Linux server and execute a shell command.

    Uses paramiko exec_command for one-shot execution with exit code capture.
    Supports both password and SSH key authentication.

    Credentials from env: LINUX_SSH_USERNAME, LINUX_SSH_PASSWORD, LINUX_SSH_KEY

    Args:
        host: Linux server IP or hostname
        command: Shell command to execute (e.g., "ls -la /var/log", "df -h")
        username: SSH username (env LINUX_SSH_USERNAME, default "root")
        password: SSH password (env LINUX_SSH_PASSWORD, default "click1")
        port: SSH port (default 22)
        connect_timeout: SSH connection timeout in seconds (1-30)
        command_timeout: Command execution timeout in seconds (1-120)
        key_file: Path to SSH private key file (env LINUX_SSH_KEY, optional)
    """
    resolved_user = username or os.environ.get("LINUX_SSH_USERNAME", "root")
    resolved_pass = password or os.environ.get("LINUX_SSH_PASSWORD", "click1")
    resolved_key = key_file or os.environ.get("LINUX_SSH_KEY", "")

    connect_timeout = max(1, min(int(connect_timeout), 30))
    command_timeout = max(1, min(int(command_timeout), 120))

    loop = asyncio.get_running_loop()

    def _run():
        client = LinuxSSHClient(
            host=host, username=resolved_user, password=resolved_pass,
            port=port, timeout=connect_timeout, command_timeout=command_timeout,
            key_filename=resolved_key if resolved_key else None,
        )
        try:
            client.connect()
            return client.execute(command)
        except Exception as exc:
            return {"command": command, "stdout": "", "stderr": str(exc), "exit_code": -1, "status": "error"}
        finally:
            client.disconnect()

    result = await loop.run_in_executor(None, _run)

    if result["status"] == "error" and result["exit_code"] == -1:
        return (
            f"=== linux_ssh_execute ===\nhost={host}:{port}\n"
            f"command: {command}\nstatus: error\n--- stderr ---\n{result['stderr']}"
        )

    return (
        f"=== linux_ssh_execute ===\nhost={host}:{port}\n"
        f"command: {command}\nexit_code: {result['exit_code']}  status: {result['status']}\n"
        f"--- stdout ---\n{result['stdout']}"
        + (f"\n--- stderr ---\n{result['stderr']}" if result.get("stderr") else "")
    )


# ═══════════════════════════════════════════════════════════════════════
# Tool 5: Device Session Open
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def device_session_open(
    host: str,
    device_type: str,
    username: str = "",
    password: str = "",
    enable_password: str = "",
    port: int = 0,
    connect_timeout: int = 15,
    command_timeout: int = 30,
) -> str:
    """Open a persistent session to a device for multiple commands.

    Keeps the connection alive between calls. Use device_session_exec to run
    commands on the open session, and device_session_close when done.

    Args:
        host: Device IP address
        device_type: Type of device — "apv_ssh", "apv_telnet", or "linux_ssh"
        username: Login username (uses env vars if empty)
        password: Login password (uses env vars if empty)
        enable_password: Enable-mode password (APV only)
        port: Connection port (uses default for device type if 0)
        connect_timeout: Connection timeout in seconds (1-30)
        command_timeout: Command execution timeout in seconds (1-120)

    Returns:
        Session ID string — pass this to device_session_exec and device_session_close.
    """
    device_type = device_type.strip().lower()
    if device_type not in ("apv_ssh", "apv_telnet", "linux_ssh"):
        return f"error: invalid device_type '{device_type}'. Must be 'apv_ssh', 'apv_telnet', or 'linux_ssh'."

    connect_timeout = max(1, min(int(connect_timeout), 30))
    command_timeout = max(1, min(int(command_timeout), 120))
    session_id = _make_session_id()
    loop = asyncio.get_running_loop()

    def _open():
        if device_type == "apv_ssh":
            resolved_user = username or os.environ.get("APV_USERNAME", "admin")
            resolved_pass = password or os.environ.get("APV_PASSWORD", "admin")
            port_val = port if port > 0 else 22
            client = APVSSHClient(
                host=host, username=resolved_user, password=resolved_pass,
                port=port_val, timeout=connect_timeout, command_timeout=command_timeout,
            )
            client.connect()
            resolved_enable = enable_password or os.environ.get("APV_ENABLE_PASSWORD", "")
            client.enter_enable_mode(resolved_enable)
            client.enter_config_mode()
            return client, resolved_enable, "config"
        elif device_type == "apv_telnet":
            resolved_user = username or os.environ.get("APV_USERNAME", "admin")
            resolved_pass = password or os.environ.get("APV_PASSWORD", "admin")
            port_val = port if port > 0 else 23
            client = APVTelnetClient(
                host=host, username=resolved_user, password=resolved_pass,
                port=port_val, timeout=connect_timeout, command_timeout=command_timeout,
            )
            client.connect()
            resolved_enable = enable_password or os.environ.get("APV_ENABLE_PASSWORD", "")
            client.enter_enable_mode(resolved_enable)
            client.enter_config_mode()
            return client, resolved_enable, "config"
        else:  # linux_ssh
            resolved_user = username or os.environ.get("LINUX_SSH_USERNAME", "root")
            resolved_pass = password or os.environ.get("LINUX_SSH_PASSWORD", "click1")
            resolved_key = os.environ.get("LINUX_SSH_KEY", "")
            port_val = port if port > 0 else 22
            client = LinuxSSHClient(
                host=host, username=resolved_user, password=resolved_pass,
                port=port_val, timeout=connect_timeout, command_timeout=command_timeout,
                key_filename=resolved_key if resolved_key else None,
            )
            client.connect()
            return client, "", "shell"

    try:
        client, enable_pw, current_mode = await loop.run_in_executor(None, _open)
        _sessions[session_id] = {"client": client, "device_type": device_type, "host": host, "enable_password": enable_pw, "mode": current_mode}
        mode_label = "config" if current_mode == "config" else "shell"
        return f"Session opened.\nsession_id: {session_id}\ndevice_type: {device_type}\nhost: {host}\nmode: {mode_label}"
    except Exception as exc:
        return f"error: failed to open {device_type} session to {host}: {exc}"


# ═══════════════════════════════════════════════════════════════════════
# Tool 6: Device Session Execute
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def device_session_exec(
    session_id: str,
    command: str,
    mode: str = "show",
) -> str:
    """Execute a command on an already-open device session.

    Args:
        session_id: Session ID returned by device_session_open
        command: CLI/shell command to execute
        mode: "show" for read-only, "config" for configuration (APV only)
    """
    session = _sessions.get(session_id)
    if not session:
        return f"error: session '{session_id}' not found."

    client = session["client"]
    device_type = session["device_type"]
    host = session["host"]
    mode = (mode or "show").strip().lower()

    loop = asyncio.get_running_loop()

    def _exec():
        if device_type == "linux_ssh":
            result = client.execute(command)
            return (
                f"=== device_session_exec ===\nsession={session_id}  host={host}  type={device_type}\n"
                f"command: {command}\nexit_code: {result['exit_code']}  status: {result['status']}\n"
                f"--- stdout ---\n{result['stdout']}"
                + (f"\n--- stderr ---\n{result['stderr']}" if result.get("stderr") else "")
            )
        else:
            # Session is already in config mode, send command directly
            output = client.send_command(command, wait=3.0)
            status = "error" if client._has_cli_error(output) else "success"
            return (
                f"=== device_session_exec ===\nsession={session_id}  host={host}  type={device_type}  mode=config\n"
                f"command: {command}\nstatus: {status}\n--- output ---\n{output.strip()}"
            )

    try:
        return await loop.run_in_executor(None, _exec)
    except Exception as exc:
        return f"error: command execution on session '{session_id}' failed: {exc}"


# ═══════════════════════════════════════════════════════════════════════
# Tool 7: Device Session Close
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def device_session_close(session_id: str) -> str:
    """Close a persistent device session.

    Args:
        session_id: Session ID returned by device_session_open
    """
    session = _sessions.pop(session_id, None)
    if not session:
        return f"error: session '{session_id}' not found."

    client = session["client"]
    host = session["host"]
    device_type = session["device_type"]
    current_mode = session.get("mode", "")

    loop = asyncio.get_running_loop()

    def _close():
        try:
            # Exit config mode for APV devices
            if current_mode == "config" and hasattr(client, "exit_config_mode"):
                client.exit_config_mode()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    await loop.run_in_executor(None, _close)
    return f"Session '{session_id}' ({device_type} to {host}) closed."


# ═══════════════════════════════════════════════════════════════════════
# Tool 8: Device Session List
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def device_session_list() -> str:
    """List all currently open device sessions."""
    if not _sessions:
        return "No active device sessions."
    lines = ["Active device sessions:", ""]
    for sid, s in _sessions.items():
        lines.append(f"  {sid}  →  {s['device_type']} @ {s['host']}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Tool 9: Smoke Test Upload & Run
# ═══════════════════════════════════════════════════════════════════════

_SMOKE_TEST_DIR = "/home/test/apv_src/smoke_test/istcore"

@mcp.tool()
async def smoke_test_run(filename: str, build: str = "") -> str:
    """Run smoke tests on a previously uploaded xlsx file.

    This MCP server runs ON THE LINUX TEST SERVER. The caller must first
    upload the xlsx file to /home/test/apv_src/smoke_test/istcore/<filename>
    (via SCP, shared mount, or linux_ssh_execute), then call this tool to
    execute the tests.

    Steps:
    1. Create subdirectory smoke_test/istcore/<stem>/ and verify xlsx exists there
    2. Extract case IDs from xlsx, write to lists/istcore
    3. Copy test_xlsx.py into the subdirectory if missing
    4. Run: pytest -s ./smoke_test/istcore/<stem>/test_xlsx.py --list istcore --build <build>
    5. Scan /home/test/apv_src/report/istcore/ for "The failed check point num: <N>"
    6. Return entries where N > 0

    Args:
        filename: The xlsx filename (e.g., "filled_sdns_listener.xlsx")
        build: Build version for --build flag (env SMOKE_BUILD, default "InfosecOS-Rel_APV-HG-K_10_5_0_istcore.click")
    """
    import subprocess as _sp

    # Resolve build version
    resolved_build = build or os.environ.get("SMOKE_BUILD", "InfosecOS-Rel_APV-HG-K_10_5_0_istcore.click")

    # Create a subdirectory named after the xlsx stem
    stem = Path(filename).stem
    run_dir = Path(_SMOKE_TEST_DIR) / stem
    run_dir.mkdir(parents=True, exist_ok=True)

    dest_path = run_dir / filename

    # Step 1: Verify file
    if not dest_path.exists():
        return (
            f"error: file not found: {dest_path}\n"
            f"Please upload the xlsx to {run_dir}/ first."
        )

    # Step 2: Extract case IDs from xlsx and write to list file
    loop = asyncio.get_running_loop()

    def _extract_case_ids():
        """Read xlsx and return list of case autoids (A column values).

        Uses the zipfile+xml approach (no openpyxl dependency) to extract
        the A column from the first worksheet.
        """
        import zipfile
        import xml.etree.ElementTree as ET

        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        zf = zipfile.ZipFile(str(dest_path))

        # Read shared strings
        ss = []
        try:
            for t in ET.parse(zf.open('xl/sharedStrings.xml')).iter(f'{ns}t'):
                ss.append(t.text or '')
        except KeyError:
            pass  # No shared strings — all inline

        # Read first sheet
        sheet = ET.parse(zf.open('xl/worksheets/sheet1.xml'))

        # Find header row and collect all A cells
        rows_data = {}
        for r in sheet.iter(f'{ns}row'):
            rn = int(r.get('r'))
            a_val = None
            for c in r.iter(f'{ns}c'):
                ref = c.get('r')
                if not ref or ref[0] != 'A':
                    continue
                # Shared string (indexed via <v>)
                v_el = c.find(f'{ns}v')
                if v_el is not None and v_el.text:
                    if c.get('t') == 's' and ss:
                        idx = int(v_el.text)
                        a_val = ss[idx] if idx < len(ss) else v_el.text
                    else:
                        a_val = v_el.text
                # Inline string (<is><t>text</t></is>) — openpyxl output
                if a_val is None:
                    is_el = c.find(f'{ns}is')
                    if is_el is not None:
                        t_el = is_el.find(f'{ns}t')
                        if t_el is not None and t_el.text:
                            a_val = t_el.text
                break
            if a_val is not None:
                rows_data[rn] = a_val

        # Find "自动化ID" header and extract subsequent numeric IDs
        header_row = 1
        for rn in sorted(rows_data):
            if '自动化ID' in str(rows_data[rn]):
                header_row = rn + 1
                break

        case_ids = []
        for rn in sorted(rows_data):
            if rn < header_row:
                continue
            v = str(rows_data[rn]).strip()
            if v and v != '0' and v != 'None' and v.isdigit():
                case_ids.append(v)

        return case_ids

    try:
        case_ids = await loop.run_in_executor(None, _extract_case_ids)
    except Exception as exc:
        return f"error: failed to read case IDs from xlsx: {exc}"

    if not case_ids:
        return f"error: no case IDs found in column A of {filename}"

    # Write list file
    list_file = Path("/home/test/apv_src/lists/istcore")
    list_file.parent.mkdir(parents=True, exist_ok=True)
    base_name = Path(filename).name
    list_content = "\n".join(
        f"| exec%APV0 | {base_name}: {cid}"
        for cid in case_ids
    )
    list_file.write_text(list_content)

    # Step 3: Ensure test_xlsx.py exists in the run directory
    test_py = run_dir / "test_xlsx.py"
    if not test_py.exists():
        src_test_py = Path("/home/test/apv_src/smoke_test/test_xlsx.py")
        if src_test_py.exists():
            import shutil as _shutil
            _shutil.copy2(str(src_test_py), str(test_py))

    # Step 4: Run pytest
    loop = asyncio.get_running_loop()
    rel_path = f"./smoke_test/istcore/{stem}/test_xlsx.py"
    cmd = (
        f"source /home/test/apv_src/.python3.8/bin/activate && "
        f"cd /home/test/apv_src && "
        f"pytest -s {rel_path} --list istcore --build {resolved_build}"
    )

    def _run_pytest():
        proc = _sp.run(
            ["/bin/bash", "-c", cmd],
            capture_output=True, text=True, timeout=600,
            cwd="/home/test/apv_src",
        )
        return proc.returncode, proc.stdout, proc.stderr

    try:
        exit_code, stdout, stderr = await loop.run_in_executor(None, _run_pytest)
    except Exception as exc:
        return f"error: pytest execution failed: {exc}"

    # Step 5: Collect failed cases from report directory
    # Report: report/<timestamp-build>/istcore/<stem>/test_xlsx/<xlsx>/<case_id>/<case_id>.txt
    report_root = Path("/home/test/apv_src/report")
    failures: list[str] = []
    failed_case_ids: set[str] = set()

    if report_root.exists():
        build_for_dir = resolved_build.replace(".click", "").replace("InfosecOS-", "").replace("-", "_")
        report_dirs = sorted(
            [d for d in report_root.iterdir() if d.is_dir() and build_for_dir.lower() in d.name.lower()],
            key=lambda d: d.name, reverse=True
        )
        if report_dirs:
            xlsx_dir = report_dirs[0] / "istcore" / stem / "test_xlsx" / base_name
            if xlsx_dir.exists():
                for case_dir in sorted(xlsx_dir.iterdir()):
                    if not case_dir.is_dir():
                        continue
                    txt = case_dir / f"{case_dir.name}.txt"
                    if not txt.exists():
                        continue
                    content = txt.read_text(encoding="utf-8", errors="replace")
                    # Check if this case has failures
                    has_failure = False
                    for line in content.splitlines():
                        if "The failed check point num:" in line:
                            parts = line.split("The failed check point num:")
                            if len(parts) > 1:
                                n = parts[1].strip().split()[0]
                                if n.isdigit() and int(n) > 0:
                                    has_failure = True
                                    failed_case_ids.add(case_dir.name)
                            break
                    if not has_failure and "Fail Num" in content:
                        failed_case_ids.add(case_dir.name)

    if failed_case_ids and report_root.exists():
        base_name = Path(filename).name
        stem = Path(filename).stem
        # Find latest report directory matching the build (strip InfosecOS- prefix)
        build_for_dir = resolved_build.replace(".click", "").replace("InfosecOS-", "").replace("-", "_")
        report_dirs = sorted(
            [d for d in report_root.iterdir() if d.is_dir() and build_for_dir.lower() in d.name.lower()],
            key=lambda d: d.name, reverse=True
        )

        if report_dirs:
            xlsx_report_dir = report_dirs[0] / "istcore" / stem / "test_xlsx" / base_name
            if xlsx_report_dir.exists():
                for cid in sorted(failed_case_ids):
                    case_dir = xlsx_report_dir / cid
                    txt_file = case_dir / f"{cid}.txt"
                    if not txt_file.exists():
                        continue
                    content = txt_file.read_text(encoding="utf-8", errors="replace")
                    # Extract relevant lines: step/check/command/fail/pass/success lines
                    relevant = []
                    for l in content.splitlines():
                        s = l.strip()
                        if any(k in s for k in (
                            "#######",           # step / check headers
                            "#### Fail",         # failure details
                            "#### Success",      # success details (context)
                            "sends command",     # CLI commands executed
                            "fail to find",      # check_point mismatch
                            "successed to find", # check_point match (context)
                            "The failed check",  # summary line
                            "The passed check",  # summary line
                            "PASS", "FAIL",      # final verdict
                        )):
                            relevant.append(s)
                    failures.append(
                        f"{cid}  path={case_dir}/{cid}.txt\n"
                        + "\n".join(f"    {rl}" for rl in relevant)
                    )

    failed_count = len(failed_case_ids) if failed_case_ids else 0

    failed_count = len(failures)
    status = "failed" if failed_count > 0 else "all_passed"
    lines = [
        f"=== smoke_test_run ===",
        f"file: {filename}",
        f"pytest exit_code: {exit_code}  failed check points: {failed_count}  status: {status}",
    ]
    if failed_count > 0:
        lines.append("--- failures ---")
        lines.extend(failures)
        lines.append(f"\nUse linux_ssh_execute to read report: cat <path>")
    else:
        lines.append("--- result ---")
        lines.append("All check points passed (failed num = 0)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Entry points
# ═══════════════════════════════════════════════════════════════════════

def main():
    """Run via stdio (Claude Desktop, etc.)."""
    mcp.run(transport="stdio")


def main_http():
    """Run via HTTP (remote access). MCP_HOST / MCP_PORT env vars supported."""
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    mcp.run(transport="http", host=host, port=port)


def main_sse():
    """Run via SSE (legacy clients). MCP_HOST / MCP_PORT env vars supported."""
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    mcp.run(transport="sse", host=host, port=port)
