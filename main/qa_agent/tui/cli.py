"""``infotest`` CLI entry point.

设计原则（来自 plan 实施原则）：
- CLI 不路由任务类型——agent 通过 tool description / system prompt 自行识别
- 子命令对齐 claude / codex 范式：``-p`` print 模式、``--resume`` / ``--continue``
- ``runner.py`` 不动（保留旧入口供脚本/CI 使用）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from main.qa_agent.runner import _ensure_env  # 复用环境变量加载


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infotest",
        description="InfoTest Engine — IST-Core terminal UI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  infotest                     进入交互 TUI\n"
            "  infotest \"ircookie 模式有哪些\"   一次性 query\n"
            "  infotest -p \"...\" > out.txt  print 模式 (CI 友好)\n"
            "  infotest --resume <tid>      恢复历史 thread\n"
            "  infotest --continue          继续最近一次 thread\n"
            "  infotest --input X.xlsx      结构化输入（agent 内部识别意图）\n"
            "  infotest threads             列出历史 thread 后退出\n"
        ),
    )
    parser.add_argument("query", nargs="?", default=None,
                        help="一次性 query（与 --input 二选一）；特殊值 'threads' 列历史")
    parser.add_argument("-p", "--print", action="store_true",
                        help="print 模式：非交互，stdout 直出最终回答（CI 友好）")
    parser.add_argument("--resume", type=str, default="",
                        help="恢复指定 thread-id 的历史会话")
    parser.add_argument("--continue", dest="continue_last", action="store_true",
                        help="继续最近一次 thread")
    parser.add_argument("--input", type=str, default="",
                        help="结构化输入文件路径（xlsx / json / 文本，agent 自行识别）")
    parser.add_argument("--thread-id", type=str, default="",
                        help="显式指定 thread-id（与 --resume 同义）")
    parser.add_argument("--task", choices=["qa", "review", "QA", "Review"], default="qa",
                        help="任务类型提示（agent 仍可覆盖；默认 qa）")
    parser.add_argument("--log-level", default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别（默认：TUI 模式 ERROR / print 模式 WARNING）")
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    parser.add_argument("-server", "--server", nargs="?", const="start",
                        choices=["start", "stop", "restart"],
                        help="Web Terminal 管理：start/stop/restart（默认 start）")
    parser.add_argument("-P", "--port", type=int, default=8080,
                        help="Web Terminal 监听端口（默认 8080）")
    return parser


def _resolve_initial_query(args: argparse.Namespace) -> str | dict | None:
    if args.input:
        path = Path(args.input).expanduser()
        if not path.exists():
            print(f"❌ --input 路径不存在: {path}", file=sys.stderr)
            sys.exit(2)
        # JSON 文件：解析为 dict
        if path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        # 其他文件（xlsx / docx / txt）：把绝对路径作为 query 文本，agent 通过
        # 路径后缀和工具自行解析。这是「CLI 不识别意图」原则的体现。
        return f"请处理这个文件：{path.resolve().as_posix()}"
    return args.query


def _run_print_mode(query, *, task_type: str, thread_id: str | None) -> int:
    """非交互 print 模式——直接调 runner.run_single，不启 TUI。"""
    from main.qa_agent.runner import run_single
    result = run_single(
        query,
        task_type=task_type,
        thread_id=thread_id,
        stream=False,
        verbose=False,
    )
    final = result.get("final_answer") or "（无回答）"
    print(final)
    return 0


def _run_threads_mode() -> int:
    """列历史 thread 后退出（脚本友好）。"""
    from main.qa_agent.tui.checkpoint_repo import CheckpointRepo

    repo = CheckpointRepo()
    threads = repo.list_threads(limit=50)
    if not threads:
        if not repo.is_persistent:
            print("(no threads — using InMemorySaver)", file=sys.stderr)
            print("Set QA_AGENT_SQLITE_PATH or QA_AGENT_POSTGRES_CHECKPOINT_DSN to persist.", file=sys.stderr)
        else:
            print("(no threads found)")
        return 0
    # 一行一条：tid step preview
    for t in threads:
        preview = (t.preview or "").replace("\n", " ")[:60]
        print(f"{t.thread_id}\t{t.last_step}\t{preview}")
    return 0


def _resolve_continue_thread() -> Optional[str]:
    """``--continue``：从 checkpoint 拿最近一次 thread。"""
    from main.qa_agent.tui.checkpoint_repo import CheckpointRepo

    return CheckpointRepo().most_recent_thread_id()


def _run_server_command(action: str, port: int) -> int:
    """Web Terminal 管理：start / stop / restart。"""
    import os
    import signal
    import subprocess
    import time

    pid_file = Path(__file__).resolve().parents[3] / ".web_server.pid"

    def _read_pid() -> int | None:
        if not pid_file.exists():
            return None
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
            return None

    def _stop() -> bool:
        pid = _read_pid()
        if pid is None:
            print("Web Terminal 未运行")
            return False
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pid_file.unlink(missing_ok=True)
                print(f"Web Terminal 已停止 (PID {pid})")
                return True
        os.kill(pid, signal.SIGKILL)
        pid_file.unlink(missing_ok=True)
        print(f"Web Terminal 已强制停止 (PID {pid})")
        return True

    def _start() -> bool:
        if _read_pid():
            print(f"Web Terminal 已在运行 (PID {_read_pid()}, port {port})")
            return False
        project_root = Path(__file__).resolve().parents[3]
        log_file = project_root / "logs" / "web_server.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, "-m", "main.qa_agent.web_server",
             "--port", str(port)],
            cwd=str(project_root),
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        pid_file.write_text(str(proc.pid))
        time.sleep(1.0)
        if proc.poll() is not None:
            print(f"Web Terminal 启动失败，查看日志: {log_file}")
            pid_file.unlink(missing_ok=True)
            return False
        print(f"Web Terminal 已启动 (PID {proc.pid}, port {port})")
        print(f"  日志: {log_file}")
        print(f"  访问: http://localhost:{port}")
        return True

    if action == "stop":
        _stop()
    elif action == "start":
        _start()
    elif action == "restart":
        _stop()
        time.sleep(0.3)
        _start()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from main.qa_agent.tui import __init__ as _init  # noqa: F401
        print("infotest 0.1.0 (IST-Core TUI MVP)")
        return 0

    # -server 子命令：Web Terminal 管理
    if args.server:
        return _run_server_command(args.server, args.port)

    # TUI 模式默认 ERROR（不让 WARNING 污染屏幕）；print 模式默认 WARNING
    log_level = args.log_level or ("WARNING" if args.print else "ERROR")
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")
    _ensure_env()

    # 子命令：query == "threads" 时进列表模式（避免与 argparse subparser 冲突）
    if args.query == "threads" and not args.print:
        return _run_threads_mode()

    task_type = "Review" if (args.task or "").lower() == "review" else "QA"
    thread_id = args.resume or args.thread_id or None

    # --continue：拿最近一次 thread
    if args.continue_last and not thread_id:
        thread_id = _resolve_continue_thread()
        if not thread_id:
            print("(--continue: 没有找到历史 thread)", file=sys.stderr)
            return 1

    initial_query = _resolve_initial_query(args)

    # print 模式：不启 TUI
    if args.print:
        if initial_query is None:
            print("❌ -p print 模式必须提供 query 或 --input", file=sys.stderr)
            return 2
        return _run_print_mode(initial_query, task_type=task_type, thread_id=thread_id)

    # 默认：启动 TUI（Ink 渲染器）
    initial_text = None
    if isinstance(initial_query, str):
        initial_text = initial_query
    elif isinstance(initial_query, dict):
        initial_text = json.dumps(initial_query, ensure_ascii=False)

    from main.qa_agent.ink.components.ist_app import IstInkApp
    app = IstInkApp(
        thread_id=thread_id,
        initial_query=initial_text,
        task_type=task_type,
    )
    app.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
