"""``infotest`` CLI entry point.

设计原则：
- CLI 不路由任务类型——agent 通过 tool description / system prompt 自行识别
- 子命令包括：``-p`` print 模式、``--resume`` / ``--continue``
- ``runner.py`` 不动（保留旧入口供脚本/CI 使用）
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from main.ist_core.runner import _ensure_env


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
            "  infotest kms                 知识库总览\n"
            "  infotest kms product update  产品知识库更新（前台执行）\n"
            "  infotest kms qa update       测试知识库更新（前台执行）\n"
            "  infotest reset               清除对话历史和临时文件（默认交互确认）\n"
            "  infotest reset --all -y      同时清理长期记忆且不询问\n"
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
        
        if path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8"))
        
        
        return f"请处理这个文件：{path.resolve().as_posix()}"
    return args.query


def _run_print_mode(query, *, task_type: str, thread_id: str | None) -> int:
    """非交互 print 模式——直接调 runner.run_single，不启 TUI。

    用 ``InMemorySaver`` 而非默认共享 SqliteSaver：print 是单次执行，不需要持久化
    resume；而外层主图的 ``qa_node`` 会**同步**调内层 MainAgent 子图（嵌套 Pregel
    循环）。共享同一 sqlite 连接的 checkpointer 在嵌套同步 invoke 下会死锁：
      - sync SqliteSaver：内层 invoke 重入外层已持有的 threading.Lock → 可重入死锁；
      - async AsyncSqliteSaver：aiosqlite 工作线程在主事件循环未 pump 时空等队列，
        qa_node 线程阻塞等其结果 → 死锁。
    InMemorySaver 无跨线程锁/无 aiosqlite 线程，每次 invoke 独立，彻底绕开。
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from main.ist_core.runner import run_single

    # 标记非交互模式：qa_ask_user 据此立即返回而非阻塞等 TUI 应答（print 无 TUI）。
    import os as _os
    _os.environ["IST_NON_INTERACTIVE"] = "1"

    result = run_single(
        query,
        task_type=task_type,
        thread_id=thread_id,
        stream=False,
        verbose=False,
        checkpointer=InMemorySaver(),
    )
    final = result.get("final_answer") or "（无回答）"
    print(final)
    return 0


def _run_threads_mode() -> int:
    """列历史 thread 后退出（脚本友好）。"""
    from main.ist_core.tui.checkpoint_repo import CheckpointRepo

    repo = CheckpointRepo()
    threads = repo.list_threads(limit=50)
    if not threads:
        if not repo.is_persistent:
            print("(no threads — using InMemorySaver)", file=sys.stderr)
            print("Set IST_SQLITE_PATH or IST_POSTGRES_CHECKPOINT_DSN to persist.", file=sys.stderr)
        else:
            print("(no threads found)")
        return 0
    
    for t in threads:
        preview = (t.preview or "").replace("\n", " ")[:60]
        print(f"{t.thread_id}\t{t.last_step}\t{preview}")
    return 0


def _resolve_continue_thread() -> Optional[str]:
    """``--continue``：从 checkpoint 拿最近一次 thread。"""
    from main.ist_core.tui.checkpoint_repo import CheckpointRepo

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

    def _find_port_pid() -> int | None:
        """Fallback: find PID occupying the port via lsof."""
        try:
            out = subprocess.check_output(
                ["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL
            ).strip()
            if out:
                return int(out.splitlines()[0])
        except (subprocess.CalledProcessError, ValueError):
            pass
        return None

    def _stop() -> bool:
        pid = _read_pid()
        if pid is None:
            pid = _find_port_pid()
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
        # 子进程已 detach（start_new_session）并继承该 fd；父进程开完即关，
        # 否则每次 _start() 都泄漏一个文件描述符。
        log_fh = open(log_file, "a")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "main.ist_core.web_server",
                 "--port", str(port)],
                cwd=str(project_root),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_fh.close()
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
    raw_argv = argv if argv is not None else sys.argv[1:]

    
    if raw_argv and raw_argv[0] == "kms":
        logging.basicConfig(level="WARNING", format="%(levelname)s %(name)s: %(message)s")
        _ensure_env()
        from main.ist_core.tui.kms_cli import run_kms_command
        return run_kms_command(raw_argv[1:])

    
    if raw_argv and raw_argv[0] == "reset":
        logging.basicConfig(level="WARNING", format="%(levelname)s %(name)s: %(message)s")
        _ensure_env()
        from main.ist_core.tui.reset_cli import run_reset_command
        return run_reset_command(raw_argv[1:])

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from main.ist_core.tui import __init__ as _init  # noqa: F401
        print("infotest 1.0.5 (IST-Core)")
        return 0

    
    if args.server:
        return _run_server_command(args.server, args.port)

    
    log_level = args.log_level or ("WARNING" if args.print else "ERROR")
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")
    _ensure_env()

    
    if args.query == "threads" and not args.print:
        return _run_threads_mode()

    task_type = "Review" if (args.task or "").lower() == "review" else "QA"
    thread_id = args.resume or args.thread_id or None

    
    if args.continue_last and not thread_id:
        thread_id = _resolve_continue_thread()
        if not thread_id:
            print("(--continue: 没有找到历史 thread)", file=sys.stderr)
            return 1

    initial_query = _resolve_initial_query(args)

    
    if args.print:
        if initial_query is None:
            print("❌ -p print 模式必须提供 query 或 --input", file=sys.stderr)
            return 2
        return _run_print_mode(initial_query, task_type=task_type, thread_id=thread_id)

    
    initial_text = None
    if isinstance(initial_query, str):
        initial_text = initial_query
    elif isinstance(initial_query, dict):
        initial_text = json.dumps(initial_query, ensure_ascii=False)

    from main.ist_core.ink.components.ist_app import IstInkApp
    app = IstInkApp(
        thread_id=thread_id,
        initial_query=initial_text,
        task_type=task_type,
    )

    # 进程内自调度 dream：TUI 常驻进程不依赖系统 crontab。
    # 受五道闸约束（24h 节流 + PID 锁），后台守护线程，不阻塞启动、失败静默。
    try:
        from main.ist_core.memory.dream import maybe_trigger_dream_async
        maybe_trigger_dream_async()
    except Exception:  # noqa: BLE001
        pass

    app.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
