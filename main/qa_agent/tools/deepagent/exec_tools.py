"""通用执行工具：qa_bash + qa_exec.

Sandbox（与 ``file_tools.py`` 同一沙箱根 ``_AGENT_ROOT = knowledge/data/``）：
- ``cwd`` 锁到 ``_AGENT_ROOT``，agent 看不到仓库根
- 子进程 env 不透传 ``PYTHONPATH``，切断 ``import main.*`` 路径
- ``qa_bash`` 路径参数走 ``_resolve_inside_root`` 校验，拒绝出沙箱
- bash 首 token 必须在白名单（ls/cat/head/tail/wc/find/grep/awk/sed/sort/uniq/cut/...）
- 拒绝 shell 元字符（``|`` ``>`` ``<`` ``;`` ``&`` ``${`` ``$()`` 等）
- ``qa_exec`` 拒绝 ``subprocess`` / ``socket`` / ``urllib`` / 写文件等 denied tokens
- 子进程超时（默认 30s，上限 120s）

已知限制：
- ``qa_exec`` 不做 ast 静态分析。``Path("/绝对路径/main/...")`` / ``open("/...")``
  无法在 import 阶段拦住——agent 仍可能写绝对路径读取沙箱外文件。读文件应优先
  用 ``qa_deepagent_read_file``；``qa_exec`` 仅用于结构化分析（xlsx 解析、Counter 等）。
"""

from __future__ import annotations

import os
import shlex
import subprocess  # nosec B404 — 受控白名单 + shell=False
import sys
import time
from pathlib import Path
from typing import Iterable

from langchain_core.tools import tool

from main.qa_agent.tools.deepagent.file_tools import _AGENT_ROOT, _resolve_inside_root


# ---------------------------------------------------------------------------
# Project boundaries（与 file_tools.py 共用沙箱根）
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# bash 命令白名单——只读 / 文本处理 / 解析。任何写、删、网络、特权都不在表里。
# 已下线：python/python3（走 qa_exec），tee（写文件）。
_BASH_ALLOWED_COMMANDS = frozenset({
    "ls", "cat", "head", "tail", "wc", "find", "grep", "awk", "sed",
    "echo", "sort", "uniq", "cut", "tr", "diff",
    "which", "file", "basename", "dirname", "realpath",
    "jq", "yq",
})

# bash 命令显式黑名单（即使白名单匹配也拒绝）。
_BASH_DENY_FIRST_TOKEN = frozenset({
    "rm", "rmdir", "mv", "cp", "ln", "tar", "zip", "unzip",
    "curl", "wget", "ssh", "scp", "rsync", "ftp", "sftp", "nc", "ncat", "telnet",
    "sudo", "su", "doas",
    "chmod", "chown", "chgrp", "umask", "setfacl",
    "dd", "mkfifo", "mknod", "mount", "umount",
    "pip", "pip3", "pipenv", "poetry", "uv",
    "brew", "apt", "yum", "dnf",
    "git",
    "kill", "killall", "pkill",
    "shutdown", "reboot", "halt",
    # 下线的旧 bash 工具不再放行
    "tee", "python", "python3", "python3.11",
})

# 危险 shell 元字符——因 shell=False 不会被 shell 解释，但仍禁止以防被 split 出怪行为。
_DENIED_METACHARS = ("|", ">", "<", ";", "&", "`", "$(", "${", "&&", "||", "<<", ">>")

# qa_exec 仅推荐 import 的标准库 + 项目相关解析包（仅作 hint，不拒绝）
_PYTHON_RECOMMENDED_IMPORTS = frozenset({
    "json", "re", "csv", "collections", "pathlib", "itertools", "datetime",
    "math", "statistics", "functools", "string",
    "openpyxl", "pandas", "numpy",
    "yaml", "toml",
})

# qa_exec 代码中绝对禁止出现的 token（直接拒绝，不进 subprocess）
_PYTHON_DENIED_TOKENS = (
    "import os.system", "os.system", "subprocess",
    "__import__('os')", '__import__("os")',
    "compile(", "eval(", "exec(",  # 防止嵌套绕过
    "open('/etc/", 'open("/etc/',
    "import socket", "from socket", "socket.",
    "import urllib", "from urllib", "urllib.",
    "import requests", "from requests",
    "shutil.rmtree", "os.remove", "os.unlink",
    # 模块 introspection 防御：避免 LLM 通过 __file__ / pkgutil 反推沙箱外路径
    "__file__", "pkgutil.get_loader", "importlib.util.find_spec",
    # 防 editable package 绕过沙箱：禁止直接 import 平台包
    "import main", "from main",
)

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120
_MAX_OUTPUT_BYTES = 256 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_env() -> dict[str, str]:
    """干净的子进程 ENV——只透传必要变量。

    显式不传 ``PYTHONPATH`` 与 ``PYTHONHOME``，切断 ``import main.*`` 的路径，
    强制子进程只能 import 三方包与标准库。
    """
    keep_keys = {
        "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
        "DASHSCOPE_API_KEY", "BAILIAN_API_KEY", "MINERU_TOKEN",
        "QDRANT_HOST", "QDRANT_PORT",
        "QDRANT_COLLECTION_NAME", "QDRANT_QA_COLLECTION",
        "NO_PROGRESS",
        "TERM",
    }
    return {k: v for k, v in os.environ.items() if k in keep_keys}


def _truncate_output(text: str, *, label: str) -> str:
    if len(text) <= _MAX_OUTPUT_BYTES:
        return text
    truncated = text[: _MAX_OUTPUT_BYTES]
    return f"{truncated}\n... [{label} truncated: original {len(text)} bytes, kept {_MAX_OUTPUT_BYTES}]"


