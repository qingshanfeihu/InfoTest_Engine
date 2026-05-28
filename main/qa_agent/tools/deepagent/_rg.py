"""ripgrep execution helpers for read-only DeepAgent filesystem tools."""

from __future__ import annotations

import platform
import shutil
import subprocess  # nosec B404 - executed with fixed argv and shell=False
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_MAX_OUTPUT_BYTES = 20_000_000


@dataclass(frozen=True)
class RipgrepResult:
    lines: list[str]
    stderr: str = ""
    returncode: int = 0
    timed_out: bool = False
    truncated: bool = False
    unavailable: bool = False

    @property
    def ok(self) -> bool:
        return not self.timed_out and not self.unavailable and self.returncode in {0, 1}


def _default_timeout_seconds() -> int:
    release = platform.release().lower()
    return 60 if "microsoft" in release or "wsl" in release else 20


def _decode(data: str | bytes | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def _split_output(stdout: str, *, drop_last: bool) -> list[str]:
    lines = stdout.splitlines()
    if drop_last and lines:
        return lines[:-1]
    return lines


def _has_eagain(stderr: str) -> bool:
    return "os error 11" in stderr or "Resource temporarily unavailable" in stderr


def run_ripgrep(
    args: Sequence[str],
    target: str,
    *,
    cwd: Path,
    timeout_seconds: int | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    _single_thread: bool = False,
) -> RipgrepResult:
    """Run ripgrep and return line-split stdout with structured error semantics."""
    rg = shutil.which("rg")
    if not rg:
        return RipgrepResult(lines=[], unavailable=True, returncode=127)

    timeout_seconds = timeout_seconds or _default_timeout_seconds()
    command = [rg, "--no-config"]
    if _single_thread:
        command.extend(["-j", "1"])
    command.extend(args)
    command.append(target)

    try:
        completed = subprocess.run(  # nosec B603 - argv is constructed, shell=False
            command,
            cwd=str(cwd),
            capture_output=True,
            text=False,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _decode(exc.stdout)
        stderr = _decode(exc.stderr)
        truncated = len(stdout.encode("utf-8", errors="replace")) > max_output_bytes
        if truncated:
            stdout = stdout.encode("utf-8", errors="replace")[:max_output_bytes].decode("utf-8", errors="replace")
        return RipgrepResult(
            lines=_split_output(stdout, drop_last=True),
            stderr=stderr,
            returncode=-1,
            timed_out=True,
            truncated=truncated,
        )
    except (FileNotFoundError, PermissionError) as exc:
        return RipgrepResult(lines=[], stderr=str(exc), unavailable=True, returncode=127)

    stdout = _decode(completed.stdout)
    stderr = _decode(completed.stderr)

    if completed.returncode not in {0, 1} and not _single_thread and _has_eagain(stderr):
        return run_ripgrep(
            args,
            target,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            _single_thread=True,
        )

    truncated = len(completed.stdout or b"") > max_output_bytes
    if truncated:
        stdout = (completed.stdout or b"")[:max_output_bytes].decode("utf-8", errors="replace")

    return RipgrepResult(
        lines=_split_output(stdout, drop_last=truncated),
        stderr=stderr,
        returncode=int(completed.returncode),
        truncated=truncated,
    )
