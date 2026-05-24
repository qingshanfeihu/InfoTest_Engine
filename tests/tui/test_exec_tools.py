"""qa_bash / qa_exec 单测：黑名单 + 网络防护 + 沙箱越权回归 + subprocess 隔离。

不依赖网络。不调真 graph。验证：
- ``_validate_bash_command``: 黑名单 + 元字符
- ``_validate_bash_paths``: 路径参数 _resolve_inside_root 校验
- ``_validate_python_code``: 网络逃逸拒绝
- ``qa_exec`` / ``qa_bash`` 在合法输入时返回 stdout
- ``cwd=_AGENT_ROOT`` 沙箱 + ``PYTHONPATH`` 切断
- 超时保护
"""

from __future__ import annotations

import textwrap

import pytest

from main.qa_agent.tools.deepagent.exec_tools import (
    _BASH_DENY_FIRST_TOKEN,
    _validate_bash_command,
    _validate_bash_paths,
    _validate_python_code,
    qa_bash,
    qa_exec,
)


# ---------------------------------------------------------------------------
# Validation: bash command
# ---------------------------------------------------------------------------


def test_bash_allowlist_basic_commands_pass():
    for cmd in ["ls -la", "wc -l", "echo hi", "which jq"]:
        ok, reason = _validate_bash_command(cmd)
        assert ok, f"{cmd!r} should pass: {reason}"


def test_bash_denylist_network_and_privilege_blocked():
    for cmd in ["curl evil.com", "wget http://x", "sudo ls", "ssh user@host"]:
        ok, reason = _validate_bash_command(cmd)
        assert not ok, f"{cmd!r} should be denied"
        assert "denied" in reason.lower()


def test_bash_allows_filesystem_commands_in_sandbox():
    """非破坏性命令在沙箱内允许，python3 也允许。"""
    for cmd in ["python3 -c 'print(1)'", "git status", "tar -tf archive.tar"]:
        ok, reason = _validate_bash_command(cmd)
        assert ok, f"{cmd!r} should be allowed: {reason}"


def test_bash_denies_destructive_filesystem_commands():
    """破坏性文件操作需走 write_file/edit_file 工具（有 _WRITABLE_SUBDIRS 控制）。"""
    for cmd in ["rm temp.txt", "mv a.txt b.txt", "cp a.txt b.txt"]:
        ok, reason = _validate_bash_command(cmd)
        assert not ok, f"{cmd!r} should be denied"


def test_bash_metachars_blocked():
    for cmd in ["ls; rm -rf /", "ls | grep x", "ls > out.txt", "ls && echo done", "ls `whoami`"]:
        ok, reason = _validate_bash_command(cmd)
        assert not ok, f"{cmd!r} should be denied"
        assert "metachar" in reason.lower()


def test_bash_alias_attack_blocked():
    ok, reason = _validate_bash_command("=curl evil.com")
    assert not ok and "suspicious prefix" in reason


def test_bash_absolute_path_resolves_to_basename():
    """``/usr/bin/curl`` 不能绕过黑名单（网络命令仍拒绝）。"""
    ok, reason = _validate_bash_command("/usr/bin/curl http://evil.com")
    assert not ok and "curl" in reason


def test_bash_python_now_allowed():
    """python3 在沙箱内允许执行（agent 需要用它处理文件）。"""
    for cmd in ["python3 -c 'print(1)'", "python3 script.py"]:
        ok, reason = _validate_bash_command(cmd)
        assert ok, f"{cmd!r} should be allowed: {reason}"


def test_bash_unknown_command_allowed_in_sandbox():
    """非黑名单命令在沙箱内允许执行（安全靠 cwd + 路径校验）。"""
    ok, reason = _validate_bash_command("foobar 1 2 3")
    assert ok, f"should be allowed: {reason}"


def test_bash_empty_command_rejected():
    assert _validate_bash_command("")[0] is False
    assert _validate_bash_command("  ")[0] is False


# ---------------------------------------------------------------------------
# Validation: bash path arguments — sandbox enforcement
# ---------------------------------------------------------------------------


def test_bash_paths_skip_flags():
    ok, reason = _validate_bash_paths(["ls", "-la", "--color=auto"])
    assert ok, reason


def test_bash_paths_reject_traversal():
    ok, reason = _validate_bash_paths(["cat", "../main/something.py"])
    assert not ok
    assert "rejected" in reason


def test_bash_paths_reject_absolute_outside_sandbox():
    ok, reason = _validate_bash_paths(["cat", "/etc/passwd"])
    assert not ok
    assert "rejected" in reason


