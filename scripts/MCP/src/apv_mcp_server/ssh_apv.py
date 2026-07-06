"""APV device SSH client via paramiko.

Connects to APV/InfosecOS load balancers over SSH, handles interactive shell,
enable mode, config mode, and --More-- pagination.

Based on the reference implementation from InfoTest_Engine's apv_ssh_client.py.
"""

from __future__ import annotations

import re
import time
from typing import Optional

import paramiko

# CLI error detection reuses the canonical module when available.
# MCP_Server may be deployed standalone, so fall back to a local equivalent.
try:
    from main.ist_core.tools.device.device_errors import (
        has_cli_error as _has_cli_error_shared,
    )
except Exception:  # pragma: no cover - standalone deployment
    _has_cli_error_shared = None


class APVSSHClient:
    """SSH interactive client for APV/InfosecOS load balancers."""

    # Prompt patterns for APV CLI modes
    PROMPT_PATTERNS = [
        r"[\w\-]+>",              # user mode: APV>
        r"[\w\-]+#",              # enable mode: APV#
        r"[\w\-]+\([^\)]+\)#",    # config mode: APV(config)#
    ]
    MORE_PATTERN = r"--More--"

    def __init__(
        self,
        host: str,
        username: str = "admin",
        password: str = "admin",
        port: int = 22,
        timeout: int = 15,
        command_timeout: int = 30,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.command_timeout = command_timeout
        self.ssh: Optional[paramiko.SSHClient] = None
        self.shell: Optional[paramiko.Channel] = None
        self._current_mode: str = "user"  # user | enable | config

    # ── Connection management ──────────────────────────────────────────

    def connect(self) -> str:
        """Establish SSH connection and open interactive shell. Returns login banner."""
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            look_for_keys=False,
            allow_agent=False,
        )
        self.shell = self.ssh.invoke_shell(term="vt100", width=200, height=50)
        self.shell.settimeout(self.command_timeout)
        banner = self._read_until_prompt(initial_wait=3.0)
        self._current_mode = "user"
        return banner

    def disconnect(self) -> None:
        """Disconnect SSH session cleanly."""
        if self.shell:
            try:
                self.shell.close()
            except Exception:
                pass
            self.shell = None
        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
            self.ssh = None
        self._current_mode = "user"

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    # ── Internal helpers ───────────────────────────────────────────────

    # Patterns that indicate the device is waiting for password input
    _PASSWORD_PATTERNS = [
        r"[Pp]assword:\s*$",
        r"[Ee]nable password:\s*$",
    ]

    def _read_until_prompt(
        self,
        initial_wait: float = 1.0,
        max_wait: float = 0,
        extra_patterns: Optional[list] = None,
    ) -> str:
        """Read output until a CLI prompt is detected or timeout. Handles --More-- pagination.

        Args:
            extra_patterns: additional regex patterns to match (e.g. password prompts).
                If any extra pattern matches, reading stops immediately.
        """
        if max_wait <= 0:
            max_wait = self.command_timeout

        output = ""
        start = time.time()
        time.sleep(initial_wait)

        while time.time() - start < max_wait:
            if self.shell.recv_ready():
                chunk = self.shell.recv(65535).decode("utf-8", errors="replace")
                output += chunk

                # Handle --More-- pagination
                if re.search(self.MORE_PATTERN, output):
                    output = re.sub(r"\s*--More--\s*", "", output)
                    self.shell.send(" ")
                    time.sleep(0.3)
                    continue

                # Check extra patterns (password prompts, etc.)
                if extra_patterns:
                    stripped = output.rstrip()
                    if any(re.search(p, stripped) for p in extra_patterns):
                        break

                # Check for CLI prompt
                stripped = output.rstrip()
                if any(re.search(p + r"\s*$", stripped) for p in self.PROMPT_PATTERNS):
                    break
            else:
                time.sleep(0.3)

        return output

    def send_command(self, command: str, wait: float = 2.0) -> str:
        """Send a single command and return the captured output (without prompt line)."""
        if not self.shell:
            raise RuntimeError("SSH shell not connected. Call connect() first.")

        # Drain any pending data
        while self.shell.recv_ready():
            self.shell.recv(65535)

        self.shell.send(command + "\n")
        raw = self._read_until_prompt(initial_wait=wait)

        lines = raw.splitlines()
        # Remove the echoed command line (first line)
        if lines and command.strip() in lines[0]:
            lines = lines[1:]
        return "\n".join(lines)

    # ── Mode switching ─────────────────────────────────────────────────

    def enter_enable_mode(self, enable_password: str = "") -> str:
        """Enter enable (privileged) mode. Returns output from the transition."""
        if self._current_mode in ("enable", "config"):
            return ""  # already privileged

        if not self.shell:
            raise RuntimeError("SSH shell not connected. Call connect() first.")

        # Drain pending data
        while self.shell.recv_ready():
            self.shell.recv(65535)

        # Send "enable" and wait for either a password prompt or a CLI prompt
        self.shell.send("enable\n")
        output = self._read_until_prompt(
            initial_wait=1.5,
            extra_patterns=self._PASSWORD_PATTERNS,
        )

        if "assword" in output.lower():
            # Device is asking for enable password — send it, then wait for prompt
            time.sleep(0.3)
            self.shell.send((enable_password or "") + "\n")
            output = self._read_until_prompt(initial_wait=1.5)

        if re.search(r"[\w\-]+#\s*$", output.rstrip()):
            self._current_mode = "enable"
            return output

        # If denied/failed, probe to see if we're actually in enable mode
        if "denied" in output.lower() or "failed" in output.lower():
            probe = self.send_command("show date", wait=2.0)
            if re.search(r"[\w\-]+#\s*$", probe.rstrip()):
                self._current_mode = "enable"
                return probe
            raise RuntimeError(f"Enable authentication failed: {output.strip()[:200]}")

        self._current_mode = "enable"
        return output

    def enter_config_mode(self) -> str:
        """Enter config mode via 'config terminal'. Returns output."""
        if self._current_mode == "config":
            return ""
        if self._current_mode != "enable":
            self.enter_enable_mode()

        output = self.send_command("config terminal", wait=2.0)
        self._current_mode = "config"
        return output

    def exit_config_mode(self) -> str:
        """Exit config mode back to enable mode."""
        if self._current_mode != "config":
            return ""
        output = self.send_command("exit", wait=1.0)
        self._current_mode = "enable"
        return output

    # ── Command execution ──────────────────────────────────────────────

    def execute_show_commands(self, commands: list[str]) -> list[dict[str, str]]:
        """Execute read-only show/list/display commands in enable mode."""
        results: list[dict[str, str]] = []
        self.enter_enable_mode()

        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            output = self.send_command(cmd, wait=3.0)
            status = "error" if self._has_cli_error(output) else "success"
            results.append({
                "command": cmd,
                "output": output.strip(),
                "status": status,
            })

        return results

    def execute_config_commands(self, commands: list[str]) -> list[dict[str, str]]:
        """Execute configuration commands in config mode. Enters and exits config mode automatically."""
        results: list[dict[str, str]] = []
        self.enter_enable_mode()
        self.enter_config_mode()

        for cmd in commands:
            cmd = cmd.strip()
            if not cmd:
                continue
            output = self.send_command(cmd, wait=3.0)
            status = "error" if self._has_cli_error(output) else "success"
            results.append({
                "command": cmd,
                "output": output.strip(),
                "status": status,
            })

        self.exit_config_mode()
        return results

    @staticmethod
    def _has_cli_error(output: str) -> bool:
        """Detect CLI error keywords in output (delegates to shared device_errors)."""
        if _has_cli_error_shared is not None:
            return _has_cli_error_shared(output)
        # Local fallback for standalone deployment
        text = output.strip().lower()
        if any(kw in text for kw in (
            "% invalid", "% error", "% unknown", "% unrecognized",
            "syntax error", "invalid input", "command not found",
            "failed to execute",
        )):
            return True
        for line in output.strip().splitlines():
            s = line.strip()
            if s == "^" or (len(s) <= 3 and "^" in s):
                return True
        return False
