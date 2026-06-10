"""APV device Telnet client (raw socket implementation).

Connects to APV/InfosecOS devices over Telnet, handles login, enable mode,
config mode, and executes CLI commands.

Flow: Connect → Login (user/pass) → enable → config terminal → execute → exit

Uses raw sockets with basic Telnet IAC handling (telnetlib was removed in Python 3.13).
"""

from __future__ import annotations

import re
import select
import socket
import time
from typing import Optional

# Telnet protocol constants
IAC  = 255  # Interpret As Command
DONT = 254
DO   = 253
WONT = 252
WILL = 251
SB   = 250  # Subnegotiation Begin
SE   = 240  # Subnegotiation End


class APVTelnetClient:
    """Telnet interactive client for APV/InfosecOS load balancers.

    Implements a minimal Telnet client using raw sockets. Handles:
    - Basic IAC negotiation (refuses all options)
    - Login with username/password
    - Enable mode with optional enable password
    - Config mode via "config terminal"
    - --More-- pagination (sends space to continue)
    - CLI prompt detection
    """

    # Prompt patterns for APV CLI modes
    PROMPT_PATTERNS = [
        r"[\w\-]+>",              # user mode: APV>
        r"[\w\-]+#",              # enable mode: APV#
        r"[\w\-]+\([^\)]+\)#",    # config mode: APV(config)#
    ]
    MORE_PATTERN = r"--More--"

    # Patterns that indicate the device is waiting for password input
    _PASSWORD_PATTERNS = [
        r"[Pp]assword:\s*$",
        r"[Ee]nable password:\s*$",
    ]

    # Login prompt patterns (bytes)
    LOGIN_PROMPTS = [b"login:", b"Login:", b"Username:", b"username:"]
    PASSWORD_PROMPTS = [b"Password:", b"password:"]

    def __init__(
        self,
        host: str,
        username: str = "admin",
        password: str = "admin",
        port: int = 23,
        timeout: int = 15,
        command_timeout: int = 30,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.command_timeout = command_timeout
        self._sock: Optional[socket.socket] = None
        self._current_mode: str = "user"
        self._buffer: bytes = b""

    # ── Connection management ──────────────────────────────────────────

    def connect(self) -> str:
        """Establish Telnet connection and log in. Returns login banner + initial output."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        self._buffer = b""

        # Wait for login prompt and handle IAC negotiation
        banner = self._read_until_prompt_or(
            extra_patterns=self.LOGIN_PROMPTS + self.PASSWORD_PROMPTS,
            timeout=self.timeout,
        )

        # Send username if we see a login prompt
        if any(p in banner for p in self.LOGIN_PROMPTS):
            self._send_line(self.username)
            # Wait for password prompt
            self._read_until(self.PASSWORD_PROMPTS, timeout=self.timeout)

        # Send password
        self._send_line(self.password)

        # Wait for initial prompt after login
        output = self._read_until_prompt(initial_wait=2.0)
        self._current_mode = "user"
        return output if isinstance(output, str) else output.decode("utf-8", errors="replace")

    def disconnect(self) -> None:
        """Disconnect Telnet session cleanly."""
        if self._sock:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._buffer = b""
        self._current_mode = "user"

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    # ── Low-level I/O ──────────────────────────────────────────────────

    def _send_line(self, text: str) -> None:
        """Send a line of text followed by CR+NUL (Telnet newline)."""
        data = text.encode("ascii") + b"\r\0"
        self._send_raw(data)

    def _send_raw(self, data: bytes) -> None:
        """Send raw bytes, escaping IAC bytes."""
        # Escape any IAC (0xFF) in the data
        escaped = data.replace(b"\xff", b"\xff\xff")
        if self._sock:
            self._sock.sendall(escaped)

    def _recv(self, timeout: float) -> bytes:
        """Receive available data with a per-read timeout. Handles IAC negotiation."""
        if not self._sock:
            return b""

        try:
            ready, _, _ = select.select([self._sock], [], [], timeout)
            if not ready:
                return b""
            data = self._sock.recv(65535)
            if not data:
                raise EOFError("Telnet connection closed by remote host")
            # Process and filter out IAC sequences
            return self._process_iac(data)
        except socket.timeout:
            return b""
        except (OSError, EOFError):
            return b""

    def _process_iac(self, data: bytes) -> bytes:
        """Process Telnet IAC commands in received data. Returns clean text bytes.

        Handles DO/DONT/WILL/WONT negotiation by refusing all options,
        and strips subnegotiation sequences.
        """
        result = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b == IAC:
                if i + 1 >= len(data):
                    # Incomplete IAC — store in buffer for next read
                    # (rare edge case, just skip for now)
                    break
                cmd = data[i + 1]
                if cmd == IAC:
                    # Escaped IAC byte (IAC IAC → literal 0xFF)
                    result.append(IAC)
                    i += 2
                elif cmd in (DO, DONT, WILL, WONT):
                    # Option negotiation: 3-byte sequence IAC <cmd> <option>
                    if cmd == DO:
                        # Refuse: send WONT
                        if i + 2 < len(data):
                            self._send_raw(bytes([IAC, WONT, data[i + 2]]))
                    elif cmd == WILL:
                        # Refuse: send DONT
                        if i + 2 < len(data):
                            self._send_raw(bytes([IAC, DONT, data[i + 2]]))
                    i += 3
                elif cmd == SB:
                    # Subnegotiation: skip until IAC SE
                    i += 2
                    while i < len(data):
                        if data[i] == IAC and i + 1 < len(data) and data[i + 1] == SE:
                            i += 2
                            break
                        i += 1
                else:
                    # Other IAC commands: skip 2 bytes
                    i += 2
            else:
                result.append(b)
                i += 1
        return bytes(result)

    def _read_until(self, expected: list[bytes], timeout: float = 0) -> bytes:
        """Read until any expected pattern is found in the buffer."""
        if timeout <= 0:
            timeout = self.command_timeout

        start = time.time()
        while time.time() - start < timeout:
            # Check if we already have a match in buffer
            for pat in expected:
                if pat in self._buffer:
                    return self._buffer

            chunk = self._recv(0.3)
            if chunk:
                self._buffer += chunk
            # Also check for CR/LF stripped patterns
            for pat in expected:
                if pat in self._buffer:
                    return self._buffer

        return self._buffer

    def _read_until_prompt_or(
        self,
        extra_patterns: Optional[list] = None,
        timeout: float = 0,
    ) -> bytes:
        """Read until a CLI prompt OR one of the extra patterns is detected."""
        if timeout <= 0:
            timeout = self.command_timeout
        if extra_patterns is None:
            extra_patterns = []

        start = time.time()
        while time.time() - start < timeout:
            # Check buffer for matches
            text = self._buffer.decode("utf-8", errors="replace")

            # Check extra patterns
            for pat in extra_patterns:
                if pat in self._buffer:
                    return self._buffer

            # Check for CLI prompt
            stripped = text.rstrip()
            if any(re.search(p + r"\s*$", stripped) for p in self.PROMPT_PATTERNS):
                return self._buffer

            # Check --More--
            if re.search(self.MORE_PATTERN, text):
                # Remove --More-- from buffer, send space
                self._buffer = re.sub(
                    rb"\s*--More--\s*", b"",
                    self._buffer,
                    flags=re.IGNORECASE,
                )
                self._send_raw(b" ")
                time.sleep(0.3)
                continue

            chunk = self._recv(0.3)
            if chunk:
                self._buffer += chunk

        return self._buffer

    def _read_until_prompt(
        self,
        initial_wait: float = 1.0,
        max_wait: float = 0,
        extra_patterns: Optional[list] = None,
    ) -> str:
        """Read until CLI prompt detected or timeout. Handles --More-- pagination.

        Args:
            extra_patterns: additional regex patterns to match (e.g. password prompts).

        Returns decoded string output.
        """
        if max_wait <= 0:
            max_wait = self.command_timeout

        start = time.time()
        time.sleep(initial_wait)

        while time.time() - start < max_wait:
            chunk = self._recv(0.3)
            if chunk:
                self._buffer += chunk

            text = self._buffer.decode("utf-8", errors="replace")

            # Handle --More-- pagination
            if re.search(self.MORE_PATTERN, text):
                self._buffer = re.sub(
                    rb"\s*--More--\s*", b"",
                    self._buffer,
                    flags=re.IGNORECASE,
                )
                self._send_raw(b" ")
                time.sleep(0.3)
                continue

            # Check extra patterns (password prompts, etc.)
            if extra_patterns:
                stripped = text.rstrip()
                if any(re.search(p, stripped) for p in extra_patterns):
                    break

            # Check for CLI prompt
            stripped = text.rstrip()
            if any(re.search(p + r"\s*$", stripped) for p in self.PROMPT_PATTERNS):
                break

        return self._buffer.decode("utf-8", errors="replace")

    def send_command(self, command: str, wait: float = 2.0) -> str:
        """Send a single command and return captured output (without prompt/echo)."""
        if not self._sock:
            raise RuntimeError("Telnet not connected. Call connect() first.")

        # Drain buffer
        self._buffer = b""
        # Drain socket
        try:
            self._sock.setblocking(False)
            while True:
                chunk = self._sock.recv(65535)
                if not chunk:
                    break
        except Exception:
            pass
        finally:
            if self._sock:
                self._sock.setblocking(True)

        self._send_line(command)
        raw = self._read_until_prompt(initial_wait=wait)

        lines = raw.splitlines()
        # Remove echoed command line if present
        if lines and command.strip() in lines[0]:
            lines = lines[1:]
        return "\n".join(lines)

    # ── Mode switching ─────────────────────────────────────────────────

    def enter_enable_mode(self, enable_password: str = "") -> str:
        """Enter enable (privileged) mode."""
        if self._current_mode in ("enable", "config"):
            return ""

        if not self._sock:
            raise RuntimeError("Telnet not connected. Call connect() first.")

        # Drain buffer
        self._buffer = b""

        # Send "enable" and wait for either a password prompt or a CLI prompt
        self._send_line("enable")
        output = self._read_until_prompt(
            initial_wait=1.5,
            extra_patterns=self._PASSWORD_PATTERNS,
        )

        if "assword" in output.lower():
            # Device is asking for enable password — send it, then wait for prompt
            time.sleep(0.3)
            self._send_line(enable_password or "")
            output = self._read_until_prompt(initial_wait=1.5)

        if re.search(r"[\w\-]+#\s*$", output.rstrip()):
            self._current_mode = "enable"
            return output

        if "denied" in output.lower() or "failed" in output.lower():
            probe = self.send_command("show date", wait=2.0)
            if re.search(r"[\w\-]+#\s*$", probe.rstrip()):
                self._current_mode = "enable"
                return probe
            raise RuntimeError(f"Enable authentication failed: {output.strip()[:200]}")

        self._current_mode = "enable"
        return output

    def enter_config_mode(self) -> str:
        """Enter config mode via 'config terminal'."""
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
        """Execute read-only show commands in enable mode."""
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
        """Execute configuration commands in config mode."""
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
        """Detect CLI error keywords in output."""
        text = output.strip().lower()
        if any(kw in text for kw in (
            "% invalid", "% error", "% unknown", "% unrecognized",
            "syntax error", "invalid input", "command not found",
        )):
            return True
        for line in output.strip().splitlines():
            s = line.strip()
            if s == "^" or (len(s) <= 3 and "^" in s):
                return True
        return False