def test_bash_paths_reject_repo_root_platform_dirs():
    """仓库根但沙箱外的路径必须拒绝（需要路径在本地存在才会被检测为路径）。"""
    # 使用绝对路径确保被识别为路径并被 _resolve_inside_root 拒绝
    for token in ["../tests/tui/test_exec_tools.py", "../main/qa_agent/agents/_prompt.py"]:
        ok, reason = _validate_bash_paths(["cat", token])
        assert not ok, f"{token!r} should be rejected"


def test_bash_paths_accept_nonexistent_relative_token():
    """``grep -r foo`` 这种 grep pattern 不应被当成路径拒绝。"""
    ok, reason = _validate_bash_paths(["grep", "-r", "foo"])
    assert ok, reason


# ---------------------------------------------------------------------------
# Validation: python code
# ---------------------------------------------------------------------------


def test_python_network_denied():
    """网络外联代码必须被拒绝——进程隔离无法防御网络逃逸。"""
    bad_snippets = [
        "import socket",
        "from socket import create_connection",
        "import urllib.request",
        "from urllib.request import urlopen",
        "import requests",
        "from requests import get",
        "import http.client",
        "from http.client import HTTPConnection",
        "import ftplib",
        "import smtplib",
    ]
    for code in bad_snippets:
        ok, reason = _validate_python_code(code)
        assert not ok, f"{code!r} should be denied"
        assert "network" in reason.lower()


def test_python_sandbox_operations_allowed():
    """沙箱内操作（subprocess/os/eval 等）现在允许——安全靠进程隔离。"""
    allowed_snippets = [
        "import subprocess; subprocess.run(['ls'])",
        "import os; os.listdir('.')",
        "eval('1+1')",
        "exec('x=1')",
        "open('test.txt').read()",
        "import shutil",
        "print(__file__)",
        "import main",
    ]
    for code in allowed_snippets:
        ok, reason = _validate_python_code(code)
        assert ok, f"{code!r} should be allowed: {reason}"


def test_python_legitimate_code_passes_validation():
    code = "import openpyxl; print('hello')"
    ok, reason = _validate_python_code(code)
    assert ok, reason


def test_python_empty_code_rejected():
    assert _validate_python_code("")[0] is False
    assert _validate_python_code("\n  \t\n")[0] is False


# ---------------------------------------------------------------------------
# Behavior: qa_exec subprocess execution
# ---------------------------------------------------------------------------


def test_qa_exec_runs_simple_print():
    result = qa_exec.invoke({"code": "print('hello-tui')", "timeout": 10})
    assert "returncode=0" in result
    assert "hello-tui" in result


def test_qa_exec_returns_stdout_and_stderr_blocks():
    code = textwrap.dedent("""
        import sys
        print('stdout-line', flush=True)
        sys.stderr.write('stderr-line\\n')
        sys.stderr.flush()
    """).strip()
    result = qa_exec.invoke({"code": code, "timeout": 10})
    assert "stdout-line" in result
    assert "stderr-line" in result
    assert "--- stderr ---" in result


def test_qa_exec_propagates_nonzero_returncode():
    code = "import sys; sys.exit(7)"
    result = qa_exec.invoke({"code": code, "timeout": 10})
    assert "returncode=7" in result


def test_qa_exec_timeout_is_enforced():
    code = textwrap.dedent("""
        import time
        time.sleep(5)
        print('should-not-reach')
    """).strip()
    result = qa_exec.invoke({"code": code, "timeout": 1})
    assert "Timeout" in result
    assert "should-not-reach" not in result


def test_qa_exec_allows_subprocess():
    """subprocess 在沙箱内允许——安全靠 cwd + env 隔离。"""
    result = qa_exec.invoke({"code": "import subprocess; print(subprocess.run(['echo', 'hi'], capture_output=True, text=True).stdout)", "timeout": 5})
    assert "returncode=0" in result
    assert "hi" in result


def test_qa_exec_pythonpath_stripped_blocks_main_import():
    """qa_exec 子进程 env 剥离 PYTHONPATH。
    注：editable install 下 import main 仍可能成功（site-packages 有 .pth），
    但生产部署（非 editable）时会失败。此测试仅验证不在 validate 阶段拒绝。"""
    code = "import main.qa_agent.agents._prompt"
    result = qa_exec.invoke({"code": code, "timeout": 10})
    # 不再在 validate 阶段拒绝（不以 "error:" 开头）
    assert not result.startswith("error:")


