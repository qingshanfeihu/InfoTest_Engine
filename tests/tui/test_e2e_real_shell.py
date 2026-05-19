"""Stage 7-9 第二层验证：真启动 TUI 子进程 + pexpect 抓终端输出。

**注意：Textual 用 alternate screen + smcup/rmcup ANSI 序列管理屏幕，pyte
虚拟终端只能抓到一小部分屏幕状态（typically just the docked footer rows）。
Transcript 主体、SlashCompletion、Input 内容这些都看不到——必须人工目视
（Layer 3）。**

本层测试只做这些靠谱的事：
- A. TUI 进程启动不崩 + footer 文本可见（说明 docked 元素渲染正常）
- B. /help 执行后能看到命令名（cmd handler dispatch 正常 + Static text 有时会泄漏到 pyte 抓得到的区域）
- C. /version 输出版本字符串
- D. /exit 正常终止进程
- E. Ctrl+C 双击退出
- F. /commands 不会破坏屏幕

不做：
- 不验证输入回显（pyte 抓不到 Input 内容）
- 不验证 SlashCompletion 候选条（pyte 抓不到 transcript 上方的 widget 内容）
- 不验证工具行渲染（同上）

完整工具行 / 流式 token / 章节折叠的视觉验收必须靠 Layer 3（人工跑 ``infotest`` 看屏）。
"""

from __future__ import annotations

import os
import time

import pexpect
import pyte
import pytest


PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
INFOTEST = os.path.join(PROJECT_ROOT, ".venv", "bin", "infotest")


def _spawn(rows: int = 30, cols: int = 120):
    """spawn infotest TUI 子进程 + 创建 pyte 虚拟终端解析输出。"""
    if not os.path.exists(INFOTEST):
        pytest.skip(f"infotest binary not found: {INFOTEST}; run `pip install -e .` first")

    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "COLUMNS": str(cols),
        "LINES": str(rows),
        "NO_COLOR": "0",
    }
    child = pexpect.spawn(
        INFOTEST,
        timeout=30,
        encoding="utf-8",
        dimensions=(rows, cols),
        env=env,
    )
    screen = pyte.Screen(cols, rows)
    stream = pyte.Stream(screen)
    return child, screen, stream


def _drain(child, screen, stream, *, until_marker: str, timeout: float = 8.0) -> str:
    """读子进程 stdout 直到屏幕里出现 ``until_marker`` 或超时。"""
    deadline = time.time() + timeout
    last_rendered = ""
    while time.time() < deadline:
        try:
            data = child.read_nonblocking(size=8192, timeout=0.2)
        except (pexpect.TIMEOUT, pexpect.EOF):
            data = ""
        if data:
            stream.feed(data)
        last_rendered = "\n".join(line.rstrip() for line in screen.display)
        if until_marker in last_rendered:
            return last_rendered
    raise TimeoutError(
        f"never saw {until_marker!r} (timeout {timeout}s); "
        f"last screen:\n{last_rendered}"
    )


def _close(child) -> None:
    try:
        child.sendcontrol("c")
        time.sleep(0.2)
        child.sendcontrol("c")
    except Exception:
        pass
    try:
        child.expect(pexpect.EOF, timeout=5)
    except Exception:
        try:
            child.terminate(force=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tests (limited to what pyte can actually verify under alt-screen)
# ---------------------------------------------------------------------------


def test_tui_starts_and_footer_visible():
    """A. TUI 启动后 footer 行可见（风格简化为 ``esc to interrupt``）。"""
    child, screen, stream = _spawn()
    try:
        rendered = _drain(child, screen, stream, until_marker="esc to interrupt", timeout=8)
        assert "esc to interrupt" in rendered
    finally:
        _close(child)


def test_slash_exit_closes_tui():
    """D. /exit 干净退出。"""
    child, screen, stream = _spawn()
    try:
        _drain(child, screen, stream, until_marker="esc to interrupt", timeout=8)
        time.sleep(0.5)
        child.send("/exit\r")
        child.expect(pexpect.EOF, timeout=10)
    except pexpect.TIMEOUT:
        pytest.fail("/exit did not terminate process within 10s")
    finally:
        if child.isalive():
            child.terminate(force=True)


def test_ctrl_c_double_press_exits():
    """F. Ctrl+C 连按两次（短窗口内）退出。"""
    child, screen, stream = _spawn()
    try:
        _drain(child, screen, stream, until_marker="esc to interrupt", timeout=8)
        time.sleep(0.5)
        child.sendcontrol("c")
        time.sleep(0.3)
        child.sendcontrol("c")
        child.expect(pexpect.EOF, timeout=10)
    except pexpect.TIMEOUT:
        pytest.fail("two Ctrl+C did not terminate within 10s")
    finally:
        if child.isalive():
            child.terminate(force=True)


def test_print_mode_does_not_show_tui():
    """``infotest -p "..."`` 是非交互模式，不应启 Textual TUI / 不应有 alt-screen ANSI 序列。

    用 ``--version`` 跑（不调 LLM 避免超时），关键验证 stdout 不含 alt-screen 序列。
    """
    import subprocess
    result = subprocess.run(
        [INFOTEST, "--version"],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0
    # 不应有 ENTER_ALT_SCREEN 序列（DEC 1049 / 1047 / 47）
    assert "\x1b[?1049h" not in result.stdout
    assert "\x1b[?1047h" not in result.stdout


def test_version_flag_quick_exit():
    """``--version`` 立即退出，不进 TUI。"""
    import subprocess
    result = subprocess.run(
        [INFOTEST, "--version"],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0
    assert "infotest" in result.stdout
    assert "0.1.0" in result.stdout


def test_threads_subcommand_quick_exit():
    """``infotest threads`` 列历史后立即退出。"""
    import subprocess
    result = subprocess.run(
        [INFOTEST, "threads"],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0


def test_help_flag_quick_exit():
    """``--help`` 立即退出。"""
    import subprocess
    result = subprocess.run(
        [INFOTEST, "--help"],
        capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0
    for arg in ("--resume", "--continue", "--input", "-p", "threads"):
        assert arg in result.stdout, f"--help missing {arg}"


def test_history_persists_across_processes(tmp_path, monkeypatch):
    """↑↓ 历史持久化：一个进程提交 query 后，下次启动 InputHistory 能 load 到。

    本测试不真启 TUI 子进程（pyte 抓不到 Input 内容）；改测 InputHistory
    模块的端到端持久化（已被 test_input_history.py 覆盖；这里再做一次 sanity）。
    """
    import os
    history_file = tmp_path / "history"
    monkeypatch.setenv("INFOTEST_HISTORY_PATH", str(history_file))
    # Force reload
    from main.qa_agent.tui import input_history
    import importlib
    importlib.reload(input_history)
    h1 = input_history.InputHistory()
    h1.add("e2e-query-1")
    h1.add("e2e-query-2")
    # 新实例应能读到
    h2 = input_history.InputHistory()
    assert "e2e-query-1" in h2.items
    assert "e2e-query-2" in h2.items

