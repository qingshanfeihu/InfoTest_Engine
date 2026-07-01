"""IST-Core CLI 入口。

用法::

    # 单次查询
    python -m main.ist_core.runner "如何配置 HTTP/2 SLB？"

    # JSON 文件输入（结构化）
    python -m main.ist_core.runner --input sample.json

    # Streaming 事件
    python -m main.ist_core.runner "..." --stream --verbose

    # 回放历史事件
    python -m main.ist_core.runner --replay runtime/logs/run-xxx.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any


def _ensure_env() -> None:
    """加载项目根 ``environment`` 文件并校验当前 provider 的 API key 已配置。"""
    try:
        from dotenv import load_dotenv

        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "environment",
        )
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
    except Exception:  # noqa: BLE001
        pass

    missing: list[str] = []
    if not (os.environ.get("OPENAI_API_KEY") or "").strip():
        missing.append("OPENAI_API_KEY")
    if missing:
        print(
            f"❌ 缺少环境变量: {', '.join(missing)}\n"
            "请在项目根目录 environment 文件中配置（参考 environment.example）",
            file=sys.stderr,
        )
        sys.exit(1)


def _load_input(args: argparse.Namespace) -> Any:
    """解析 --input / 位置参数 -> 返回 user_input。"""
    if args.input:
        path = Path(args.input)
        if not path.exists():
            print(f"❌ 输入文件不存在: {path}", file=sys.stderr)
            sys.exit(2)
        text = path.read_text(encoding="utf-8")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    if args.query:
        return args.query
    print("❌ 必须提供 query 或 --input FILE", file=sys.stderr)
    sys.exit(2)

def _resolve_thread_id() -> str:
    """生成 thread_id。Web session 用 {username}_{session_id}，CLI 兜底用随机 ID。"""
    user = os.environ.get("IST_SSH_USER", "").strip()
    session = os.environ.get("IST_SESSION_ID", "").strip()
    if user and session:
        return f"{user}_{session}"
    return f"run-{uuid.uuid4().hex[:8]}"



def run_single(
    user_input: Any,
    *,
    task_type: str = "QA",
    thread_id: str | None = None,
    stream: bool = False,
    verbose: bool = False,
    checkpointer: Any | bool = True,
    goal: str = "",
) -> dict[str, Any]:
    """单次调用 Graph，返回最终 state。

    ``checkpointer`` 透传给 ``build_ist_core_graph``：
    - ``True``（默认）：按 ``stream`` 选 async/sync 的 SqliteSaver（持久化，可 resume）。
    - 传入 saver 实例（如 ``InMemorySaver()``）：用该实例。print 单次模式用它绕开
      共享 SqliteSaver 锁——外层图 ``qa_node`` 同步调内层 MainAgent 子图会嵌套
      Pregel 循环，共享同一 sqlite 连接的锁在嵌套 invoke 下会死锁（见 cli.py）。
    """
    from main.ist_core.graph import build_ist_core_graph



    mode = "async" if stream else "sync"
    graph = build_ist_core_graph(checkpointer=checkpointer, checkpointer_mode=mode)

    #旧
    #thread_id = thread_id or f"run-{uuid.uuid4().hex[:8]}"
    thread_id = thread_id or _resolve_thread_id()
    config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}

    initial_state: dict[str, Any] = {
        "task_type": task_type,
        "user_input": user_input,
        "messages": [],
    }
    # /goal 自治循环：传了目标就开 goal_gate（opt-in）。外层图默认 recursion_limit=25，
    # 每轮 qa_node→review_gate→goal_gate 约 3 步，N 轮会超 → 按上限放宽外层 limit。
    if (goal or "").strip():
        initial_state["goal_text"] = goal.strip()
        try:
            _cap = max(1, int(os.environ.get("IST_GOAL_MAX_ROUNDS") or 8))
        except (TypeError, ValueError):
            _cap = 8
        config["recursion_limit"] = max(25, _cap * 4 + 20)

    if stream:

        from main.ist_core.sinks.cli_sink import CLISink
        from main.ist_core.streaming import stream_and_collect

        return stream_and_collect(graph, initial_state, config=config, sinks=[CLISink(verbose=verbose)])

    # 主循环连接韧性：心跳 + 外层连接重试（治长跑遇 APIConnectionError 整轮崩、0 产出）。
    from main.ist_core.resilience import Heartbeat, run_with_resilience, set_active_heartbeat
    with Heartbeat() as hb:
        hb.set_note(f"thread={thread_id} task={task_type}")
        set_active_heartbeat(hb)  # 让主 agent tool_call 能刷新 note（当前阶段可见）
        try:
            result = run_with_resilience(lambda: graph.invoke(initial_state, config),
                                         label=f"graph.invoke[{thread_id}]")
        finally:
            set_active_heartbeat(None)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IST-Core CLI 入口（runner 模式，print-only；TUI 走 infotest 命令）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", help="单次查询文本（与 --input 二选一）")
    parser.add_argument("--input", type=str, default="", help="JSON 输入文件路径（优先于位置参数）")
    parser.add_argument("--stream", action="store_true", help="启用流式事件总线（CLI 实时渲染 tool_call / llm_token）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示调试信息（tool filter / top-k hits）")
    parser.add_argument("--no-color", action="store_true", help="禁用 CLI 颜色")
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 摘要（含 findings / messages）")
    parser.add_argument("--replay", type=str, default="", help="回放模式：渲染指定 jsonl 事件文件")
    parser.add_argument("--thread-id", type=str, default="", help="显式指定 thread_id（复用 checkpointer）")

    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(levelname)s %(name)s: %(message)s")

    
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    if args.replay:
        from main.ist_core.sinks.cli_sink import CLISink

        CLISink(verbose=args.verbose, no_color=args.no_color).replay(args.replay)
        return

    _ensure_env()
    user_input = _load_input(args)

    result = run_single(
        user_input,
        task_type="QA",
        thread_id=args.thread_id or None,
        stream=args.stream,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(_summarize(result), ensure_ascii=False, indent=2))
    else:
        final = result.get("final_answer") or "（无回答）"
        print(final)


def _summarize(result: dict[str, Any]) -> dict[str, Any]:
    messages = []
    for msg in (result.get("messages") or [])[-8:]:
        if hasattr(msg, "type"):
            messages.append({"type": msg.type, "content": (msg.content or "")[:500] if isinstance(msg.content, str) else str(msg.content)[:500]})
        elif isinstance(msg, dict):
            messages.append({"type": msg.get("role"), "content": str(msg.get("content", ""))[:500]})
    return {
        "task_type": result.get("task_type"),
        "final_answer": result.get("final_answer"),
        "messages_tail": messages,
        "run_id": result.get("run_id"),
    }


if __name__ == "__main__":
    main()