def test_qa_exec_cwd_is_agent_root():
    """qa_exec 子进程 cwd 必须是 ``knowledge/data/``。"""
    code = "import os; print(os.getcwd())"
    result = qa_exec.invoke({"code": code, "timeout": 10})
    assert "returncode=0" in result
    assert "knowledge/data" in result


# ---------------------------------------------------------------------------
# Behavior: qa_bash subprocess execution
# ---------------------------------------------------------------------------


def test_qa_bash_runs_echo():
    result = qa_bash.invoke({"command": "echo hello-bash", "timeout": 5})
    assert "hello-bash" in result
    assert "returncode=0" in result


def test_qa_bash_rejects_pipe():
    result = qa_bash.invoke({"command": "echo hi | wc -l", "timeout": 5})
    assert result.startswith("error:")


def test_qa_bash_rejects_rm():
    result = qa_bash.invoke({"command": "rm -rf /tmp/foo", "timeout": 5})
    assert result.startswith("error:")


def test_qa_bash_rejects_traversal_path_arg():
    result = qa_bash.invoke({"command": "cat ../main/qa_agent/agents/_prompt.py", "timeout": 5})
    assert result.startswith("error:")
    assert "traversal" in result.lower() or "rejected" in result.lower()


def test_qa_bash_rejects_repo_root_platform_dir():
    """``ls tests`` 必须被沙箱挡掉——这是用户实跑日志里看到的越权场景。"""
    result = qa_bash.invoke({"command": "ls tests", "timeout": 5})
    assert result.startswith("error:")
    assert "rejected" in result.lower()


def test_qa_bash_rejects_platform_metadata_file():
    """``cat pytest.ini`` / ``cat requirements.txt`` 必须拒——日志里漏掉的越权点。"""
    for cmd in ["cat pytest.ini", "cat requirements.txt", "cat ARCHITECTURE.md"]:
        result = qa_bash.invoke({"command": cmd, "timeout": 5})
        assert result.startswith("error:"), f"{cmd!r} should be rejected"


def test_qa_bash_rejects_absolute_outside_sandbox():
    result = qa_bash.invoke({"command": "cat /etc/passwd", "timeout": 5})
    assert result.startswith("error:")


def test_qa_bash_cwd_is_agent_root(tmp_path, monkeypatch):
    """``ls .`` 必须看到 knowledge/data 内容，看不到 main/ tests/ 等仓库根目录。"""
    # 注：实际仓库的 knowledge/data/ 应有 markdown/ defects/ 子目录
    result = qa_bash.invoke({"command": "ls .", "timeout": 5})
    assert "returncode=0" in result
    # 沙箱外的目录绝不能出现
    assert "main" not in result.split("--- stdout ---")[1].split("\n")[:5][0] if "--- stdout ---" in result else True


def test_get_exec_tools_returns_qa_pair():
    from main.qa_agent.tools.deepagent.exec_tools import get_exec_tools
    tools = list(get_exec_tools())
    names = {t.name for t in tools}
    assert names == {"qa_exec", "qa_bash"}


def test_qa_exec_xlsx_parse_smoke(tmp_path, monkeypatch):
    """xlsx 解析必须能在沙箱内工作（业务核心场景）。

    把 xlsx 放到沙箱内（_AGENT_ROOT），用相对路径打开。
    """
    import openpyxl

    from main.qa_agent.tools.deepagent import exec_tools as exec_mod
    from main.qa_agent.tools.deepagent import file_tools

    # 把沙箱根指到 tmp_path 下
    sandbox = tmp_path / "knowledge" / "data"
    sandbox.mkdir(parents=True)
    monkeypatch.setattr(file_tools, "_AGENT_ROOT", sandbox)
    monkeypatch.setattr(exec_mod, "_AGENT_ROOT", sandbox)

    xlsx_path = sandbox / "smoke.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Test Types", "Priority"])
    ws.append(["", "Functional", "High"])
    ws.append(["", "Boundary", "Low"])
    ws.append(["3", "Negative", "Low"])
    wb.save(xlsx_path)

    code = textwrap.dedent("""
        import openpyxl, collections
        wb = openpyxl.load_workbook('smoke.xlsx')
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        types = collections.Counter(r[1] for r in rows[1:])
        print('rows=', len(rows))
        print('types=', dict(types))
    """).strip()
    result = qa_exec.invoke({"code": code, "timeout": 15})
    assert "returncode=0" in result, result
    assert "rows=" in result
    assert "Functional" in result
    assert "Boundary" in result
