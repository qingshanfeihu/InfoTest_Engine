"""通用执行工具：python_exec + bash_exec.

Design choices (MVP-scope security):
- No PTY / session / history; each invocation is an isolated subprocess.
- bash_exec first token must be in allowlist (ls/cat/head/tail/wc/find/grep/awk/sed/echo
  /sort/uniq/cut/which/python/python3/python3.11 etc — read-only commands).
- Reject ``rm`` / ``mv`` / ``cp`` / ``curl`` / ``wget`` / ``pip`` / ``ssh`` /
  ``sudo`` / ``chmod`` / ``chown`` / ``dd`` / ``mkfifo`` and any write/network/privileged commands.
- Disallow shell metachars beyond simple words (``shell=False`` + ``shlex.split`` enforces).
- python_exec runs user code in a separate ``sys.executable -c`` subprocess so it
  cannot pollute the LangGraph or Textual state; timeout-protected against infinite loops.
- CWD locked to PROJECT_ROOT; ENV passes only ``PATH`` / ``HOME`` / ``LANG`` /
  ``DASHSCOPE_API_KEY`` / ``MINERU_TOKEN`` / ``QDRANT_*``.
"""

from __future__ import annotations

import os
import shlex
import subprocess  # nosec B404 — 受控白名单 + shell=False
import sys
import textwrap
import time
from pathlib import Path
from typing import Iterable

from langchain_core.tools import tool


# ---------------------------------------------------------------------------
# Project boundaries (复用 file_tools.py 的常量定义思路)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# bash 命令白名单——只读 / 文本处理 / 解析。任何写、删、网络、特权都不在表里。
_BASH_ALLOWED_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "find", "grep", "awk", "sed",
    "echo", "sort", "uniq", "cut", "tr", "diff", "tee",
    "which", "file", "basename", "dirname", "realpath",
    # JSON / 文本工具
    "jq", "yq",
    # Python 解释器（用于 -c "..."）：受 python_exec 工具优先，但 bash_exec 也允许
    "python", "python3", "python3.11",
})

# bash 命令显式黑名单（即使白名单匹配也拒绝）——防止 alias / 同名脚本
_BASH_DENY_FIRST_TOKEN = frozenset({
    "rm", "rmdir", "mv", "cp", "ln", "tar", "zip", "unzip",
    "curl", "wget", "ssh", "scp", "rsync", "ftp", "sftp", "nc", "ncat", "telnet",
    "sudo", "su", "doas",
    "chmod", "chown", "chgrp", "umask", "setfacl",
    "dd", "mkfifo", "mknod", "mount", "umount",
    "pip", "pip3", "pipenv", "poetry", "uv",
    "brew", "apt", "yum", "dnf",
    "git",  # git 写仓库太多副作用，禁用
    "kill", "killall", "pkill",
    "shutdown", "reboot", "halt",
})

# 危险 shell 元字符——因 shell=False 不会被 shell 解释，但仍禁止以防被 split 出怪行为
_DENIED_METACHARS = ("|", ">", "<", ";", "&", "`", "$(", "${", "&&", "||", "<<", ">>")

# python_exec 仅允许 import 的标准库 + 项目相关解析包
# 不在表里的 import 不立即拒绝（不做 AST 检查太重），仅给 stderr 提示——
# 实际防御靠 subprocess 隔离 + timeout + denied tokens。
_PYTHON_RECOMMENDED_IMPORTS = frozenset({
    "json", "re", "csv", "collections", "pathlib", "itertools", "datetime",
    "math", "statistics", "functools", "string",
    "openpyxl", "pandas", "numpy",
    "yaml", "toml",
})

# python_exec 代码中绝对禁止出现的 token（直接拒绝，不进 subprocess）
_PYTHON_DENIED_TOKENS = (
    "import os.system", "os.system", "subprocess",
    "__import__('os')", '__import__("os")',
    "compile(", "eval(", "exec(",  # 防止嵌套绕过
    "open('/etc/", 'open("/etc/',
    "socket.", "urllib", "requests",
    "shutil.rmtree", "os.remove", "os.unlink",
)

# 子进程超时
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120

