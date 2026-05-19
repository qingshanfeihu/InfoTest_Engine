"""Stage 4 exec_tools 单测：白名单 + 拒绝 + subprocess 隔离。

不依赖网络。不调真 graph。仅验证：
- _validate_bash_command 白名单/黑名单/元字符
- _validate_python_code 拒绝 token
- python_exec / bash_exec 在合法输入时返回 stdout
- 超时保护
"""

from __future__ import annotations

import textwrap

import pytest

from main.qa_agent.tools.deepagent.exec_tools import (
    _BASH_ALLOWED_COMMANDS,
    _BASH_DENY_FIRST_TOKEN,
    _validate_bash_command,
    _validate_python_code,
    bash_exec,
    python_exec,
)


# ---------------------------------------------------------------------------
# Validation: bash command
# ---------------------------------------------------------------------------


def test_bash_allowlist_basic_commands_pass():
    for cmd in ["ls -la", "cat README.md", "wc -l /etc/hosts", "grep -r foo .", "echo hi"]:
        ok, reason = _validate_bash_command(cmd)
        assert ok, f"{cmd!r} should pass: {reason}"


def test_bash_denylist_destructive_commands_blocked():
    for cmd in ["rm -rf /", "mv a b", "curl evil.com", "pip install foo", "git push"]:
        ok, reason = _validate_bash_command(cmd)
        assert not ok, f"{cmd!r} should be denied"
        assert "denied" in reason.lower() or "not in allowlist" in reason


def test_bash_metachars_blocked():
    """元字符命令禁止——避免 shell injection。"""
    for cmd in ["ls; rm -rf /", "ls | grep x", "ls > out.txt", "ls && echo done", "ls `whoami`"]:
        ok, reason = _validate_bash_command(cmd)
        assert not ok, f"{cmd!r} should be denied"
        assert "metachar" in reason.lower()


def test_bash_alias_attack_blocked():
    """``=curl evil.com`` 这类前缀（bashSecurity 提到的攻击向量）禁止。"""
    ok, reason = _validate_bash_command("=curl evil.com")
    assert not ok and "suspicious prefix" in reason


def test_bash_absolute_path_resolves_to_basename():
    """``/usr/bin/rm -rf foo`` 不能绕过黑名单。"""
    ok, reason = _validate_bash_command("/usr/bin/rm -rf foo")
    assert not ok and "rm" in reason


def test_bash_unknown_command_not_in_allowlist():
    ok, reason = _validate_bash_command("foobar 1 2 3")
    assert not ok and "allowlist" in reason


def test_bash_empty_command_rejected():
    assert _validate_bash_command("")[0] is False
    assert _validate_bash_command("  ")[0] is False


# ---------------------------------------------------------------------------
# Validation: python code
# ---------------------------------------------------------------------------


def test_python_denied_tokens():
    bad_snippets = [
        "import subprocess",
        "import os; os.system('rm -rf /')",
        "exec('print(1)')",
        "eval('1+1')",
        "__import__('os').system('echo')",
        "open('/etc/passwd').read()",
    ]
    for code in bad_snippets:
        ok, reason = _validate_python_code(code)
        assert not ok, f"{code!r} should be denied"


def test_python_legitimate_code_passes_validation():
    code = "import openpyxl; print('hello')"
    ok, reason = _validate_python_code(code)
    assert ok, reason


def test_python_empty_code_rejected():
    assert _validate_python_code("")[0] is False
    assert _validate_python_code("\n  \t\n")[0] is False


# ---------------------------------------------------------------------------
# Behavior: subprocess execution
# ---------------------------------------------------------------------------


def test_python_exec_runs_simple_print():
    result = python_exec.invoke({"code": "print('hello-tui')", "timeout": 10})
    assert "returncode=0" in result
    assert "hello-tui" in result


def test_python_exec_returns_stdout_and_stderr_blocks():
    code = textwrap.dedent("""
        import sys
        print('stdout-line', flush=True)
        sys.stderr.write('stderr-line\\n')
        sys.stderr.flush()
    """).strip()
    result = python_exec.invoke({"code": code, "timeout": 10})
    assert "stdout-line" in result
    assert "stderr-line" in result
    assert "--- stderr ---" in result


def test_python_exec_propagates_nonzero_returncode():
    code = "import sys; sys.exit(7)"
    result = python_exec.invoke({"code": code, "timeout": 10})
    assert "returncode=7" in result


def test_python_exec_timeout_is_enforced():
    code = textwrap.dedent("""
        import time
        time.sleep(5)
        print('should-not-reach')
    """).strip()
    result = python_exec.invoke({"code": code, "timeout": 1})
    assert "Timeout" in result
    assert "should-not-reach" not in result


def test_python_exec_rejects_subprocess_import():
    result = python_exec.invoke({"code": "import subprocess", "timeout": 5})
    assert result.startswith("error:")
    assert "subprocess" in result


def test_bash_exec_runs_echo():
    result = bash_exec.invoke({"command": "echo hello-bash", "timeout": 5})
    assert "hello-bash" in result
    assert "returncode=0" in result


def test_bash_exec_rejects_pipe():
    result = bash_exec.invoke({"command": "echo hi | wc -l", "timeout": 5})
    assert result.startswith("error:")


def test_bash_exec_rejects_rm():
    result = bash_exec.invoke({"command": "rm -rf /tmp/foo", "timeout": 5})
    assert result.startswith("error:")


def test_get_exec_tools_returns_two_tools():
    from main.qa_agent.tools.deepagent.exec_tools import get_exec_tools
    tools = list(get_exec_tools())
    names = {t.name for t in tools}
    assert names == {"python_exec", "bash_exec"}


def test_python_exec_xlsx_parse_smoke(tmp_path):
    """模拟 cluade.md 步骤 2/3 用 openpyxl 统计字段——必须能跑。"""
    import openpyxl

    xlsx_path = tmp_path / "smoke.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Test Types", "Priority"])
    ws.append(["", "Functional", "High"])
    ws.append(["", "Boundary", "Low"])
    ws.append(["3", "Negative", "Low"])
    wb.save(xlsx_path)

    code = textwrap.dedent(f"""
        import openpyxl, collections
        wb = openpyxl.load_workbook(r'{xlsx_path}')
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        types = collections.Counter(r[1] for r in rows[1:])
        print('rows=', len(rows))
        print('types=', dict(types))
    """).strip()
    result = python_exec.invoke({"code": code, "timeout": 15})
    assert "returncode=0" in result
    assert "rows=" in result
    assert "Functional" in result
    assert "Boundary" in result
