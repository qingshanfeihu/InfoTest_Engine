"""TuiSink：把 ``QaAgentEvent`` 翻译成 Textual ``Message`` 投递到 UI 线程。

关键约束：
- EventBus 是同步的，graph worker 线程会直接回调 ``__call__``
- 不能直接 update widget，必须用 ``app.call_from_thread(post_message, msg)``
- llm_token 节流 80ms（对齐 cli_sink.py:60），避免每个 token 都唤醒 UI

工具名 -> 消息子类的派发表在 ``messages.TOOL_NAME_TO_MESSAGE``。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from main.qa_agent.events import QaAgentEvent
from main.qa_agent.tui.messages import (
    AIFinalMessage,
    AIThinkingMessage,
    BashExecMessage,
    ErrorMessage,
    EvidenceMessage,
    FileReadMessage,
    FindingMessage,
    GrepHitsMessage,
    HilRequestMessage,
    HumanInputMessage,
    InfoMessage,
    IstMessage,
    LsTreeMessage,
    PhaseMarkerMessage,
    PlatformTaskMessage,
    PythonExecMessage,
    SubAgentTaskMessage,
    TodoListMessage,
    TOOL_NAME_TO_MESSAGE,
    ToolCallMessage,
    WarnMessage,
    XlsxSheetMessage,
)

# ---------------------------------------------------------------------------
# Textual Message wrappers
# ---------------------------------------------------------------------------

@dataclass
class IstUiEvent:
    """跨线程投递到 Textual App 的统一信封。

    在 widgets 端用 ``on_ist_ui_event`` 类型的 handler 接收。我们不直接用
    Textual 的 ``Message`` 子类，因为 sink 模块要保持对 textual 的零依赖
    便于纯 pytest 单测（plan 验证策略：mock post_message）。
    """

    kind: str  # "append" | "update_ai_token" | "finalize_ai" | "tool_done" | ...
    message: IstMessage | None = None
    extra: dict[str, Any] | None = None

# ---------------------------------------------------------------------------
# TuiSink
# ---------------------------------------------------------------------------

class TuiSink:
    """订阅 EventBus 的 sink；把 QaAgentEvent 映射成 IstUiEvent 投递到 UI。

    用法::

        sink = TuiSink(post=app.call_from_thread_post)
        bus.subscribe(sink)

    其中 ``post`` 是一个回调，签名 ``post(IstUiEvent) -> None``。在 IstApp 里
    实现为 ``self.call_from_thread(self.post_message, IstUiEventMessage(ev))``。
    """

    def __init__(
        self,
        post: Callable[[IstUiEvent], None],
        *,
        token_throttle_ms: int = 80,
    ) -> None:
        self._post = post
        self._throttle_s = token_throttle_ms / 1000.0
        self._token_buf: list[str] = []
        self._token_run_seq: int = 0  # 当前流式 AIThinkingMessage 的 seq，用于增量
        self._last_flush = 0.0
        self._lock = threading.Lock()
        # inflight by tool name —— 当 tool_call 创建消息后，对应的 tool_result
        # 来时切状态。SubAgentTaskMessage 也走此处理（Step 8：删 subagent_start/end
        # 死代码后，task 工具的状态机完全靠 LangChain 标准 tool_call/tool_result
        # 驱动）。
        self._tool_calls_inflight: dict[str, ToolCallMessage] = {}  # by run_id+seq
        self._subagent_tasks_inflight: dict[str, "SubAgentTaskMessage"] = {}  # by tool name

    # -- Public sink protocol ------------------------------------------------

    def __call__(self, event: QaAgentEvent) -> None:
        kind = event.get("kind") or ""
        if kind == "llm_token":
            self._handle_token(event)
            return
        # Any non-token event: flush pending tokens first to keep UI ordering
        self._flush_tokens(force=True)
        try:
            self._handle_event(event)
        except Exception as exc:  # noqa: BLE001
            # Sink 异常绝不能传回 EventBus（会被 EventBus 吞，但留个 InfoMessage）
            self._post(IstUiEvent(kind="append", message=ErrorMessage(text=f"TuiSink error: {exc}")))

    # -- Token streaming -----------------------------------------------------

    def _handle_token(self, event: QaAgentEvent) -> None:
        content = (event.get("payload") or {}).get("content") or ""
        if not content:
            return
        with self._lock:
            self._token_buf.append(content)
            now = time.time()
            if now - self._last_flush >= self._throttle_s:
                self._flush_tokens_unsafe()
                self._last_flush = now

    def _flush_tokens(self, *, force: bool = False) -> None:
        with self._lock:
            if self._token_buf and (force or time.time() - self._last_flush >= self._throttle_s):
                self._flush_tokens_unsafe()

    def _flush_tokens_unsafe(self) -> None:
        if not self._token_buf:
            return
        chunk = "".join(self._token_buf)
        self._token_buf.clear()
        self._post(IstUiEvent(kind="update_ai_token", extra={"chunk": chunk}))

    # -- Non-token event dispatch -------------------------------------------

    def _handle_event(self, event: QaAgentEvent) -> None:
        kind = event.get("kind") or ""
        run_id = event.get("run_id") or ""
        seq = int(event.get("seq") or 0)
        ts = event.get("ts") or ""
        payload = event.get("payload") or {}
        tags = event.get("tags") or {}

        if kind == "run_start":
            self._post(IstUiEvent(kind="run_start", extra={"run_id": run_id, "thread_id": payload.get("config", {}).get("thread_id")}))
        elif kind == "run_end":
            self._post(IstUiEvent(kind="run_end", extra={"run_id": run_id}))
        elif kind == "run_error":
            self._post(IstUiEvent(kind="append", message=ErrorMessage(run_id=run_id, seq=seq, ts=ts, text=str(payload))))
        elif kind in {"node_start", "node_end"}:
            node = tags.get("node") or tags.get("name") or ""
            self._post(IstUiEvent(kind=kind, extra={"node": node, "run_id": run_id}))
            # 权威对话结论：必须用 finalize node 的 final_answer，不能用 qa_node。
            # qa_node 的 final_answer 只是「本轮主 agent 最后一条 AIMessage」——
            # 评审场景下 graph.finalize() 才把 review-verification 的 ToolMessage
            # 全文 merge 进来；若在 qa_node_end 就投 AIFinalMessage，用户只能看到
            # 「评审完成」短总结，看不到逐条 Check + 测试建议（与 graph.py finalize
            # 注释中的工程兜底初衷一致）。
            if kind == "node_end" and node == "finalize":
                final_answer = payload.get("final_answer") or ""
                if final_answer:
                    self._post(IstUiEvent(
                        kind="append",
                        message=AIFinalMessage(
                            run_id=run_id, seq=seq, ts=ts, content=final_answer,
                        ),
                    ))
        elif kind == "phase_marker":
            phase = payload.get("phase") or payload.get("event") or ""
            self._post(IstUiEvent(kind="append", message=PhaseMarkerMessage(run_id=run_id, seq=seq, ts=ts, phase=phase)))
        elif kind in {"tool_call", "tool_start"}:
            msg = self._make_tool_message(event)
            if isinstance(msg, ToolCallMessage):
                self._tool_calls_inflight[f"{run_id}:{seq}"] = msg
            # SubAgentTaskMessage（task 工具）—— Step 8 改造：靠 LangChain 标准
            # tool_call/tool_result 驱动状态机，不再用自定义 subagent_start/end 事件
            if isinstance(msg, SubAgentTaskMessage):
                tool_name = tags.get("name") or payload.get("name") or "task"
                self._subagent_tasks_inflight[tool_name] = msg
            self._post(IstUiEvent(kind="append", message=msg))
        elif kind in {"tool_result", "tool_end"}:
            tool_name = tags.get("name") or ""
            # 切 SubAgentTaskMessage 状态 running → done（Step 8）
            sub_task = self._subagent_tasks_inflight.pop(tool_name, None)
            if sub_task is not None:
                sub_task.status = "done"
                sub_task.result = (payload.get("output") or "")[:500]
                self._post(IstUiEvent(kind="update_subagent_task", message=sub_task))
            self._post(IstUiEvent(
                kind="tool_done",
                extra={
                    "run_id": run_id,
                    "tool_name": tool_name,
                    "result": payload.get("output") or "",
                },
            ))
        elif kind == "llm_start":
            self._token_run_seq = seq
            self._post(IstUiEvent(kind="append", message=AIThinkingMessage(run_id=run_id, seq=seq, ts=ts)))
        elif kind == "llm_end":
            self._flush_tokens(force=True)
            # AIFinalMessage——不是 finalize 流式 widget。这样在工具行上方会出现
            if payload.get("name") == "thought":
                content = payload.get("content") or ""
                if content:
                    self._post(IstUiEvent(
                        kind="append",
                        message=AIFinalMessage(run_id=run_id, seq=seq, ts=ts, content=content),
                    ))
                return
            # graph.py:_MainAgentProgressHandler.on_chat_model_end 发的 usage-only 事件
            # -> 只走 finalize_ai 通路更新 token 计数，不渲染消息
            if payload.get("name") == "usage_only":
                self._post(IstUiEvent(
                    kind="finalize_ai",
                    extra={"run_id": run_id, "usage": event.get("usage") or {}},
                ))
                return
            self._post(IstUiEvent(
                kind="finalize_ai",
                extra={"run_id": run_id, "usage": event.get("usage") or {}},
            ))
        elif kind == "evidence_added":
            self._post(IstUiEvent(kind="append", message=EvidenceMessage(run_id=run_id, seq=seq, ts=ts, payload=payload)))
        elif kind in {"finding_emitted", "finding_written"}:
            self._post(IstUiEvent(kind="append", message=FindingMessage(run_id=run_id, seq=seq, ts=ts, payload=payload)))
        elif kind == "hil_request":
            self._post(IstUiEvent(
                kind="hil_request",
                message=HilRequestMessage(
                    run_id=run_id,
                    seq=seq,
                    ts=ts,
                    findings=payload.get("findings") or {},
                    draft_answer=payload.get("draft_answer") or "",
                    reason=payload.get("reason") or "",
                ),
            ))
        elif kind == "hil_response":
            self._post(IstUiEvent(kind="hil_response", extra={"run_id": run_id, "decision": payload}))
        # NOTE: subagent_start / subagent_end 处理分支已删除（Step 8）。
        # 历史死代码：grep 确认无 emit 点。task 工具走 LangChain 标准
        # tool_call/tool_result——见本文件下方 _build_tool_call_message
        # 派发 SubAgentTaskMessage(status="running")，on_tool_end 由
        # ToolCallMessage 状态机切到 done。
        elif kind == "error":
            self._post(IstUiEvent(kind="append", message=ErrorMessage(run_id=run_id, seq=seq, ts=ts, text=str(payload))))
        elif kind == "warn":
            self._post(IstUiEvent(kind="append", message=WarnMessage(run_id=run_id, seq=seq, ts=ts, text=str(payload))))
        elif kind == "info":
            # 不渲染 LangGraph 内部 chain 的 on_prompt_start / on_custom_event 事件
            # （不显示 chain name 在 transcript）
            # 只在 payload 显式有 ``info_text`` 字段时才 append
            if payload.get("name") == "thinking_block":
                # qwen3 / Claude 系列输出的 thinking block -> 单独 ThinkingMessage
                from main.qa_agent.tui.messages import ThinkingMessage
                thinking = payload.get("thinking") or ""
                if thinking:
                    self._post(IstUiEvent(
                        kind="append",
                        message=ThinkingMessage(run_id=run_id, seq=seq, ts=ts, thinking=thinking),
                    ))
                return
            text = payload.get("info_text") or ""
            if text:
                self._post(IstUiEvent(kind="append", message=InfoMessage(run_id=run_id, seq=seq, ts=ts, text=text)))

    def _make_tool_message(self, event: QaAgentEvent) -> IstMessage:
        """根据 ``tool_call.name`` 派发到专属消息子类，未识别则 fallback 到 ToolCallMessage。

        Special-case：``qa_deepagent_read_file`` 路径以 ``.xlsx`` 结尾时升级为
        ``XlsxSheetMessage``——只在 sink 入口判断一次，不污染 widget。
        """
        run_id = event.get("run_id") or ""
        seq = int(event.get("seq") or 0)
        ts = event.get("ts") or ""
        tags = event.get("tags") or {}
        payload = event.get("payload") or {}
        tool_name = tags.get("name") or ""
        args = payload.get("input") or {}
        if isinstance(args, str):
            # 字符串 input -> 直接解析（LangChain on_tool_start 走这条路）
            args = _parse_input_str_to_args(args, tool_name)
        elif isinstance(args, dict) and "raw" in args and len(args) == 1:
            # 我们 graph.py:_emit 包装的 {"raw": "..."} -> 也走解析
            parsed = _parse_input_str_to_args(args["raw"], tool_name)
            if parsed:
                args = parsed

        # xlsx upgrade path — read_file with .xlsx -> XlsxSheetMessage
        if tool_name == "qa_deepagent_read_file":
            path = (args or {}).get("path") if isinstance(args, dict) else ""
            if isinstance(path, str) and path.lower().endswith((".xlsx", ".xlsm")):
                return XlsxSheetMessage(run_id=run_id, seq=seq, ts=ts, workbook_path=path)

        # Normal dispatch
        cls = TOOL_NAME_TO_MESSAGE.get(tool_name, ToolCallMessage)
        if cls is FileReadMessage:
            path = (args or {}).get("path") if isinstance(args, dict) else ""
            return FileReadMessage(run_id=run_id, seq=seq, ts=ts, path=str(path or ""))
        if cls is GrepHitsMessage:
            pattern = (args or {}).get("pattern") if isinstance(args, dict) else ""
            return GrepHitsMessage(run_id=run_id, seq=seq, ts=ts, pattern=str(pattern or ""))
        if cls is LsTreeMessage:
            path = (args or {}).get("path") if isinstance(args, dict) else ""
            # 不再用 "." 兜底——args 没解析到就不显示括号内容
            return LsTreeMessage(run_id=run_id, seq=seq, ts=ts, path=str(path or ""))
        if cls is PythonExecMessage:
            code = (args or {}).get("code") if isinstance(args, dict) else ""
            return PythonExecMessage(run_id=run_id, seq=seq, ts=ts, code=str(code or ""))
        if cls is BashExecMessage:
            command = (args or {}).get("command") if isinstance(args, dict) else ""
            return BashExecMessage(run_id=run_id, seq=seq, ts=ts, command=str(command or ""))
        if cls is SubAgentTaskMessage:
            subagent_type = (args or {}).get("subagent_type") if isinstance(args, dict) else ""
            description = (args or {}).get("description") if isinstance(args, dict) else ""
            return SubAgentTaskMessage(
                run_id=run_id, seq=seq, ts=ts,
                subagent_type=str(subagent_type or ""),
                description=str(description or "")[:200],
                status="running",
            )
        if cls is PlatformTaskMessage:
            return PlatformTaskMessage(
                run_id=run_id,
                seq=seq,
                ts=ts,
                task=args if isinstance(args, dict) else {},
                permission_profile=str((args or {}).get("permission_profile") or "") if isinstance(args, dict) else "",
                dry_run=bool((args or {}).get("dry_run", True)) if isinstance(args, dict) else True,
            )
        if cls is TodoListMessage:
            todos = _extract_todos_from_args(args)
            return TodoListMessage(run_id=run_id, seq=seq, ts=ts, todos=todos)
        # Generic fallback
        return ToolCallMessage(
            run_id=run_id,
            seq=seq,
            ts=ts,
            tool_name=tool_name,
            args=args if isinstance(args, dict) else {"raw": args},
            status="pending",
        )

    # -- Diagnostics ---------------------------------------------------------

    def reset(self) -> None:
        with self._lock:
            self._token_buf.clear()
            self._token_run_seq = 0
            self._last_flush = 0.0
            self._tool_calls_inflight.clear()
            self._subagent_tasks_inflight.clear()

# ---------------------------------------------------------------------------
# Reverse parser: LangChain ``on_tool_start(input_str=...)`` -> structured args
# ---------------------------------------------------------------------------

_TOOL_PRIMARY_KEY = {
    "qa_deepagent_read_file": "path",
    "qa_deepagent_grep": "pattern",
    "qa_deepagent_ls": "path",
    "qa_deepagent_glob": "pattern",
    "qa_exec": "code",
    "qa_bash": "command",
}

def _parse_input_str_to_args(input_str: str, tool_name: str) -> dict:
    """把 LangChain ``on_tool_start`` 的 input_str 反解析回 ``{path/pattern/code/command}`` dict.

    LangChain 把 tool 调用 args 序列化成的 ``input_str`` 格式有 3 种常见形态：

    1. JSON: ``'{"path": "main/qa_agent/graph.py"}'``
    2. Python repr: ``"{'path': 'main/qa_agent/graph.py'}"``
    3. 单值裸字符串: ``"main/qa_agent/graph.py"`` （tool 只有 1 个参数时偶尔这样）

    根据 ``tool_name`` 知道主参数名（path / pattern / code / command），优先尝试 JSON
    解析；失败则用 ast.literal_eval 解析 dict；再失败把整段当主参数 raw 字符串。
    """
    import ast
    import json

    raw = (input_str or "").strip()
    if not raw:
        return {}

    primary = _TOOL_PRIMARY_KEY.get(tool_name, "")

    # 1. JSON
    try:
        v = json.loads(raw)
        if isinstance(v, dict):
            return v
        if primary and isinstance(v, (str, int, float)):
            return {primary: str(v)}
    except (ValueError, TypeError):
        pass

    # 2. Python repr (单引号 dict)
    try:
        v = ast.literal_eval(raw)
        if isinstance(v, dict):
            return v
        if primary and isinstance(v, (str, int, float)):
            return {primary: str(v)}
    except (ValueError, SyntaxError):
        pass

    # 3. 兜底：整段当主参数（如果工具有主参数）
    if primary:
        return {primary: raw}
    return {"raw": raw}

def _extract_todos_from_args(args: Any) -> list[dict[str, str]]:
    """从 write_todos 的 tool_call args 中提取 todos 列表。

    args 可能是：
    - dict: {"todos": [{"content": "...", "status": "..."}]}
    - str: JSON 字符串
    """
    import json

    if isinstance(args, dict):
        todos = args.get("todos", [])
        if isinstance(todos, list):
            return [
                {"content": str(t.get("content", "")), "status": str(t.get("status", "pending"))}
                for t in todos if isinstance(t, dict)
            ]
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return _extract_todos_from_args(parsed)
        except (ValueError, TypeError):
            pass
    return []