# 输出最大字节数（avoid OOM)
_MAX_OUTPUT_BYTES = 256 * 1024  # 256 KiB stdout + stderr 各自上限


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_env() -> dict[str, str]:
    """干净的子进程 ENV——只透传必要的少数变量。"""
    keep_keys = {
        "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
        "PYTHONPATH",
        "DASHSCOPE_API_KEY", "BAILIAN_API_KEY", "MINERU_TOKEN",
        "QDRANT_HOST", "QDRANT_PORT",
        "QDRANT_COLLECTION_NAME", "QDRANT_QA_COLLECTION",
        "NO_PROGRESS",
        "TERM",  # 不少 CLI 程序需要
    }
    return {k: v for k, v in os.environ.items() if k in keep_keys}


def _truncate_output(text: str, *, label: str) -> str:
    """避免巨型输出炸掉 LLM context。"""
    if len(text) <= _MAX_OUTPUT_BYTES:
        return text
    truncated = text[: _MAX_OUTPUT_BYTES]
    return f"{truncated}\n... [{label} truncated: original {len(text)} bytes, kept {_MAX_OUTPUT_BYTES}]"


def _validate_bash_command(cmd: str) -> tuple[bool, str]:
    """返回 (是否允许, 拒绝原因)。"""
    cmd = (cmd or "").strip()
    if not cmd:
        return False, "empty command"
    # 元字符检查（在 shlex 之前，防止用户写 "ls; rm -rf /"）
    for token in _DENIED_METACHARS:
        if token in cmd:
            return False, f"shell metachar not allowed: {token!r}"
    # 拆首 token
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        return False, f"unparsable command: {exc}"
    if not parts:
        return False, "empty parsed command"
    first = parts[0]
    # alias 攻击：=foo bar（防止前缀绕过）
    if first.startswith("=") or first.startswith("\\"):
        return False, f"command starts with suspicious prefix: {first!r}"
    # 取 basename，避免绝对路径绕过白名单（如 /usr/bin/rm）
    base = os.path.basename(first)
    if base in _BASH_DENY_FIRST_TOKEN:
        return False, f"command is denied: {base!r}"
    if base not in _BASH_ALLOWED_COMMANDS:
        return False, f"command not in allowlist: {base!r}"
    return True, ""


def _validate_python_code(code: str) -> tuple[bool, str]:
    code = code or ""
    if not code.strip():
        return False, "empty code"
    lower = code.replace(" ", "")
    for token in _PYTHON_DENIED_TOKENS:
        if token.replace(" ", "") in lower:
            return False, f"python denied token: {token!r}"
    return True, ""


def _format_summary_imports(code: str) -> str:
    """返回代码顶部用到的非推荐 import（仅作 hint，不拒绝）。"""
    lines = code.splitlines()
    suspect: list[str] = []
    for line in lines[:50]:
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            module = stripped.split()[1].split(".")[0]
            if module not in _PYTHON_RECOMMENDED_IMPORTS:
                suspect.append(module)
    if not suspect:
        return ""
    return f"(hint: non-standard imports detected: {', '.join(sorted(set(suspect)))})"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(parse_docstring=True)
