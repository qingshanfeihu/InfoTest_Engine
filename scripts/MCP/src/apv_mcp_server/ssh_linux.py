"""Linux SSH client via paramiko.

Provides a simple, robust SSH client for executing commands on generic Linux servers.
Uses paramiko's exec_command for one-shot execution with proper exit code capture.
"""

from __future__ import annotations

import logging
from typing import Optional

import paramiko

logger = logging.getLogger(__name__)


class LinuxSSHClient:
    """SSH client for generic Linux servers using paramiko exec_command."""

    def __init__(
        self,
        host: str,
        username: str = "root",
        password: str = "click1",
        port: int = 22,
        timeout: int = 15,
        command_timeout: int = 30,
        key_filename: Optional[str] = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.command_timeout = command_timeout
        self.key_filename = key_filename
        self.ssh: Optional[paramiko.SSHClient] = None

    def connect(self) -> str:
        """Establish SSH connection. Returns server banner/version info."""
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": self.host,
            "port": self.port,
            "username": self.username,
            "timeout": self.timeout,
            "look_for_keys": False,
            "allow_agent": False,
        }

        if self.key_filename:
            connect_kwargs["key_filename"] = self.key_filename
        else:
            connect_kwargs["password"] = self.password

        self.ssh.connect(**connect_kwargs)

        # Get server banner
        transport = self.ssh.get_transport()
        if transport:
            remote_version = transport.remote_version or ""
        else:
            remote_version = ""

        return f"Connected to {self.host}:{self.port} — SSH {remote_version}"

    def disconnect(self) -> None:
        """Disconnect SSH session."""
        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
            self.ssh = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    def execute(self, command: str) -> dict:
        """Execute a single command and return structured result.

        Returns:
            dict with keys: command, stdout, stderr, exit_code, status
        """
        if not self.ssh:
            raise RuntimeError("SSH not connected. Call connect() first.")

        try:
            transport = self.ssh.get_transport()
            if transport is None or not transport.is_active():
                raise RuntimeError("SSH transport is not active")

            chan = transport.open_session(timeout=self.command_timeout)
            chan.settimeout(self.command_timeout)
            chan.exec_command(command)

            stdout = self._read_channel(chan.recv)
            stderr = self._read_channel(chan.recv_stderr)
            exit_code = chan.recv_exit_status()

            chan.close()

            status = "success" if exit_code == 0 else "error"

            return {
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "status": status,
            }

        except Exception as exc:
            return {
                "command": command,
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "status": "error",
            }

    @staticmethod
    def _read_channel(read_func, chunk_size: int = 65535) -> str:
        """Read all data from a channel callback."""
        parts = []
        while True:
            try:
                chunk = read_func(chunk_size)
                if not chunk:
                    break
                parts.append(chunk.decode("utf-8", errors="replace"))
            except Exception:
                break
        return "".join(parts)


def execute_command(
    host: str,
    command: str,
    username: str = "root",
    password: str = "click1",
    port: int = 22,
    timeout: int = 15,
    command_timeout: int = 30,
    key_filename: Optional[str] = None,
) -> dict:
    """Convenience function: connect, execute one command, disconnect.

    Returns:
        dict with keys: command, stdout, stderr, exit_code, status
    """
    client = LinuxSSHClient(
        host=host,
        username=username,
        password=password,
        port=port,
        timeout=timeout,
        command_timeout=command_timeout,
        key_filename=key_filename,
    )
    try:
        client.connect()
        return client.execute(command)
    finally:
        client.disconnect()
