"""通用执行工具：qa_bash + qa_exec.

Sandbox（

- ``cwd`` 由 ``_resolve_cwd_for_target()`` 按命令路径参数选最匹配的沙箱根
  （
  反向解析；InfoTest_Engine 没有用户 ``cd`` 概念，直接选目标所在根）
- 子进程 env 不透传 ``PYTHONPATH``，切断 ``import main.*`` 路径
- ``qa_bash`` 路径参数走 ``_resolve_inside_root`` 多根校验，拒绝出沙箱
- ``qa_bash`` 命令黑名单拦截网络外联 / 提权 / 破坏性文件操作
- 拒绝 shell 元字符（``|`` ``>`` ``<`` ``;`` ``&`` ``${`` ``$()`` 等）
- ``qa_exec`` 仅拒绝网络外联（socket / urllib / requests / http / ftp / smtp）
- 子进程超时（默认 30s，上限 120s）

安全设计：不做通用代码内容过滤，
安全靠沙箱隔离（cwd + env + shell=False + timeout）。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

from langchain_core.tools import tool

from main.ist_core.tools.deepagent._sandbox import (
    _default_cwd,
)
from main.ist_core.tools.deepagent.file_tools import (
    _AGENT_ROOT,
    _PROJECT_ROOT,
    _WORKSPACE_ROOT,
    _agent_roots,
    _resolve_inside_root,
    _resolve_writable_path,
)







_BASH_DENY_FIRST_TOKEN = frozenset({
    
    "curl", "wget", "ssh", "scp", "rsync", "ftp", "sftp", "nc", "ncat", "telnet",
    
    "sudo", "su", "doas",
    
    "rm", "rmdir", "mv", "ln",
    "dd", "tee",
    "chmod", "chown", "chgrp",
})




_BASH_WRITE_COMMANDS = frozenset({"cp"})


_DENIED_METACHARS = ("|", ">", "<", ";", "&", "`", "$(", "${", "&&", "||", "<<", ">>")


_PYTHON_RECOMMENDED_IMPORTS = frozenset({
    "json", "re", "csv", "collections", "pathlib", "itertools", "datetime",
    "math", "statistics", "functools", "string",
    "openpyxl", "pandas", "numpy",
    "yaml", "toml",
})




_PYTHON_NETWORK_DENY = (
    "import socket", "from socket", "socket.",
    "import urllib", "from urllib", "urllib.",
    "import requests", "from requests",
    "import http.client", "from http",
    "import ftplib", "from ftplib",
    "import smtplib", "from smtplib",
)

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120
_MAX_OUTPUT_BYTES = 256 * 1024





def _safe_env() -> dict[str, str]:
    """干净的子进程 ENV——只透传必要变量。

    显式不传 ``PYTHONPATH`` 与 ``PYTHONHOME``，切断 ``import main.*`` 的路径，
    强制子进程只能 import 三方包与标准库。

    额外注入 ``IST_AGENT_ROOT`` / ``IST_WORKSPACE_ROOT`` 绝对路径，让 qa_exec
    子进程能用 ``os.environ['IST_WORKSPACE_ROOT']`` 跨根读取（如读
    ``workspace/inputs/<.xlsx>``），不依赖固定 cwd。仅暴露这两根（不暴露
    ``_PROJECT_ROOT``），避免放大可读路径攻击面。延迟读 ``file_tools``
    当前值，配合测试 monkeypatch 沙箱根。
    """
    from main.ist_core.tools.deepagent import file_tools as _ft

    keep_keys = {
        "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
        "DASHSCOPE_API_KEY", "BAILIAN_API_KEY", "DEEPSEEK_API_KEY", "MINERU_TOKEN",
        "NO_PROGRESS",
        "TERM",
    }
    env = {k: v for k, v in os.environ.items() if k in keep_keys}
    env["IST_AGENT_ROOT"] = str(_ft._AGENT_ROOT)
    env["IST_WORKSPACE_ROOT"] = str(_ft._WORKSPACE_ROOT)
    return env

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
    return True, ""

def _looks_like_path(token: str) -> bool:
    """启发式判断 token 是否"像路径"——含 / / .. / ~ / 绝对路径，或在沙箱内/外存在。

    用来决定是否对该 token 走 _resolve_inside_root 校验。设计上偏严：
    宁可对 grep pattern 误检（被 _resolve_inside_root 当成不存在路径放行），
    也不漏检沙箱外路径。

    多根感知：遍历 ``_agent_roots()``，任一根存在该 token 即按路径处理。
    """
    if not token:
        return False
    if token.startswith(("/", "~")) or ".." in Path(token).parts:
        return True
    if "/" in token:
        return True
    
    try:
        for root in _agent_roots():
            if (root / token).exists():
                return True
        if (_PROJECT_ROOT / token).exists():
            return True
    except (OSError, ValueError):
        pass
    return False

def _split_cp_sources_dest(parts: list[str]) -> tuple[list[str], str | None]:
    """把 ``cp`` 命令切成 (sources, dest)。

    cp 语义：``cp [-flags] SRC... DST``——最后一个非 flag token 是目标。
    没有任何路径参数时返回 (parts[1:], None)，由调用方决定如何处理。
    """
    positional = [t for t in parts[1:] if not t.startswith("-")]
    if len(positional) < 2:
        return positional, None
    return positional[:-1], positional[-1]

def _validate_bash_paths(parts: list[str]) -> tuple[bool, str]:
    """对 bash 命令 ``parts[1:]`` 中的"像路径"参数走 _resolve_inside_root。

    任何不在 ``_agent_roots()`` 任一根内的路径参数都拒绝命令。

    特殊处理 ``cp``：源路径走 ``_resolve_inside_root``（沙箱内可读即可），
    目标路径走 ``_resolve_writable_path``（强制落到 workspace/outputs/）。
    """
    base = os.path.basename(parts[0]) if parts else ""

    if base in _BASH_WRITE_COMMANDS:
        sources, dest = _split_cp_sources_dest(parts)
        if dest is None:
            return False, f"{base!r} requires source and destination"
        for src in sources:
            if not _looks_like_path(src):
                continue
            try:
                _resolve_inside_root(src)
            except (PermissionError, ValueError) as exc:
                return False, f"source rejected: {src} ({exc})"
            except FileNotFoundError:
                continue
        
        
        
        dest_path = Path(dest)
        if not dest_path.is_absolute():
            head = dest_path.parts[0] if dest_path.parts else ""
            if head not in {"outputs", "workspace"}:
                return False, (
                    f"destination rejected: {dest} "
                    "(cp dst must start with 'outputs/' or 'workspace/outputs/')"
                )
        try:
            _resolve_writable_path(dest)
        except (PermissionError, ValueError) as exc:
            return False, f"destination rejected: {dest} ({exc})"
        return True, ""

    for token in parts[1:]:
        if token.startswith("-"):
            continue
        if not _looks_like_path(token):
            continue
        try:
            _resolve_inside_root(token)
        except (PermissionError, ValueError) as exc:
            return False, f"path argument rejected: {token} ({exc})"
        except FileNotFoundError:
            
            continue
    return True, ""

def _validate_python_code(code: str) -> tuple[bool, str]:
    code = code or ""
    if not code.strip():
        return False, "empty code"
    lower = code.replace(" ", "")
    for token in _PYTHON_NETWORK_DENY:
        if token.replace(" ", "") in lower:
            return False, f"network access not allowed: {token!r}"
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





@tool(parse_docstring=True)
def qa_exec(code: str, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Run a Python snippet inside the agent sandbox for structured analysis.

    Sandbox: cwd locked to ``knowledge/data/``; child process env strips
    ``PYTHONPATH`` so ``import main.*`` is unavailable; network access
    (socket/urllib/requests/http/ftp/smtp) is denied.

    To read across sandbox roots, use the env vars exposed in the child
    process: ``IST_AGENT_ROOT`` (knowledge/data) and ``IST_WORKSPACE_ROOT``
    (workspace). Example::

        import os, openpyxl
        path = os.path.join(os.environ['IST_WORKSPACE_ROOT'],
                            'inputs', 'case.xlsx')
        wb = openpyxl.load_workbook(path)

    Use this for parsing xlsx via openpyxl, counting rows with
    ``collections.Counter``, summarising JSON, running subprocess for
    file conversion, etc. To read an arbitrary file prefer
    ``qa_deepagent_read_file`` — this tool is for *analysis*, not
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
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(_default_cwd()),
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
    """Run a single shell command inside the agent sandbox.

    Sandbox: cwd locked to ``knowledge/data/``; path arguments validated via
    the same white-list as ``qa_deepagent_*`` tools; network commands, privilege
    escalation, and destructive file operations are denied; no shell metachars,
    no pipes, no redirects.

    Denied commands: curl/wget/ssh/scp/rsync/ftp/sftp/nc/ncat/telnet (network),
    sudo/su/doas (privilege), rm/rmdir/mv/ln/dd/tee/chmod/chown/chgrp
    (destructive — use write_file/edit_file tools instead).

    ``cp`` is allowed for staging files into ``workspace/outputs/``: the
    source path must live under any sandbox root (read), the destination
    must resolve under ``workspace/outputs/`` (same gates as write_file).

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

    
    
    
    
    
    
    
    
    
    
    base = os.path.basename(parts[0])
    if base in _BASH_WRITE_COMMANDS:
        sources, dest = _split_cp_sources_dest(parts)
        flags = [t for t in parts[1:] if t.startswith("-")]
        expanded_parts = [parts[0]] + flags
        for src in sources:
            if not _looks_like_path(src):
                expanded_parts.append(src)
                continue
            try:
                expanded_parts.append(str(_resolve_inside_root(src)))
            except (PermissionError, FileNotFoundError, ValueError):
                expanded_parts.append(src)
        try:
            expanded_parts.append(str(_resolve_writable_path(dest)))
        except (PermissionError, ValueError):
            expanded_parts.append(dest)
    else:
        expanded_parts = [parts[0]]
        for token in parts[1:]:
            if token.startswith("-"):
                expanded_parts.append(token)
                continue
            if not _looks_like_path(token):
                expanded_parts.append(token)
                continue
            try:
                absolute = _resolve_inside_root(token)
                expanded_parts.append(str(absolute))
            except (PermissionError, FileNotFoundError, ValueError):
                
                expanded_parts.append(token)

    cwd_path = _default_cwd()

    started = time.time()
    try:
        completed = subprocess.run(
            expanded_parts,
            cwd=str(cwd_path),
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
    "_BASH_DENY_FIRST_TOKEN",
]