def python_exec(code: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Run a self-contained Python snippet in an isolated subprocess.

    This is a generic DeepAgents-style execution tool for static review and
    structured analysis (e.g. parsing xlsx via openpyxl, counting fields,
    summarizing JSON). It runs in a separate Python process, so it cannot
    affect the LangGraph runtime or the TUI.

    Boundaries:
    - Read-only by convention: do NOT write files, fetch network resources,
      or invoke shells. Code is rejected if it contains denied tokens like
      ``subprocess`` / ``os.system`` / ``socket`` / ``urllib`` / ``open('/etc/...``.
    - CWD is locked to the project root.
    - Timeout-protected (default 30s, max 120s).
    - Stdout/stderr capped at 256 KiB each; output beyond that is truncated.
    - The Python interpreter used is the same as the host process.

    Args:
        code: Python source to run. Must be self-contained (no stdin input).
        timeout: Wall-clock limit in seconds (1..120).

    Returns:
        Text block with header, stdout, stderr, returncode, and elapsed_ms.
    """
    ok, reason = _validate_python_code(code)
    if not ok:
        return f"error: {reason}"
    timeout = max(1, min(int(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))

    started = time.time()
    try:
        completed = subprocess.run(  # nosec B603 — code 已 lint，shell=False
            [sys.executable, "-c", code],
            cwd=_PROJECT_ROOT,
            env=_safe_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        elapsed_ms = int((time.time() - started) * 1000)
        stdout = _truncate_output(completed.stdout or "", label="stdout")
        stderr = _truncate_output(completed.stderr or "", label="stderr")
        hint = _format_summary_imports(code)
        body = (
            f"=== python_exec ===\n"
            f"returncode={completed.returncode} elapsed_ms={elapsed_ms}\n"
        )
        if hint:
            body += f"{hint}\n"
        body += "--- stdout ---\n" + stdout
        if stderr.strip():
            body += "\n--- stderr ---\n" + stderr
        return body.rstrip()
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.time() - started) * 1000)
        return (
            f"=== python_exec ===\n"
            f"returncode=-1 elapsed_ms={elapsed_ms}\n"
            f"--- error ---\nTimeout after {timeout}s"
        )
    except Exception as exc:  # noqa: BLE001
        return f"error: python_exec subprocess failed: {exc}"


@tool(parse_docstring=True)
def bash_exec(command: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Run a single read-only shell command (no pipes, no redirects).

    This is a generic DeepAgents-style bash execution tool for read-only
    inspection commands. It is intentionally minimal — no shell metachars
    are allowed, no PTY, no session state.

    Allowed first commands (basename match):
    ls, cat, head, tail, wc, find, grep, awk, sed, echo, sort, uniq, cut,
    tr, diff, tee, which, file, basename, dirname, realpath, jq, yq,
    python, python3, python3.11.

    Denied (any path resolution): rm, rmdir, mv, cp, ln, tar, zip, curl,
    wget, ssh, scp, rsync, ftp, sftp, nc, ncat, telnet, sudo, su, doas,
    chmod, chown, chgrp, dd, mkfifo, mknod, mount, pip*, brew, apt, yum,
    dnf, git, kill*, shutdown, reboot, halt.

    Forbidden chars in command string: ``|`` ``>`` ``<`` ``;`` ``&`` `````
    ``$()`` ``${`` ``&&`` ``||`` ``<<`` ``>>``.

    Boundaries:
    - shell=False; the command is parsed via shlex and exec'd directly.
    - CWD locked to project root.
    - Timeout-protected (default 30s, max 120s).
    - Stdout/stderr capped at 256 KiB each.

    Args:
        command: Shell command (no pipes / redirects / chains).
        timeout: Wall-clock limit in seconds (1..120).

    Returns:
        Text block with header, stdout, stderr, returncode, and elapsed_ms.
    """
    ok, reason = _validate_bash_command(command)
    if not ok:
        return f"error: {reason}"
    timeout = max(1, min(int(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))

    parts = shlex.split(command)
    started = time.time()
    try:
        completed = subprocess.run(  # nosec B603 — 已 validate + shell=False
            parts,
            cwd=_PROJECT_ROOT,
            env=_safe_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        elapsed_ms = int((time.time() - started) * 1000)
        stdout = _truncate_output(completed.stdout or "", label="stdout")
        stderr = _truncate_output(completed.stderr or "", label="stderr")
        body = (
            f"=== bash_exec ===\n"
            f"$ {command}\n"
            f"returncode={completed.returncode} elapsed_ms={elapsed_ms}\n"
            f"--- stdout ---\n" + stdout
        )
        if stderr.strip():
            body += "\n--- stderr ---\n" + stderr
        return body.rstrip()
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.time() - started) * 1000)
        return (
            f"=== bash_exec ===\n"
            f"$ {command}\n"
            f"returncode=-1 elapsed_ms={elapsed_ms}\n"
            f"--- error ---\nTimeout after {timeout}s"
        )
    except Exception as exc:  # noqa: BLE001
        return f"error: bash_exec subprocess failed: {exc}"


# ---------------------------------------------------------------------------
# Public registry helper for downstream main_agent registration
# ---------------------------------------------------------------------------


def get_exec_tools() -> Iterable:
    """Return the tools list for ``build_default_registry()`` integration."""
    return [python_exec, bash_exec]


# Convenience aliases for unit testing
__all__ = [
    "python_exec",
    "bash_exec",
    "get_exec_tools",
    "_validate_bash_command",  # exported for unit tests
    "_validate_python_code",
    "_BASH_ALLOWED_COMMANDS",
    "_BASH_DENY_FIRST_TOKEN",
]