def _validate_bash_command(cmd: str) -> tuple[bool, str]:
    """命令名 / 元字符校验。返回 (是否允许, 拒绝原因)。"""
    cmd = (cmd or "").strip()
    if not cmd:
        return False, "empty command"
    for token in _DENIED_METACHARS:
        if token in cmd:
            return False, f"shell metachar not allowed: {token!r}"
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        return False, f"unparsable command: {exc}"
    if not parts:
        return False, "empty parsed command"
    first = parts[0]
    if first.startswith("=") or first.startswith("\\"):
        return False, f"command starts with suspicious prefix: {first!r}"
    base = os.path.basename(first)
    if base in _BASH_DENY_FIRST_TOKEN:
        return False, f"command is denied: {base!r}"
    if base not in _BASH_ALLOWED_COMMANDS:
        return False, f"command not in allowlist: {base!r}"
    return True, ""


def _looks_like_path(token: str) -> bool:
    """启发式判断 token 是否"像路径"——含 / / .. / ~ / 绝对路径，或在沙箱内/外存在。

    用来决定是否对该 token 走 _resolve_inside_root 校验。设计上偏严：
    宁可对 grep pattern 误检（被 _resolve_inside_root 当成不存在路径放行），
    也不漏检沙箱外路径。
    """
    if not token:
        return False
    if token.startswith(("/", "~")) or ".." in Path(token).parts:
        return True
    if "/" in token:  # 含路径分隔符
        return True
    # 不含分隔符的裸 token：如果在沙箱内或仓库根存在，也按路径处理
    try:
        if (_AGENT_ROOT / token).exists():
            return True
        if (_PROJECT_ROOT / token).exists():
            return True
    except (OSError, ValueError):
        pass
    return False


def _validate_bash_paths(parts: list[str]) -> tuple[bool, str]:
    """对 bash 命令 ``parts[1:]`` 中的"像路径"参数走 _resolve_inside_root。

    任何不在 ``_AGENT_ROOT`` 内的路径参数都拒绝命令。
    """
    for token in parts[1:]:
        if token.startswith("-"):
            continue  # flag
        if not _looks_like_path(token):
            continue
        try:
            _resolve_inside_root(token)
        except (PermissionError, ValueError) as exc:
            return False, f"path argument rejected: {token} ({exc})"
        except FileNotFoundError:
            # 文件不存在不拒绝——交给底层 shell 报 ENOENT，让 agent 看到准确错误
            continue
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
def qa_exec(code: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Run a Python snippet inside the agent sandbox for structured analysis.

    Sandbox: cwd locked to ``knowledge/data/``; child process env strips
    ``PYTHONPATH`` so ``import main.*`` is unavailable; denied tokens like
    ``subprocess`` / ``socket`` / ``urllib`` / ``__file__`` are rejected.

    Use this for parsing xlsx via openpyxl, counting rows with
    ``collections.Counter``, summarising JSON, etc. To read an arbitrary file
    prefer ``qa_deepagent_read_file`` — this tool is for *analysis*, not
    file fetching.

    Boundaries:
    - Read-only by convention. Do not write files or fetch network resources.
    - Timeout-protected (default 30s, max 120s).
    - Stdout/stderr capped at 256 KiB each; output beyond that is truncated.

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
            cwd=_AGENT_ROOT,
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
            f"=== qa_exec ===\n"
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
            f"=== qa_exec ===\n"
            f"returncode=-1 elapsed_ms={elapsed_ms}\n"
            f"--- error ---\nTimeout after {timeout}s"
        )
    except Exception as exc:  # noqa: BLE001
        return f"error: qa_exec subprocess failed: {exc}"


@tool(parse_docstring=True)
def qa_bash(command: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Run a single read-only shell command inside the agent sandbox.

    Sandbox: cwd locked to ``knowledge/data/``; path arguments validated via
    the same white-list as ``qa_deepagent_*`` tools; only read-only commands
    allowed; no shell metachars, no pipes, no redirects.

    Allowed commands:
    ls, cat, head, tail, wc, find, grep, awk, sed, echo, sort, uniq, cut,
    tr, diff, which, file, basename, dirname, realpath, jq, yq.

    Boundaries:
    - shell=False; the command is parsed via shlex and exec'd directly.
    - cwd locked to knowledge/data/.
    - Path arguments resolved against the sandbox; out-of-sandbox paths are
      rejected (including ``..``, ``~``, and absolute paths outside).
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
    ok, reason = _validate_bash_paths(parts)
    if not ok:
        return f"error: {reason}"

    started = time.time()
    try:
        completed = subprocess.run(  # nosec B603 — 已 validate + shell=False
            parts,
            cwd=_AGENT_ROOT,
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
            f"=== qa_bash ===\n"
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
            f"=== qa_bash ===\n"
            f"$ {command}\n"
            f"returncode=-1 elapsed_ms={elapsed_ms}\n"
            f"--- error ---\nTimeout after {timeout}s"
        )
    except Exception as exc:  # noqa: BLE001
        return f"error: qa_bash subprocess failed: {exc}"


# ---------------------------------------------------------------------------
# Public registry helper for downstream main_agent registration
# ---------------------------------------------------------------------------


def get_exec_tools() -> Iterable:
    """Return the tools list for ``build_default_registry()`` integration."""
    return [qa_exec, qa_bash]


__all__ = [
    "qa_exec",
    "qa_bash",
    "get_exec_tools",
    "_validate_bash_command",
    "_validate_bash_paths",
    "_validate_python_code",
    "_BASH_ALLOWED_COMMANDS",
    "_BASH_DENY_FIRST_TOKEN",
]
