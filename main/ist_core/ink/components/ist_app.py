"""IstInkApp — IST-Core TUI using the Python Ink renderer.

Replaces the Textual-based IstApp. Uses Python Ink renderer for:
- Real terminal cursor positioning (IME follows cursor)
- Full mouse capture (DEC 1000+1002+1003+1006) with a self-implemented
  selection engine (selection.py) — drag-to-select, double-click word,
  triple-click line, release-copy via OSC 52 + pbcopy/xclip, Ctrl+C
  re-copy when a selection is active. Same native UX.
- Efficient incremental screen updates
"""

from __future__ import annotations

import logging
import os
import time as _time
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

from main.ist_core.ink.app import InkApp
from main.ist_core.ink.components.footer import FooterPane, _format_elapsed, _format_token_count
from main.ist_core.ink.components.plan_panel import PlanPanel
from main.ist_core.ink.components.prompt_input import PromptInput
from main.ist_core.ink.components.transcript import Transcript
from main.ist_core.ink.dom import NodeType, create_element, create_text
from main.ist_core.ink.parse_keypress import (
    InputEvent,
    KeyPress,
    MouseEvent,
    PasteEvent,
    UploadEvent,
    SwitchConversationEvent,
)
from main.ist_core.tui.slash_commands import PickerResult, PickerOption





_TOOL_SHORT_NAMES: dict[str, str] = {
    "fs_read": "Read",
    "fs_grep": "Grep",
    "fs_glob": "Glob",
    "fs_ls": "Ls",
    "fs_write": "Write",
    "fs_edit": "Edit",
    "run_shell": "Bash",
    "run_python": "Exec",
    "invoke_skill": "Skill",
    "kb_footprint": "Footprint",
    "kb_bug_search": "BugSearch",
    "write_todos": "TodoWrite",
    "task": "Agent",
}


def _tool_short_name(raw: str) -> str:
    return _TOOL_SHORT_NAMES.get(raw, raw)


def _is_known_fork_skill(skill_name: str) -> bool:
    """从 reducer 的 fork-skill 缓存查 skill 是不是 fork。

    fork skill 的 invoke_skill 调用显示为 Agent(<skill>)（对齐 task → Agent）。
    """
    try:
        from main.ist_core.tui.reducer import _get_fork_skill_names
        return skill_name in _get_fork_skill_names()
    except Exception:  # noqa: BLE001
        return False


def _extract_from_raw(args: dict, key: str) -> str:
    """从 {"raw": "{'key': 'value', ...}"} 中提取指定 key 的值。"""
    import re
    raw = args.get("raw") or ""
    if not isinstance(raw, str):
        return ""
    m = re.search(rf"""['"]?{key}['"]?\s*[:=]\s*['"]([^'"]+)['"]""", raw)
    return m.group(1) if m else ""


def _tool_display_arg(name: str, args: dict) -> str:
    """工具特定参数摘要。"""
    if not args:
        return ""
    if name in ("fs_read", "fs_write",
                "fs_edit", "fs_ls"):
        path = (args.get("file_path") or args.get("path")
                or _extract_from_raw(args, "path")
                or _extract_from_raw(args, "file_path"))
        if isinstance(path, str) and path:
            parts = path.replace("\\", "/").split("/")
            return "/".join(parts[-2:]) if len(parts) > 2 else path
    if name == "fs_grep":
        pattern = (args.get("pattern") or args.get("query")
                   or _extract_from_raw(args, "pattern")
                   or _extract_from_raw(args, "query"))
        return str(pattern)[:60] if pattern else ""
    if name == "fs_glob":
        pattern = args.get("pattern") or _extract_from_raw(args, "pattern")
        return str(pattern)[:60] if pattern else ""
    if name in ("run_shell", "run_python"):
        cmd = args.get("command") or _extract_from_raw(args, "command") or ""
        cmd = str(cmd)
        return (cmd[:60] + "…") if len(cmd) > 60 else cmd
    if name == "invoke_skill":
        skill = args.get("skill") or _extract_from_raw(args, "skill") or ""
        # 批派可观察性:brief 信封/正文里的 autoid 一并带出(否则并发派 8 个 worker
        # 全是裸「⏺ Skill」行,分不清派的哪个 case——2026-07-03 实证)。
        import re as _re2
        blob = str(args.get("brief") or "") + str(args.get("raw") or "")
        m = _re2.search(r"20303175\d{8,10}", blob)
        aid = f"…{m.group(0)[-6:]}" if m else ""
        if skill and aid:
            return f"{skill} · {aid}"
        if skill:
            return str(skill)[:40]
        # skill 名都抽不到时给 raw 首段,别渲染成裸工具名
        raw = str(args.get("raw") or "")
        return (raw[:40] + "…") if raw else ""
    first_val = next(iter(args.values()), "")
    if isinstance(first_val, str) and len(first_val) > 60:
        return first_val[:60] + "…"
    return str(first_val) if first_val else ""


def _is_transient_tool_error(output: str) -> bool:
    """只把「真·错误结果」判为瞬态连接错误。

    is_transient_error 是给「异常文本 / fork 吞成的 'ERROR: ...' 串」用的；但 TUI 这里
    把它用在所有 tool_result.output 上——正常 tool 输出(如 fs_read 读到的文件内容,满屏
    数字/HTTP 词)会被它的子串匹配误中(实测 autoid 里的 "4291" 撞过裸 "429")。先门控:
    output 得「看起来是错误」(短、且带明确错误信号)才去判瞬态,正常长输出直接放过。
    """
    if not output:
        return False
    low = output.lower()
    looks_like_error = (
        len(output) < 2000
        and ("error" in low or "exception" in low or "traceback" in low
             or "failed" in low or "refused" in low or "timed out" in low)
    )
    if not looks_like_error:
        return False
    from main.ist_core.resilience import is_transient_error
    return is_transient_error(output)


def _tool_result_summary(name: str, output: str) -> list[str] | None:
    """工具特定结果摘要。返回 None = 通用截断；返回 list = 摘要替代。"""
    if name == "fs_read":
        n = output.count("\n") + (1 if output and not output.endswith("\n") else 0)
        return [f"Read \x1b[1m{n}\x1b[0m lines"]
    if name == "fs_glob":
        matches = [l for l in output.split("\n") if l.strip()]
        if len(matches) <= 6:
            return matches or ["(no matches)"]
        return matches[:5] + [f"\x1b[2m… +{len(matches) - 5} matches\x1b[0m"]
    return None


class IstInkApp:
    """IST-Core TUI application using Python Ink renderer."""

    def __init__(
        self,
        *,
        thread_id: str | None = None,
        initial_query: str | None = None,
        task_type: str = "QA",
    ) -> None:
        self._thread_id = thread_id
        self._initial_query = initial_query
        self._task_type = task_type

        
        
        
        self._app = InkApp(alt_screen=True, mouse=True)

        
        self._transcript = Transcript()
        self._prompt = PromptInput(
            cursor_manager=self._app.cursor,
            on_submit=self._on_submit,
            placeholder="输入消息（/ 触发补全）",
        )
        
        
        self._plan_panel = PlanPanel()

        from main.ist_core.ink.components.ask_user_panel import AskUserPanel
        self._ask_user_panel = AskUserPanel()

        
        self._thinking_line = create_element(NodeType.BOX)
        self._thinking_line.style.height = 0
        self._thinking_text = create_text("")
        self._thinking_line.append_child(self._thinking_text)


        self._footer = FooterPane(render_callback=self._app.render, thinking_text_cb=self._update_thinking_line)

        
        self._divider_top = create_element(NodeType.BOX)
        self._divider_top.style.height = 1
        self._divider_top.text_styles.dim = True
        self._divider_text = create_text("")
        self._divider_top.append_child(self._divider_text)

        
        self._divider_bottom = create_element(NodeType.BOX)
        self._divider_bottom.style.height = 1
        self._divider_bottom.text_styles.dim = True
        self._divider_bottom_text = create_text("")
        self._divider_bottom.append_child(self._divider_bottom_text)

        
        
        
        self._app.root.append_child(self._transcript.node)
        self._app.root.append_child(self._plan_panel.node)
        self._app.root.append_child(self._ask_user_panel.node)
        self._app.root.append_child(self._thinking_line)
        self._app.root.append_child(self._divider_top)
        self._app.root.append_child(self._prompt.node)
        self._app.root.append_child(self._divider_bottom)
        self._app.root.append_child(self._footer.node)

        
        self._app.on_input = self._handle_input

        
        self._is_loading = False
        self._bridge: Any = None
        self._streaming_buf: list[str] = []
        self._last_md_render_ts: float = 0.0
        self._md_renderer: Any = None
        self._model: str = ""
        self._welcome_shown: bool = False
        self._last_ctrl_c: float = 0.0
        self._tokens_used: int = 0
        self._run_start_time: float = 0.0
        self._outputs_snapshot: set[str] = set()
        self._tool_outputs_expanded: bool = False
        self._thinking_expanded: bool = False
        self._last_thinking_text: str = ""
        self._tool_output_blocks: list[dict] = []
        self._subagent_thinking_lines: list[dict] = []  # fork ⎿ ∴ Thinking 行 {idx, full},供 ctrl+t 就地展开全文
        self._main_thinking_lines: list[dict] = []  # 主 agent 每条 ∴ thinking 行 {idx, full},供 ctrl+t 全部就地折叠/展开(不只最后一条)
        self._load_tui_config()
        # ask_user 交互式问答的活跃会话（None=非问答模式）
        self._ask_user: Any = None
        
        # 评分系统状态
        self._rating_run_id: str = ""
        self._rating_waiting: bool = False
        self._rating_comment_mode: bool = False
        self._pending_rating_run_id: str = ""  # 待显示的评分run_id（等待流式输出结束）
        
        self._ai_stream_idx: int = -1
        # 流式结束后,暂存流式 ⏺ 消息的行号,供提交版(snapshot.messages 的最终 BLOCK_TEXT)
        # 原地替换,避免"流式 append + 提交 append"把同一段文本渲染成两条(重复 bug)。
        self._stream_commit_idx: int = -1


        from main.ist_core.tui.input_history import InputHistory
        self._input_history = InputHistory()
        self._history_idx = -1

        
        from main.ist_core.tui.state import TuiState
        self.tui_state = TuiState(thread_id=self._thread_id or "")

        # 对话管理（延迟初始化）
        self._checkpoint_repo_obj = None
        self._username = os.environ.get("IST_SSH_USER", "").strip()

        # /resume 交互选择器状态
        self._picker: dict | None = None  # None=非选择模式 | dict: {options, idx, title}

    def append_transcript_info(self, text: str) -> None:
        """线程安全地向 transcript 追加一行（供 KMS 等后台任务回写进度）。"""
        with self._app.lock:
            self._transcript.append_message(f" {text}")
            self._app.render()

    def set_background_status(self, text: str | None) -> None:
        """后台任务进度（显示在输入框上方 thinking 行，不刷屏 transcript）。"""
        with self._app.lock:
            self._update_thinking_line(text)
            self._app.render()

    @property
    def _checkpoint_repo(self):
        """延迟初始化 CheckpointRepo。"""
        if self._checkpoint_repo_obj is None:
            from main.ist_core.tui.checkpoint_repo import CheckpointRepo
            self._checkpoint_repo_obj = CheckpointRepo()
        return self._checkpoint_repo_obj

    # 【屏蔽切换对话功能】切换对话相关方法注释
    # def _on_thread_selected(self, thread_id: str) -> None:
    #     if self._bridge and self._bridge.is_running:
    #         raise RuntimeError("当前对话正在进行中，请等待完成后再切换")
    #     self._thread_id = thread_id
    #     self.tui_state = TuiState(thread_id=thread_id)
    #     if self._bridge:
    #         self._bridge.switch_thread(thread_id)
    #     with self._app.lock:
    #         self._transcript.append_message(f"已切换到对话: {thread_id[-16:]}")
    #         self._app.render()

    # def _switch_conversation(self, conversation_id: str) -> None:
    #     """切换到指定对话（由前端 switch_conversation 消息触发）。"""
    #     if not self._username:
    #         return
    #     new_tid = f"{self._username}_{conversation_id}"
    #     self._on_thread_selected(new_tid)

    def run(self) -> None:
        """Start the TUI (blocking)."""
        import warnings
        import sys
        import os

        
        warnings.filterwarnings("ignore")
        
        devnull = open(os.devnull, "w")
        old_stderr = sys.stderr
        sys.stderr = devnull

        try:
            self._app.start()
            self._start_evidence_tailer()
            self._show_welcome()
            if self._initial_query:
                self._submit(self._initial_query)
            self._wait_for_exit()
        except KeyboardInterrupt:
            pass
        finally:
            
            
            try:
                if self._bridge is not None:
                    self._bridge.cancel()
                    self._bridge.join(timeout=3.0)
            except Exception:  # noqa: BLE001
                pass
            # 关闭 JSONL sink 文件句柄，避免 fd 泄漏
            _jsonl_sink = getattr(self, "_jsonl_sink", None)
            if _jsonl_sink is not None:
                try:
                    _jsonl_sink.close()
                except Exception:  # noqa: BLE001
                    pass
            sys.stderr = old_stderr
            devnull.close()
            self._app.stop()
            
            
            
            
            if self._bridge is not None and self._bridge.is_running:
                import os as _os
                _os._exit(0)

    def _wait_for_exit(self) -> None:
        """Block until the app is stopped."""
        import time
        while self._app._running:
            time.sleep(0.1)

    def _start_evidence_tailer(self) -> None:
        """fastlog 消费端:每 ~300ms 把新增 fork 步骤**追加到主 transcript**(像日志往下流,
        和 agent 消息/里程碑同一条流,不是独立面板 → 不分屏),并把 fork token 并入 footer ↑↓。

        - **只在 sticky-scroll(视图在底部、用户在跟看)时渲染**;用户往上滚(sticky 关)则
          只追加不渲染 → 不与用户滚动时的重排互抢、页面不冲花。
        - 批量(300ms 读一次,非每条事件 emit)→ 不刷卡。完整明细同时在 evidence 日志文件。
        """
        import threading
        import time as _time
        import os as _os
        from main.ist_core.skills.loader import (
            _evidence_log_path, reset_evidence_log, reset_fork_tokens, get_fork_tokens,
        )

        reset_evidence_log()    # 每会话日志从干净开始
        reset_fork_tokens()
        path = _evidence_log_path()
        D, X = self._DIM, self._RESET

        def _poll() -> None:
            offset = 0
            last_ft = (-1, -1)
            while self._app._running:
                _time.sleep(0.3)
                new_lines = []
                try:
                    if _os.path.exists(path):
                        size = _os.path.getsize(path)
                        if size < offset:        # 截断/新 run → 从头
                            offset = 0
                        if size > offset:
                            with open(path, "r", encoding="utf-8") as f:
                                f.seek(offset)
                                chunk = f.read()
                                offset = f.tell()
                            new_lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
                except Exception:  # noqa: BLE001
                    logger.debug("编译日志读取失败", exc_info=True)
                try:
                    ft = get_fork_tokens()
                    if not new_lines and ft == last_ft:
                        continue
                    last_ft = ft
                    with self._app.lock:
                        self._footer.update(fork_input=ft[0], fork_output=ft[1],
                                            fork_cache_hit=ft[2])
                        if new_lines:
                            # 供 footer 判「worker 静默多久」（无相位时 busy 行标注在等 worker）
                            self._footer.fork_last_event_ts = _time.time()
                            self._transcript.append_messages(
                                [f"   {D}· {ln}{X}" for ln in new_lines]
                            )
                        # 只在用户跟看(底部 sticky)时渲染;往上滚则不渲染,放行用户滚动
                        if new_lines and self._transcript.node.sticky_scroll:
                            self._app.render()
                except Exception:  # noqa: BLE001
                    logger.debug("编译日志 UI 更新失败", exc_info=True)

        threading.Thread(target=_poll, daemon=True).start()

    def _show_welcome(self) -> None:
        from main.ist_core.agents._llm import ist_core_default_model
        import os
        model = ist_core_default_model()
        self._model = model
        self._footer.update(model=model)

        w = self._app.width

        
        self._divider_text.set_value("─" * w)
        self._divider_bottom_text.set_value("─" * w)

        
        self._transcript.append_message("")
        from main.common.version import app_version
        self._transcript.append_message(f"  \x1b[1mInfoTest Engine v{app_version()}\x1b[0m")
        self._transcript.append_message(f"  \x1b[2m{model} · {os.getcwd()}\x1b[0m")
        self._transcript.append_message("")
        self._transcript.append_message(f"  \x1b[2m输入自然语言描述测试分析需求，自动调用工具查阅知识库。\x1b[0m")
        self._transcript.append_message(f"  \x1b[2m/help 查看命令 · /init 初始化项目 · /model 切换模型\x1b[0m")
        self._transcript.append_message("")
        self._app.render()
        self._welcome_shown = True

    def _handle_input(self, event: InputEvent) -> None:
        """Dispatch input events to appropriate handlers."""
        
        
        
        
        with self._app.lock:
            if isinstance(event, KeyPress):
                self._handle_key(event)
            elif isinstance(event, MouseEvent):
                self._handle_mouse(event)
            elif isinstance(event, PasteEvent):
                self._prompt.handle_paste(event.text)
                self._app.render()
            elif isinstance(event, UploadEvent):
                self._handle_upload(event)
            elif isinstance(event, SwitchConversationEvent):
                self._handle_switch_conversation(event)

    def _handle_upload(self, event: UploadEvent) -> None:
        """处理带外上传信号（Web Terminal 上传文件经 OSC 序列传入）。

        文件已由 web_server 落到 workspace/inputs/<filename>。这里把它的沙箱
        相对路径插入输入框（光标处），用户可继续补充指令再提交。agent 收到的
        是确定的 `inputs/<filename>` 路径，无需任何正则猜测。
        """
        filename = (event.filename or "").strip()
        if not filename:
            return
        # 仅取 basename 防御（前端已是 basename，双保险挡 OSC payload 注入路径）
        import os as _os
        safe = _os.path.basename(filename.replace("\\", "/"))
        if not safe or safe in (".", ".."):
            return
        ref = f"inputs/{safe}"
        # 插入到输入框：已有内容则加空格分隔，避免和用户已敲的字粘连
        existing = self._prompt.value
        if existing and not existing.endswith((" ", "\n")):
            self._prompt.handle_paste(" " + ref + " ")
        else:
            self._prompt.handle_paste(ref + " ")
        self._transcript.append_message(
            f"  \x1b[2m⬆ 已上传 {safe} → {ref}\x1b[0m"
        )
        self._app.render()

    def _handle_switch_conversation(self, event: SwitchConversationEvent) -> None:
        """Web 前端发来切换对话信号 → 激活新对话，重建 bridge 上下文。"""
        cid = (event.conversation_id or "").strip()
        if not cid or not self._username:
            return
        thread_id = f"{self._username}_{cid}"
        try:
            from main.ist_core.auth.session_manager import SessionManager
            mgr = SessionManager()
            conv = mgr.get_conversation(self._username, cid)
            title = conv.get("title", "新对话")[:60] if conv else "新对话"
            self._on_conversation_resumed(cid, thread_id, title)
            self._transcript.append_message(f" \x1b[32m✓\x1b[0m 已切换对话: {title}")
            self._app.render()
        except Exception:
            self._transcript.append_message(" \x1b[31m✗\x1b[0m 切换对话失败")
            self._app.render()

    @staticmethod
    def _outputs_dir() -> Path:
        """获取当前用户专属的 outputs 目录。"""
        root = Path(__file__).resolve().parents[4]
        username = os.environ.get("IST_SSH_USER", "").strip()
        if not username:
            username = os.environ.get("IST_USERNAME", "").strip()
        if not username:
            username = "default"
        return root / "workspace" / "outputs" / username

    def _snapshot_outputs(self) -> set[str]:
        """快照 workspace/outputs/{username}/ 当前文件集合（用于 run 前后 diff 出新产物）。"""
        d = self._outputs_dir()
        d.mkdir(parents=True, exist_ok=True)
        try:
            return {f.name for f in d.iterdir() if f.is_file() and not f.name.startswith(".")}
        except OSError:
            return set()

    def _notify_new_outputs(self) -> None:
        """agent 回合结束后：检测 outputs 新文件，经 OSC 信号通知 Web 前端刷新下载面板。

        与上传方向对称：写文件这件事发生在 agent 工具层（与渲染解耦），所以在
        回合结束的渲染线程里做 diff + 发信号。OSC 7002 不占屏幕单元，穿过 PTY
        被前端识别。本地 TUI 收到该 OSC 会被 ink 解析器忽略（无害）。
        """
        try:
            current = self._snapshot_outputs()
            new_files = current - self._outputs_snapshot
            self._outputs_snapshot = current
            if not new_files:
                return
            import base64 as _b64
            for name in sorted(new_files):
                b64 = _b64.b64encode(name.encode("utf-8")).decode("ascii")
                self._app.write_passthrough(f"\x1b]7002;{b64}\x07")
            names = "、".join(sorted(new_files))
            self._transcript.append_message(
                f"  \x1b[2m⬇ 已生成 {names} → 可点「下载」获取\x1b[0m"
            )
        except Exception:  # noqa: BLE001
            pass

    def _show_rating_prompt(self, run_id: str) -> None:
        """对话结束后在终端输出评分选项。

        输出格式：
        ── 请对本次对话服务进行评分 ──
        [0] 0分  [1] 1分  [2] 2分  [3] 3分  [4] 4分  [5] 5分  [6] 自定义评价
        输入数字选择评分（不阻塞对话，可继续输入其他内容）
        """
        self._rating_run_id = run_id
        self._rating_waiting = True
        self._rating_comment_mode = False

        self._transcript.append_message("")
        self._transcript.append_message(
            "\x1b[36m── 请对本次对话服务进行评分 ──\x1b[0m"
        )
        self._transcript.append_message(
            "\x1b[2m[0] 0分  [1] 1分  [2] 2分  [3] 3分  [4] 4分  [5] 5分  [6] 自定义评价\x1b[0m"
        )
        self._transcript.append_message(
            "\x1b[2m输入数字选择评分（不阻塞对话，可继续输入其他内容）\x1b[0m"
        )
        self._app.render()

    def _handle_rating_input(self, text: str) -> bool:
        """处理用户输入的评分。

        返回 True 表示输入被评分系统处理，False 表示输入应交给正常对话流程。
        """
        if not self._rating_waiting:
            return False

        text = text.strip()
        if not text:
            return False

        # 检查是否是评分数字 0-6
        if text in ("0", "1", "2", "3", "4", "5", "6"):
            if text == "6":
                # 进入自定义评价模式
                self._rating_comment_mode = True
                self._transcript.append_message(
                    "\x1b[36m请输入自定义评价内容（输入后按回车提交）：\x1b[0m"
                )
                self._app.render()
                return True
            else:
                # 直接提交评分
                score = int(text)
                self._submit_rating(score, "")
                return True

        # 自定义评价模式：提交评价
        if self._rating_comment_mode:
            self._submit_rating(5, text)
            return True

        # 不是评分输入，交给正常对话流程
        return False

    def _submit_rating(self, score: int, comment: str) -> None:
        """提交评分到后端API并显示结果。"""
        import os as _os
        import requests as _requests

        session_user = _os.environ.get("IST_SSH_USER", "").strip()
        session_id = _os.environ.get("IST_AUTH_SESSION_ID", "").strip()
        conversation_id = _os.environ.get("IST_CONVERSATION_ID", "").strip()

        if not session_user or not session_id:
            self._transcript.append_message(
                "\x1b[31m✗ 评分提交失败：缺少认证信息\x1b[0m"
            )
            self._rating_waiting = False
            self._rating_comment_mode = False
            self._app.render()
            return

        try:
            from main.ist_core.web_server import get_auth_token
            token = get_auth_token(session_user, session_id) or ""
        except Exception:
            token = ""

        # 从环境变量读取 web server 地址和端口
        web_host = _os.environ.get("IST_WEB_HOST", "127.0.0.1")
        web_port = _os.environ.get("IST_WEB_PORT", "8080")

        try:
            url = f"http://{web_host}:{web_port}/api/chat/rating/submit?session_id={session_id}&token={token}"
            resp = _requests.post(
                url,
                json={
                    "conversation_id": conversation_id,
                    "run_id": self._rating_run_id,
                    "score": score,
                    "comment": comment,
                },
                timeout=5,
            )
            if resp.ok:
                result = resp.json()
                if result.get("ok"):
                    msg = f"\x1b[32m✓ 评分已提交（{score}分）\x1b[0m"
                    if comment:
                        msg += f"\x1b[2m - {comment}\x1b[0m"
                    self._transcript.append_message(msg)
                else:
                    self._transcript.append_message(
                        f"\x1b[31m✗ 评分提交失败：{result.get('detail', '未知错误')}\x1b[0m"
                    )
            else:
                err = resp.json().get("detail", f"HTTP {resp.status_code}")
                self._transcript.append_message(
                    f"\x1b[31m✗ 评分提交失败：{err}\x1b[0m"
                )
        except Exception as e:
            self._transcript.append_message(
                f"\x1b[31m✗ 评分提交失败：{e}\x1b[0m"
            )

        self._rating_waiting = False
        self._rating_comment_mode = False
        self._rating_run_id = ""
        self._app.render()

    def _handle_key(self, kp: KeyPress) -> None:
        """Handle keyboard events."""
        import time as _time

        # /resume 交互选择器模式：最高优先级，拦截所有按键
        if self._picker is not None:
            self._handle_picker_key(kp)
            return

        # ask_user 问答模式：拦截按键到会话（Other 文本输入态除外，
        # 那时放行给 PromptInput 收文本，enter/esc 在此处理提交/取消）。
        if getattr(self, "_ask_user", None) is not None:
            if self._ask_user.in_other_input:
                if kp.key in ("return", "enter"):
                    text = self._prompt.value
                    self._prompt.clear()
                    self._ask_user.submit_other_text(text)
                    self._app.render()
                    return
                if kp.key == "escape":
                    self._prompt.clear()
                    self._ask_user.cancel_other_input()
                    return
                consumed = self._prompt.handle_key(kp.key, kp.char)
                if consumed:
                    self._app.render()
                return
            if self._ask_user.handle_key(kp.key, kp.char):
                return


        if self._input_history.in_search_mode:
            if self._handle_search_key(kp):
                return

        
        
        
        from main.ist_core.ink.selection import clear_selection, has_selection
        if has_selection(self._app.selection):
            if kp.key == "ctrl+c":
                self._copy_selection(clear_after=False)
                return
            if kp.key == "escape":
                clear_selection(self._app.selection)
                self._app.notify_selection_change()
                self._app.render()
                return

        
        if kp.key == "ctrl+c":
            now = _time.time()
            if self._is_loading:
                self._cancel_query()
                self._last_ctrl_c = now
            elif now - getattr(self, '_last_ctrl_c', 0) < 1.5:
                
                self._app._running = False
            else:
                self._last_ctrl_c = now
                self._transcript.append_message(" \x1b[2m(press ctrl+c again to exit)\x1b[0m")
                self._app.render()
            return
        if kp.key == "ctrl+d":
            self._app._running = False
            return
        if kp.key == "escape":
            if self._is_loading:
                self._cancel_query()
            else:
                self._prompt.clear()
                
                
                
                
                
                
                
                self._app._force_full_render()
            return
        if kp.key == "ctrl+o":
            self._toggle_expand()
            return
        if kp.key == "ctrl+t":
            self._toggle_thinking()
            return
        if kp.key == "ctrl+l":
            self._app._force_full_render()
            return
        if kp.key == "pageup":
            self._scroll_transcript(-self._half_viewport())
            return
        if kp.key == "pagedown":
            self._scroll_transcript(self._half_viewport())
            return
        if kp.key == "ctrl+r":
            self._enter_or_advance_search()
            return
        if kp.key == "up":
            self._history_up()
            self._app.render()
            return
        if kp.key == "down":
            self._history_down()
            self._app.render()
            return
        if kp.key == "tab":
            self._tab_complete()
            return

        
        consumed = self._prompt.handle_key(kp.key, kp.char)
        if consumed:
            self._app.render()

    def _handle_mouse(self, me: "MouseEvent") -> None:
        """Handle mouse events: wheel scrolls transcript; left button does
        the style-based selection (single drag = char, double-click =
        word, triple-click = line, release auto-copies)."""
        
        
        col, row = self._mouse_to_screen_coords(me.x, me.y)

        if me.type == "wheel":
            
            if me.button == 0:
                self._scroll_transcript(-3)
            elif me.button == 1:
                self._scroll_transcript(3)
            return

        
        if me.button != 0:
            return

        if me.type == "press":
            self._handle_left_press(col, row, alt=me.alt)
            return

        if me.type == "move":
            
            
            
            sel = self._app.selection
            if not sel.is_dragging:
                return
            if sel.anchor_span is not None:
                from main.ist_core.ink.selection import extend_selection
                extend_selection(sel, self._app._curr_screen, col, row)
            else:
                from main.ist_core.ink.selection import update_selection
                update_selection(sel, col, row)
            self._app.notify_selection_change()
            self._app.render()
            return

        if me.type == "release":
            from main.ist_core.ink.selection import (
                finish_selection,
                has_selection,
            )
            sel = self._app.selection
            was_dragging = sel.is_dragging
            finish_selection(sel)
            
            
            
            if was_dragging and has_selection(sel):
                self._copy_selection(clear_after=False)
            self._app.notify_selection_change()
            self._app.render()
            return

    def _handle_left_press(self, col: int, row: int, *, alt: bool) -> None:
        """Single / double / triple-click dispatch. Uses a 300 ms
        same-cell window to escalate click count.
        """
        import time as _time
        now = _time.monotonic()
        last = getattr(self, "_last_click_meta", None)
        click_count = 1
        if (
            last is not None
            and now - last[0] < 0.3
            and last[1] == col
            and last[2] == row
        ):
            click_count = last[3] + 1
        
        
        if click_count > 3:
            click_count = 3

        from main.ist_core.ink.selection import (
            select_line_at,
            select_word_at,
            start_selection,
        )

        sel = self._app.selection
        
        sel.scrolled_off_above = []
        sel.scrolled_off_below = []
        sel.scrolled_off_above_sw = []
        sel.scrolled_off_below_sw = []

        screen = self._app._curr_screen
        if click_count == 1:
            start_selection(sel, col, row, alt=alt)
        elif click_count == 2:
            select_word_at(sel, screen, col, row)
        else:
            select_line_at(sel, screen, row)

        self._last_click_meta = (now, col, row, click_count)
        self._app.notify_selection_change()
        self._app.render()

    def _mouse_to_screen_coords(self, x: int, y: int) -> tuple[int, int]:
        """SGR mouse coords are already 0-indexed screen cells (see
        _parse_sgr_mouse). The selection state operates in the same
        coordinate space, so we pass the raw values through. Clamp to the
        current screen bounds to avoid out-of-range indexing during
        edge-of-viewport drags."""
        screen = self._app._curr_screen
        clamped_x = max(0, min(x, max(0, screen.width - 1)))
        clamped_y = max(0, min(y, max(0, screen.height - 1)))
        return clamped_x, clamped_y

    def _copy_selection(self, *, clear_after: bool) -> None:
        """Copy the current selection to the clipboard.

        clear_after=True drops the highlight after copying; False keeps it 
        visible so subsequent Ctrl+C can re-copy the same range.
        """
        from main.ist_core.ink.selection import (
            clear_selection,
            get_selected_text,
            has_selection,
        )
        from main.ist_core.ink.termio.osc import set_clipboard

        sel = self._app.selection
        if not has_selection(sel):
            return
        text = get_selected_text(sel, self._app._curr_screen)
        if not text:
            return
        seq = set_clipboard(text)
        if seq:
            self._app._terminal.write(seq)
        
        self._footer.set_toast(f"Copied {len(text)} chars", ttl_seconds=1.2)
        if clear_after:
            clear_selection(sel)
            self._app.notify_selection_change()
        self._app.render()

    def _half_viewport(self) -> int:
        return max(1, self._transcript.viewport_height() // 2)

    def _scroll_transcript(self, delta: int) -> None:
        if delta == 0:
            return
        self._transcript.scroll_by(delta)
        # 滚动会把超宽/软换行内容移进视口，普通 diff 清不掉宽字符跨列残留(溢到最左成"线")。
        # 走 _repaint_full:render_full 逐格重写(含空格)自愈残影,且无 erase 空白相 → 不闪。
        # 不要用 _force_full_render(那条带 erase,会每次滚动闪一下)。
        self._app._repaint_full()

    

    def _enter_or_advance_search(self) -> None:
        if self._input_history.in_search_mode:
            result = self._input_history.search_next()
            self._update_search_ui(result)
        else:
            initial = self._prompt.value
            result = self._input_history.start_search(initial)
            self._update_search_ui(result)

    def _update_search_ui(self, match: str | None) -> None:
        query = self._input_history.search_query
        if match is not None:
            self._prompt.set_value(match)
        self._footer.set_search_state(query=query, match=match if match else "")
        self._app.render()

    def _handle_search_key(self, kp: KeyPress) -> bool:
        """Search-mode keystroke dispatcher. Returns True if event consumed."""
        key = kp.key
        
        
        if key == "ctrl+r":
            return False
        if key == "escape":
            draft = self._input_history.exit_search(restore=True)
            self._prompt.set_value(draft)
            self._footer.set_search_state(query=None, match=None)
            self._app.render()
            return True
        if key == "enter":
            self._input_history.exit_search(restore=False)
            self._footer.set_search_state(query=None, match=None)
            text = self._prompt.value
            if text:
                self._prompt.clear()
                self._submit(text)
            else:
                self._app.render()
            return True
        if key == "backspace":
            new_q = self._input_history.search_query[:-1]
            result = self._input_history.update_search_query(new_q)
            self._update_search_ui(result)
            return True
        if key == "ctrl+c":
            
            draft = self._input_history.exit_search(restore=True)
            self._prompt.set_value(draft)
            self._footer.set_search_state(query=None, match=None)
            self._app.render()
            return True
        
        if kp.char and len(kp.char) == 1 and kp.char.isprintable():
            new_q = self._input_history.search_query + kp.char
            result = self._input_history.update_search_query(new_q)
            self._update_search_ui(result)
            return True
        
        
        self._input_history.exit_search(restore=False)
        self._footer.set_search_state(query=None, match=None)
        return False

    def _on_submit(self, text: str) -> None:
        """Called when user presses Enter in prompt."""
        # 评分系统：先检查是否是评分输入
        if self._handle_rating_input(text):
            self._prompt.clear()
            return
        self._submit(text)

    def _submit(self, text: str, *, pre_expanded: str | None = None) -> None:
        """Submit user input to the agent.

        ``pre_expanded`` is the original multi-line content when the caller
        already knows it (e.g. repeat-paste auto-submit). When set, the
        placeholder-expansion step is skipped and the LLM receives this
        text verbatim. ``text`` is still used for history / slash routing.
        """
        text = text.strip()
        if not text and not pre_expanded:
            return

        if text:
            
            
            self._input_history.add(text)

            
            
            if text.startswith("/"):
                self._handle_slash(text)
                return

        if pre_expanded is not None:
            expanded = pre_expanded
        else:
            
            
            
            
            expanded = self._prompt.consume_pasted_refs(text).replace("↵", "\n")

        
        if self._welcome_shown:
            self._transcript.clear()
            self._welcome_shown = False

        
        from main.ist_core.tui.input_preprocessor import preprocess_file_paths
        import os as _os
        _session_dir = _os.environ.get("IST_SESSION_DIR")
        processed_text, preprocess_status = preprocess_file_paths(
            expanded,
            session_dir=Path(_session_dir) if _session_dir else None,
        )
        if preprocess_status:
            if preprocess_status.startswith("⬆ NEED_UPLOAD:"):
                filename = preprocess_status.removeprefix("⬆ NEED_UPLOAD:")
                if _session_dir:
                    msg = f"⬆ 文件 {filename} 不在本地，请通过 Web Terminal 上传"
                else:
                    msg = f"⬆ 文件 {filename} 不存在，请检查路径是否正确"
                self._transcript.append_message(f"  \x1b[33m{msg}\x1b[0m")
                self._app.render()
                return
            else:
                
                self._transcript.append_message(f"  \x1b[2m{preprocess_status}\x1b[0m")
                expanded = processed_text

        # 问答分隔线（已有历史消息时显示，首轮不显示）
        if self._transcript.message_count() > 0:
            _w = max(40, self._transcript.node.rect.width or 80)
            self._transcript.append_message(f"\x1b[2m{'─' * _w}\x1b[0m")

        # 用户输入回显:前空一行与上文隔开 + 每行加 > 箭头(dim)标识是输入 + 后空一行
        self._transcript.append_message("")
        for line in expanded.split("\n"):
            self._transcript.append_message(f" \x1b[2m>\x1b[0m {line}")
        self._transcript.append_message("")
        self._footer.update(status="esc to interrupt")
        self._is_loading = True
        self._run_start_time = _time.time()
        # 快照 outputs 基线，回合结束时 diff 出 agent 新生成的可下载文件
        self._outputs_snapshot = self._snapshot_outputs()
        self._app.render()

        
        
        
        self._run_via_bridge(expanded)

    def _submit_expanded(self, expanded: str) -> None:
        """Submit raw multi-line content directly, bypassing the prompt
        editor. Used by repeat-paste auto-submit."""
        
        
        num_lines = expanded.count("\n")
        history_label = (
            f"[Pasted text +{num_lines} lines]" if num_lines else expanded
        )
        self._input_history.add(history_label)
        
        self._prompt.clear_pasted_refs()
        self._submit("", pre_expanded=expanded)

    def _run_via_bridge(self, text: str) -> None:
        """Run query through GraphBridge in background thread."""
        from langchain_core.messages import HumanMessage
        from main.ist_core.tui.bridge import GraphBridge
        from main.ist_core.tui.message_model import MessageSnapshot

        if self._bridge is None:
            from main.ist_core.runner import _resolve_thread_id
            thread_id = self._thread_id or _resolve_thread_id()
            from main.ist_core.sinks.jsonl_sink import JsonlFileSink
            from pathlib import Path
            
            
            _project_root = Path(__file__).resolve().parents[4]
            jsonl_sink = JsonlFileSink(log_dir=_project_root / "runtime" / "logs")
            self._jsonl_sink = jsonl_sink
            extra = [jsonl_sink]
            try:
                from main.ist_core.sinks.pg_sink import PgAuditSink
                extra.append(PgAuditSink())
            except Exception:
                pass
            self._bridge = GraphBridge(
                graph_factory=self._build_graph,
                post=self._on_snapshot,
                thread_id=thread_id,
                extra_sinks=extra,
            )

        if self._bridge.is_running:
            self._transcript.append_message("(busy — 等待当前回合完成)")
            self._app.render()
            return

        initial_state = {
            "task_type": self._task_type,
            "user_input": text,
            "messages": [HumanMessage(content=text)],
        }
        self._streaming_buf = []
        self._last_thinking_idx = -1
        self._suppress_thinking_until_done = False
        self._subagent_inner_summaries = {}
        self._subagent_thinking_lines = []
        self._main_thinking_lines = []
        # B2：新 run 清空 tool_use 行号映射，避免旧行号污染本轮插入定位
        self._tool_use_row = {}
        self._transcript.append_message("")
        self._bridge.start(initial_state)

    @staticmethod
    def _build_graph():
        from main.ist_core.graph import build_ist_core_graph
        return build_ist_core_graph(checkpointer=True)

    def _on_snapshot(self, snapshot: Any) -> None:
        """Handle MessageSnapshot from TuiSink (called from bridge thread).

        把不可变 MessageSnapshot diff 成 transcript 增量渲染(append/原地更新)。
        bridge worker 是后台线程；DOM 修改必须和 ink-input 线程串行化。
        """
        with self._app.lock:
            self._on_snapshot_locked(snapshot)

    def _on_snapshot_locked(self, snapshot: Any) -> None:
        """Diff snapshot against previous state and render changes."""
        from main.ist_core.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_TOOL_RESULT, BLOCK_THINKING,
            BLOCK_PHASE_MARKER, BLOCK_EVIDENCE, BLOCK_FINDING,
        )
        prev = getattr(self, '_prev_snapshot', None)
        self._prev_snapshot = snapshot

        # 思考期（reasoning delta 到达、还没 content）：streaming_text 仍为 None，下面的 streaming
        # 分支不执行 → footer 相位更新被跳过，显示不出「深度思考中」。这里补一步：把 thinking
        # 相位喂给 footer，让尾字段随 mimo 真实思考期显示真实状态（reducer 已按 reasoning delta
        # 置 _llm_phase="thinking"）。不 return——本轮无新消息，继续走后续渲染无害。
        if snapshot.streaming_text is None and snapshot.llm_phase == "thinking":
            self._footer.update(
                llm_phase="thinking",
                output_token_count=snapshot.output_token_count,
            )
            self._app.render()


        if snapshot.streaming_text is not None:
            self._flush_pending_tools()
            rendered = self._render_markdown(snapshot.streaming_text)
            # 正文尚空(minimax <think> 剥离后 content 为空 / 首个 chunk 是纯思考)时**不建 ⏺ 行**——
            # 否则每段纯思考响应留一个空 ⏺ 项目符号(实测 minimax 满屏空 ⏺)。思考走 footer/BLOCK_THINKING
            # 通道显示,不占正文项目符号。等真正有正文再建行。
            if self._ai_stream_idx < 0 and not rendered.strip():
                self._footer.update(
                    llm_phase=snapshot.llm_phase or "thinking",
                    output_token_count=snapshot.output_token_count,
                )
                self._app.render()
                return
            if self._ai_stream_idx < 0:
                self._stream_commit_idx = -1  # 新流开始,放弃上一段未匹配的提交占位
                self._ai_stream_idx = self._transcript.message_count()
                self._transcript.append_message(f" ⏺ {rendered}")
            else:
                self._transcript.update_message_at(
                    self._ai_stream_idx, f" ⏺ {rendered}"
                )
            self._footer.update(
                llm_phase=snapshot.llm_phase or "output",
                output_token_count=snapshot.output_token_count,
            )
            self._app.render()
            return

        
        if prev and prev.streaming_text is not None and snapshot.streaming_text is None:
            # 流式刚结束:记住这条流式 ⏺ 消息的行号,供下面 Path 2 渲染最终 BLOCK_TEXT 时
            # 原地替换(而非再 append 一条同文本 → 重复)。
            self._stream_commit_idx = self._ai_stream_idx
            self._ai_stream_idx = -1

        
        prev_count = len(prev.messages) if prev else 0
        new_msgs = snapshot.messages[prev_count:]
        for msg in new_msgs:
            for block in msg.content:
                self._render_content_block(block, msg)

        
        if snapshot.usage:
            input_t = snapshot.usage.get("input_tokens", 0) or 0
            output_t = snapshot.usage.get("output_tokens", 0) or 0
            cache_hit = snapshot.usage.get("prompt_cache_hit_tokens", 0) or 0
            total = snapshot.usage.get("total_tokens", 0) or (input_t + output_t)
            if total and total != self._tokens_used:
                self._tokens_used = total
                self._footer.update(
                    tokens_used=total,
                    input_tokens=input_t,
                    output_tokens=output_t,
                    llm_phase=snapshot.llm_phase,
                    output_token_count=snapshot.output_token_count,
                    cache_hit_tokens=cache_hit,
                )

        
        if snapshot.status == "done" and (not prev or prev.status != "done"):
            self._flush_pending_tools()
            # 移除末尾孤立的 fork ⎿ ∴ Thinking 占位(fastlog 异步追加的收尾残留,常落在 main 最终回复后)
            self._strip_trailing_subagent_thinking()
            self._is_loading = False
            self._ai_stream_idx = -1
            self._stream_commit_idx = -1  # 回合收尾,清掉未匹配的流式占位,防跨回合误更新

            # 回合耗时 + 本轮 token 用量
            if getattr(self, "_run_start_time", 0.0):
                _elapsed = _time.time() - self._run_start_time
                _f = self._footer
                _run_in = max(0, _f.input_tokens + _f.fork_input - _f._run_start_input)
                _run_out = max(0, _f.output_tokens + _f.fork_output - _f._run_start_output)
                _fmt = _format_token_count
                self._transcript.append_message(
                    f"  \x1b[2m✻ Cooked for {_format_elapsed(_elapsed)}"
                    f" · ↑ {_fmt(_run_in)} · ↓ {_fmt(_run_out)} tokens\x1b[0m"
                )
                # 零产出哨兵(症状级防御):turn "正常结束"却零输入零输出 = 模型层被静默吞错
                # (实证 tokensec 余额尽时 402 未冒泡,TUI 呈现 0.8s 空转,用户无从知晓)。
                # 不论异常在哪层被转成空响应,零产出这个症状机械可判——显式告警。
                if _run_in == 0 and _run_out == 0 and _elapsed < 30:
                    self._transcript.append_message(
                        "  \x1b[31m⚠ 本轮模型零响应(0 token)——大概率 API 异常被静默吞掉:"
                        "请检查供应商余额/网关状态(如 402 Insufficient Balance)、"
                        "或查看 runtime/logs 最新 run-*.jsonl。\x1b[0m"
                    )
                self._run_start_time = 0.0

            if self._plan_panel.is_visible:
                self._plan_panel.mark_all_done()
            self._footer.update(status="ready", llm_phase="", output_token_count=0)
            # 回合结束：检测 outputs 新文件，发 OSC 通知 Web 前端刷新下载面板。
            # 这是每轮真正的完成信号（snapshot.status done）；diff 后更新快照，
            # 故与其他完成路径重复调用也幂等（第二次 new_files 为空）。
            self._notify_new_outputs()

            # 评分系统：对话结束后，设置待显示的评分run_id
            # 不立即显示，等待下一次snapshot更新时（此时所有消息都已渲染）
            run_end_info = getattr(snapshot, 'run_end_info', None) or {}
            run_id = run_end_info.get('run_id', '')
            if run_id and not self._rating_waiting:
                self._pending_rating_run_id = run_id

        elif snapshot.status == "running" and (not prev or prev.status != "running"):
            # 新对话开始：清除评分状态
            self._rating_waiting = False
            self._rating_comment_mode = False
            self._rating_run_id = ""
            self._pending_rating_run_id = ""

        elif snapshot.status == "error" and (not prev or prev.status != "error"):
            self._flush_pending_tools()
            self._is_loading = False
            self._ai_stream_idx = -1
            self._stream_commit_idx = -1  # 同上,错误收尾也清掉流式占位

            # 回合耗时（错误也显示）+ 本轮 token 用量
            if getattr(self, "_run_start_time", 0.0):
                _elapsed = _time.time() - self._run_start_time
                _f = self._footer
                _run_in = max(0, _f.input_tokens + _f.fork_input - _f._run_start_input)
                _run_out = max(0, _f.output_tokens + _f.fork_output - _f._run_start_output)
                _fmt = _format_token_count
                self._transcript.append_message(
                    f"  \x1b[2m✻ Cooked for {_format_elapsed(_elapsed)}"
                    f" · ↑ {_fmt(_run_in)} · ↓ {_fmt(_run_out)} tokens\x1b[0m"
                )
                self._run_start_time = 0.0

            _err_text = ""
            if snapshot.messages:
                last = snapshot.messages[-1]
                for b in last.content:
                    if b.type == BLOCK_TEXT and b.text:
                        self._transcript.append_message(
                            f" \x1b[31m[error]\x1b[0m {b.text}"
                        )
                        _err_text = b.text
                        break
            self._footer.update(status="error", llm_phase="", output_token_count=0)
            # 粘性错误条:transcript 的 [error] 行会被后续输出滚出屏,把摘要驻留在
            # footer 状态行直到下一轮 run 开始(实证:批量编译长会话里错误无感知)。
            self._footer.set_sticky_error(_err_text or "run error(详见上方 [error] 行)")

        # 在所有渲染完成后，检查是否有待显示的评分系统
        # 条件：没有新的流式输出、status为done
        if self._pending_rating_run_id and snapshot.streaming_text is None and snapshot.status == "done":
            run_id = self._pending_rating_run_id
            self._pending_rating_run_id = ""
            if not self._rating_waiting:
                self._show_rating_prompt(run_id)

        self._app.render()

    def _place_result_lines(self, tool_use_id: str, lines: list[str]) -> int:
        """B2：把结果行放到对应 tool_use 行的「结果区」末尾，返回起始行号。

        - 找到该 tool_use 的 ⏺ 行号，结果插到它下方已有结果行之后
          （同一 tool 多段结果按序，且不串到下一个 tool 的 ⏺ 之前）。
        - 找不到对应行（无 tuid / 已被偏移丢失）→ 兜底 append 末尾。
        """
        row_map = getattr(self, "_tool_use_row", {})
        anchor = row_map.get(tool_use_id, -1) if tool_use_id else -1
        if anchor < 0:
            # 兜底：append 末尾（行为同改造前）
            at = self._transcript.message_count()
            for ln in lines:
                self._transcript.append_message(ln)
            return at
        # 插入点 = anchor 行下方，跳过该 tool 已插入的结果行（⎿ / … 开头），
        # 但遇到下一个 ⏺ 行就停（不串到别的 tool）
        insert_at = anchor + 1
        msgs = self._transcript._messages
        while insert_at < len(msgs):
            stripped = msgs[insert_at].lstrip()
            # 跳过本 tool 已插入的结果行：⎿ 首行、… 折叠行，以及新的 5 空格对齐续行
            # （续行不再带 ⎿，故按「缩进且非 ⏺ 工具行」识别）。遇到下一个 ⏺ 即停。
            is_cont = msgs[insert_at].startswith("     ") and not stripped.startswith("⏺")
            if stripped.startswith("⎿") or "⎿" in msgs[insert_at] or stripped.startswith("…") or is_cont:
                insert_at += 1
            else:
                break
        self._insert_result_lines(insert_at, lines)
        return insert_at

    def _insert_result_lines(self, at_idx: int, lines: list[str]) -> None:
        """B2：在 at_idx 处插入结果行，并统一偏移所有 ≥ at_idx 的行索引状态。

        把 tool_result 的 ⎿ 行插到对应 tool_use 行下方（而非 append 末尾），
        使并行工具的每个 ⏺ 下面紧跟自己的结果。集中处理偏移，避免索引漂移。
        """
        n = len(lines)
        if n <= 0:
            return
        self._transcript.replace_range(at_idx, 0, lines)  # count=0 → 纯插入
        # 统一偏移所有受影响的行索引状态
        if getattr(self, "_ai_stream_idx", -1) >= at_idx:
            self._ai_stream_idx += n
        if getattr(self, "_stream_commit_idx", -1) >= at_idx:
            self._stream_commit_idx += n
        if getattr(self, "_last_thinking_idx", -1) >= at_idx:
            self._last_thinking_idx += n
        if hasattr(self, "_tool_use_row"):
            for k, v in self._tool_use_row.items():
                if v >= at_idx:
                    self._tool_use_row[k] = v + n
        if hasattr(self, "_tool_start_stack"):
            self._tool_start_stack = [
                (i + n if i >= at_idx else i, name)
                for (i, name) in self._tool_start_stack
            ]
        if hasattr(self, "_tool_output_blocks"):
            for blk in self._tool_output_blocks:
                if blk.get("start_idx", -1) >= at_idx:
                    blk["start_idx"] += n

    def _render_content_block(self, block: Any, msg: Any) -> None:
        """Render a single ContentBlock to the transcript."""
        from main.ist_core.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_TOOL_RESULT, BLOCK_THINKING,
            BLOCK_PHASE_MARKER, BLOCK_EVIDENCE, BLOCK_FINDING,
        )
        B = self._BOLD
        C = self._CYAN
        D = self._DIM
        X = self._RESET

        
        
        
        
        parent_id = getattr(msg, "parent_tool_use_id", "") or ""
        if parent_id:
            self._render_subagent_inner_block(block, parent_id)
            return

        if block.type == BLOCK_TEXT and block.text:
            self._flush_pending_tools()
            rendered = self._render_markdown(block.text, final=True)
            self._ai_stream_idx = -1
            if getattr(self, "_stream_commit_idx", -1) >= 0:
                # 这段文本刚通过流式渲染过(占位在 _stream_commit_idx 行)。提交版只需把那行
                # 原地替换为 final 渲染,绝不能再 append 一条 → 否则同一段 ⏺ 文本重复两遍。
                self._transcript.update_message_at(
                    self._stream_commit_idx, f" ⏺ {rendered}"
                )
                self._stream_commit_idx = -1
            else:
                self._transcript.append_message(f" ⏺ {rendered}")

        elif block.type == BLOCK_THINKING and block.thinking:

            if getattr(self, '_suppress_thinking_until_done', False):
                return
            self._ai_stream_idx = -1
            # 每条 thinking 独立 append（reducer 已按独立 message + uuid 管理）。
            # 不再删除上一条 thinking 行——thinking 之间几乎必夹 tool_use，
            # 旧的 replace_range 删除会误删/错位后续行，导致 thinking 显示消失。
            if self._thinking_expanded:
                self._transcript.append_message(
                    f" {D}\x1b[3m∴ {block.thinking.strip()}{X}"
                )
            else:
                self._transcript.append_message(
                    f" {D}\x1b[3m∴ Thinking{X} {D}(ctrl+t to expand){X}"
                )
            # 记录每条 thinking 的行号 + 全文，供 ctrl+t 就地折叠/展开（全部，不只最后一条）
            _t_idx = self._transcript.message_count() - 1
            self._last_thinking_idx = _t_idx
            self._last_thinking_text = block.thinking.strip()
            self._main_thinking_lines.append({"idx": _t_idx, "full": block.thinking.strip()})

        elif block.type == BLOCK_TOOL_USE:
            self._ai_stream_idx = -1
            raw_name = block.name or "tool"

            if raw_name == "write_todos":
                return
            # ask_user 的交互与结果完全由 ask_user 面板负责，
            # 不渲染标准工具行（避免重复 + 暴露内部工具名/参数）。
            if raw_name == "ask_user":
                return
            args = dict(block.input) if block.input else {}
            display_name = _tool_short_name(raw_name)
            
            
            if raw_name == "invoke_skill":
                skill_name = args.get("skill") or _extract_from_raw(args, "skill") or ""
                if skill_name and _is_known_fork_skill(skill_name):
                    display_name = "Agent"
            first_val = _tool_display_arg(raw_name, args)
            arg_str = f"({C}{first_val}{X})" if first_val else ""
            idx = self._transcript.message_count()
            display_full = f"{display_name}{X}{arg_str}"
            if block.status == "done":
                self._transcript.append_message(
                    f" \x1b[32m⏺\x1b[0m {B}{display_full}"
                )
            elif block.status == "error":
                self._transcript.append_message(
                    f" \x1b[31m⏺\x1b[0m {B}{display_full}"
                )
            else:
                self._transcript.append_message(
                    f" \x1b[5;33m⏺\x1b[0m {B}{display_full}"
                )
                if not hasattr(self, '_tool_start_stack'):
                    self._tool_start_stack = []
                self._tool_start_stack.append((idx, display_full))
            # B2：记录 tool_use_id → ⏺ 行号，供 tool_result 归位插到其下方
            tuid = getattr(block, "tool_use_id", "") or ""
            if tuid:
                if not hasattr(self, "_tool_use_row"):
                    self._tool_use_row = {}
                self._tool_use_row[tuid] = idx

        elif block.type == BLOCK_TOOL_RESULT:
            self._ai_stream_idx = -1
            # qa_ask_user 结果由 ask_user 面板的完成提示负责，跳过标准结果行
            if (block.name or "") == "qa_ask_user":
                return
            # 瞬态连接错误折叠为单行，不展示完整异常文本（agent 侧仍可看到原始错误）
            if block.output and _is_transient_tool_error(block.output):
                tuid = getattr(block, "tool_use_id", "") or ""
                self._place_result_lines(
                    tuid, [f"   {D}⎿{X} {D}瞬态连接错误，已自动重试{X}"]
                )
                return
            if block.output:
                raw_name = block.name or ""
                tuid = getattr(block, "tool_use_id", "") or ""
                # fork skill (verifier) 完成：折叠为单行 Done
                if (
                    raw_name == "invoke_skill"
                    and "VERDICT:" in block.output
                    and "LEVEL:" in block.output
                ):
                    self._suppress_thinking_until_done = True
                    self._place_result_lines(
                        tuid, [f"   {D}⎿{X} {D}Done (Agent completed){X}"]
                    )
                    return
                full_lines = block.output.split("\n")
                expanded = getattr(self, '_tool_outputs_expanded', False)

                summary = _tool_result_summary(raw_name, block.output)
                # ⎿ 只标结果首行，后续行用 5 空格对齐到内容列（与 Claude Code 一致），
                # 不再每行都堆 ⎿（那样一列角标连成断续竖线）。5 空格 = "   ⎿ " 的视觉宽度。
                def _gut(lns: list[str]) -> list[str]:
                    return [(f"   {D}⎿{X} {t}" if i == 0 else f"     {t}") for i, t in enumerate(lns)]
                if summary is not None and not expanded:
                    result_lines = _gut(list(summary))
                elif expanded or len(full_lines) <= 3:
                    result_lines = _gut([line[:100] for line in full_lines])
                else:
                    result_lines = _gut([line[:100] for line in full_lines[:3]])
                    result_lines.append(
                        f"   {D}… +{len(full_lines) - 3} lines (ctrl+o to expand){X}"
                    )
                display_count = len(result_lines)
                # B2：把结果插到对应 tool_use 行下方（并行工具结果归位）
                start_idx = self._place_result_lines(tuid, result_lines)
                if not hasattr(self, '_tool_output_blocks'):
                    self._tool_output_blocks = []
                self._tool_output_blocks.append({
                    "start_idx": start_idx,
                    "full_lines": full_lines,
                    "display_count": display_count,
                    "tool_name": raw_name,
                })

        elif block.type == BLOCK_PHASE_MARKER:
            phase = block.payload.get("phase", "") if block.payload else ""
            self._transcript.append_message(f" {B}[{phase}]{X}")

        elif block.type == BLOCK_EVIDENCE:
            text = block.payload.get("text", "") if block.payload else ""
            # text 可能是 loader 合并后的**多行** fork 步骤(降刷屏)→ 逐行格式化,
            # 用 append_messages 整批**只滚动一次**(避免每行 O(N) 高度重算)。
            # 单行 evidence(流水线进度行,无 \n)split 后即单元素,行为不变。
            # 放宽到 180:fork 结果行(footprint 节点+命令、dev_probe 回显)信息量大,
            # 120 会把命令语法截没;过长部分靠 transcript soft-wrap 折行对齐。
            ev_lines = [f"   {D}· evidence: {ln[:180]}{X}"
                        for ln in text.split("\n") if ln.strip()]
            if ev_lines:
                self._transcript.append_messages(ev_lines)

        elif block.type == BLOCK_FINDING:
            text = block.payload.get("text", "") if block.payload else ""
            self._transcript.append_message(f"   {B}⚡ finding: {text[:120]}{X}")

        elif block.type == "todo_list":

            todos = block.payload.get("todos") if block.payload else None
            if todos and hasattr(self, '_plan_panel'):
                self._plan_panel.update(todos)

        elif block.type == "ask_user":
            payload = dict(block.payload) if block.payload else {}
            self._begin_ask_user(
                payload.get("question_id", ""),
                list(payload.get("questions", [])),
            )

    def _begin_ask_user(self, question_id: str, questions: list) -> None:
        """进入 ask_user 交互式问答模式（渲染到固定面板，不入 transcript）。"""
        if not question_id or not questions:
            return
        from main.ist_core.ink.components.ask_user_view import AskUserSession
        self._ask_user = AskUserSession(
            question_id,
            questions,
            render=self._render_ask_user,
            on_finish=self._finish_ask_user,
        )
        self._render_ask_user()

    def _render_ask_user(self) -> None:
        """把当前问答会话整列重渲染到固定面板（不随 transcript 滚动）。"""
        if self._ask_user is None:
            self._ask_user_panel.clear()
            self._app.render()
            return
        self._ask_user_panel.update(self._ask_user.render_lines())
        self._app.render()

    def _finish_ask_user(self) -> None:
        """问答结束（提交/取消）：清面板，在 transcript 留一行简洁结果。"""
        session = self._ask_user
        self._ask_user = None
        self._ask_user_panel.clear()
        # A3：留完成提示，让用户/对话历史看到选择结果
        try:
            if session is not None:
                summary = session.result_summary()
                if summary:
                    self._transcript.append_message(summary)
        except Exception:  # noqa: BLE001
            pass
        self._app.render()

    def _render_subagent_inner_block(self, block: Any, parent_id: str) -> None:
        """fork subagent 内部 ContentBlock 折叠成 ⎿ 进度行（接 snapshot 路径）。

        消费 ContentBlock 并进行展示：
        - BLOCK_TEXT / BLOCK_THINKING → ``⎿ ∴ Thinking``（verifier 研究报告全文不平铺）
        - BLOCK_TOOL_USE → ``⎿ <ShortName>(<arg>)``
        - BLOCK_TOOL_RESULT → 跳过（fork 内部工具结果不刷屏）
        每个 parent_id 最多显示 _SUBAGENT_INNER_MAX_LINES 行，超出折成省略提示。
        """
        from main.ist_core.tui.message_model import (
            BLOCK_TEXT, BLOCK_TOOL_USE, BLOCK_THINKING,
        )
        D = self._DIM
        C = self._CYAN
        X = self._RESET

        line = ""
        fork_full = ""  # fork text/thinking 全文,供 ctrl+t 就地展开/折叠
        if block.type in (BLOCK_TEXT, BLOCK_THINKING):
            fork_full = (getattr(block, "thinking", "") or getattr(block, "text", "") or "").strip()
            if getattr(self, "_thinking_expanded", False) and fork_full:
                line = f"   {D}\x1b[3m⎿ ∴ {fork_full}{X}"
            else:
                line = f"   {D}⎿ ∴ Thinking{X}"
        elif block.type == BLOCK_TOOL_USE:
            raw_name = block.name or "tool"
            if raw_name == "write_todos":
                return
            display = _tool_short_name(raw_name)
            args = dict(block.input) if block.input else {}
            arg = _tool_display_arg(raw_name, args)
            line = f"   {D}⎿{X} {display}" + (f"({C}{arg}{X})" if arg else "")
        else:
            return

        if not hasattr(self, "_subagent_inner_summaries"):
            self._subagent_inner_summaries = {}
        if not hasattr(self, "_subagent_thinking_lines"):
            self._subagent_thinking_lines = []
        count = self._subagent_inner_summaries.get(parent_id, 0)
        expanded = getattr(self, "_tool_outputs_expanded", False)
        if expanded or count < self._SUBAGENT_INNER_MAX_LINES:
            self._transcript.append_message(line)
            if fork_full:  # 记录 fork thinking 行,供 ctrl+t 就地展开全文
                self._subagent_thinking_lines.append(
                    {"idx": self._transcript.message_count() - 1, "full": fork_full})
        elif count == self._SUBAGENT_INNER_MAX_LINES:
            self._transcript.append_message(
                f"   {D}… (more subagent activity; ctrl+o to expand){X}"
            )
        
        self._subagent_inner_summaries[parent_id] = count + 1

    # 渲染用 ANSI 常量 + subagent 内部行折叠上限。原先与已删除的旧事件处理器
    # (_on_ui_event_locked / _format_and_append)相邻,清理死代码时被一并移走;
    # 这里恢复——它们仍被活跃渲染路径(self._BOLD / self._SUBAGENT_INNER_MAX_LINES 等)使用。
    _GREEN = "\x1b[32m"
    _RED = "\x1b[31m"
    _CYAN = "\x1b[36m"
    _BOLD = "\x1b[1m"
    _DIM = "\x1b[2m"
    _RESET = "\x1b[0m"
    _SUBAGENT_INNER_MAX_LINES = 3

    def _strip_trailing_subagent_thinking(self) -> None:
        """回合结束时移除 transcript 末尾孤立的 fork 子 agent ``⎿ ∴ Thinking`` 占位行。

        fastlog 异步把 fork 步骤追加到主 transcript,fork 的收尾 thinking 占位常落在
        main 最终回复**之后**残留(现象:main 回复完仍多一行 ⎿ ∴ Thinking)。从末尾往上剥
        连续的占位行(及其间空行),遇到第一条实际内容(main 回复 / 工具行)即停,不误删正文。
        """
        msgs = getattr(self._transcript, "_messages", None)
        if msgs is None:  # 极简 stub Transcript(无 _messages 属性)时安全跳过
            return
        cut = len(msgs)
        while cut > 0 and ("⎿" in msgs[cut - 1] and "∴ Thinking" in msgs[cut - 1]):
            cut -= 1
            while cut > 0 and msgs[cut - 1].strip() == "":
                cut -= 1
        if cut < len(msgs):
            self._transcript.replace_range(cut, len(msgs) - cut, [])
            # 同步移除被删 fork thinking 行的记录(idx 落在被剥区间)
            self._subagent_thinking_lines = [
                r for r in getattr(self, "_subagent_thinking_lines", []) if r["idx"] < cut]

    def _flush_pending_tools(self) -> None:
        """Mark all pending tool dots as green (completed)."""
        if not hasattr(self, '_tool_start_stack'):
            self._tool_start_stack = []
            return
        G = self._GREEN
        B = self._BOLD
        X = self._RESET
        for idx, name in self._tool_start_stack:
            self._transcript.update_message_at(
                idx, f" {G}⏺{X} {B}{name}{X}"
            )
        self._tool_start_stack.clear()


    def _update_thinking_line(self, text: str | None) -> None:
        """Show/hide the thinking status line above the input divider。

        宽度感知截断到**一行**:footer 把最新 fork 步骤接在状态行尾,若超宽换行,
        height=1 的 box 会溢出留残影。这里按可视宽度(CJK 双宽)截断,保证恰好一行。
        """
        if text:
            from ..string_width import string_width
            maxw = max(20, (getattr(self._app, "width", 0) or 120) - 2)
            w, acc = 0, []
            for ch in text:
                cw = string_width(ch)
                if w + cw > maxw:
                    break
                acc.append(ch)
                w += cw
            self._thinking_line.style.height = 1
            self._thinking_text.set_value(" " + "".join(acc))
        else:
            self._thinking_line.style.height = 0
            self._thinking_text.set_value("")

    def _render_markdown(self, text: str, *, final: bool = False) -> str:
        """Render markdown to ANSI. Streaming uses fast regex; final uses Rich."""
        if self._md_renderer is None:
            from main.ist_core.ink.components.markdown_renderer import MarkdownRenderer
            w = self._transcript._node.rect.width or 80
            self._md_renderer = MarkdownRenderer(width=max(w - 4, 20))
        else:
            w = self._transcript._node.rect.width
            if w > 0:
                self._md_renderer.set_width(max(w - 4, 20))
        if final:
            return self._md_renderer.render_final(text)
        return self._md_renderer.render_streaming(text)

    def _handle_slash(self, text: str) -> None:
        """Handle slash commands."""
        from main.ist_core.tui.slash_commands import (
            dispatch_slash_command, ParsedSlashCommand,
            ErrorResult, InfoResult, TextResult, ClearResult, ExitResult, InjectResult, PickerResult,
        )

        parts = text[1:].split(None, 1)
        cmd_name = parts[0] if parts else ""
        cmd_args = parts[1] if len(parts) > 1 else ""

        if cmd_name == "exit":
            self._app._running = False
            return
        if cmd_name == "clear":
            self._transcript.clear()
            self._tool_output_blocks.clear()
            self._plan_panel.clear()
            self._app.render()
            return

        
        parsed = ParsedSlashCommand(command_name=cmd_name, args=cmd_args)
        try:
            result = dispatch_slash_command(parsed, app=self)
            if isinstance(result, ExitResult):
                self._app._running = False
            elif isinstance(result, ClearResult):
                self._transcript.clear()
                self._tool_output_blocks.clear()
                self._plan_panel.clear()
            elif isinstance(result, ErrorResult):
                self._transcript.append_message(f" \x1b[31m✗\x1b[0m {result.text}")
            elif isinstance(result, (InfoResult, TextResult)):
                self._transcript.append_message(f" {result.text}")
            elif isinstance(result, InjectResult):
                # /<skill> 强制触发:把渲染好的合成 prompt 直接当用户输入提交跑 agent
                # (verbatim,不污染输入历史)。_submit_expanded 内部已渲染 + 起 run。
                self._submit_expanded(result.prompt)
                return
            elif isinstance(result, PickerResult):
                # /resume 等:进入选择器模式——键盘上下箭头/Enter 交互
                self._enter_picker(result)
                return
        except Exception as e:
            self._transcript.append_message(f" \x1b[31m✗\x1b[0m /{cmd_name}: {e}")
        self._app.render()

    # ── /resume 交互选择器 ───────────────────────────────────────────────

    def _enter_picker(self, result: PickerResult) -> None:
        """进入选择器模式：渲染选项列表，监听上下箭头/Enter/Esc。"""
        self._picker = {
            "options": result.options,
            "idx": 0,
            "title": result.title,
            "_picker_msg_count": 0,  # 已在 transcript 中的选择器行数
        }
        self._render_picker()

    def _render_picker(self) -> None:
        """渲染选择器 UI 到 transcript 末尾（每次导航时替换上次渲染的行）。"""
        if self._picker is None:
            return
        # 移除上一次选择器渲染的行
        n_old = self._picker.get("_picker_msg_count", 0)
        if n_old > 0:
            total = self._transcript.message_count()
            start = max(0, total - n_old)
            self._transcript.replace_range(start, n_old, [])

        opts = self._picker["options"]
        sel = self._picker["idx"]
        lines = [f"\x1b[1m{self._picker['title']}\x1b[0m"]
        for i, opt in enumerate(opts):
            marker = "\x1b[7m ▶ \x1b[0m" if i == sel else "  "
            lines.append(f"  {marker} \x1b[1m{i+1}.\x1b[0m {opt.label}")
        lines.append("\x1b[2m↑ ↓ 选择 | Enter 确认恢复 | Esc 取消\x1b[0m")

        self._transcript.append_messages(lines)
        self._picker["_picker_msg_count"] = len(lines)
        self._app.render()

    def _handle_picker_key(self, kp: KeyPress) -> None:
        """选择器模式下处理按键。"""
        key = kp.key
        if key in ("up", "down"):
            direction = 1 if key == "down" else -1
            self._picker["idx"] = (self._picker["idx"] + direction) % len(self._picker["options"])
            self._render_picker()
        elif key in ("return", "enter"):
            idx = self._picker["idx"]
            opt = self._picker["options"][idx]
            picker = self._picker
            self._picker = None
            self._on_picker_confirm(opt, picker)
        elif key == "escape":
            # 清理选择器 UI 行
            picker = self._picker
            self._picker = None
            n_old = picker.get("_picker_msg_count", 0)
            if n_old > 0:
                total = self._transcript.message_count()
                start = max(0, total - n_old)
                self._transcript.replace_range(start, n_old, [])
            self._transcript.append_message(" \x1b[2m(已取消)\x1b[0m")


            self._app.render()
        # 数字键 1-3 快速选择
        elif kp.char and kp.char.isdigit():
            n = int(kp.char) - 1
            if 0 <= n < len(self._picker["options"]):
                opt = self._picker["options"][n]
                picker = self._picker
                self._picker = None
                self._on_picker_confirm(opt, picker)

    def _on_picker_confirm(self, opt: PickerOption, picker: dict) -> None:
        """用户确认选择后执行恢复。"""
        # 先清理选择器 UI
        n_old = picker.get("_picker_msg_count", 0)
        if n_old > 0:
            total = self._transcript.message_count()
            start = max(0, total - n_old)
            self._transcript.replace_range(start, n_old, [])

        username = self._username or os.environ.get("IST_SSH_USER", "").strip()
        cid = opt.conversation_id
        thread_id = f"{username}_{cid}"
        title_short = opt.first_user_input[:60] if opt.first_user_input else opt.label

        self._transcript.append_message(f"\x1b[32m✓\x1b[0m 已恢复对话: {title_short}")
        self._on_conversation_resumed(cid, thread_id, title_short)

    def _on_conversation_resumed(self, conversation_id: str, thread_id: str, title: str) -> None:
        """恢复指定对话：切换 thread_id + 激活对话 + 重建 bridge。

        下一次用户输入将自动续写该对话的 checkpoint。
        """
        import os as _os

        # 设置环境变量供 audit sink 和 _resolve_thread_id 使用
        _os.environ["IST_CONVERSATION_ID"] = conversation_id

        # 切换 thread_id（下一次 _run_via_bridge 会用此创建新 bridge）
        self._thread_id = thread_id
        self.tui_state.__dict__["thread_id"] = thread_id

        # 销毁旧 bridge（下次 submit 时会重建，thread_id 指向恢复的对话）
        if self._bridge is not None:
            try:
                self._bridge.cancel()
            except Exception:
                pass
            self._bridge = None

        # 尝试从 PG 激活该对话
        try:
            from main.ist_core.auth.session_manager import SessionManager
            mgr = SessionManager()
            mgr.activate_conversation(self._username, conversation_id)
        except Exception:
            pass

        self._app.render()

    # ── 原 append_transcript_info ────────────────────────────────────────

    def append_transcript_info(self, msg: str) -> None:
        """Thread-safe: append a status line to transcript (used by kms_command)."""
        with self._app.lock:
            self._transcript.append_message(f"  \x1b[2m{msg}\x1b[0m")
            self._app.render()

    def set_background_status(self, text: str | None) -> None:
        """Thread-safe: update the thinking line above input (used by kms_command)."""
        with self._app.lock:
            self._update_thinking_line(text)
            self._app.render()

    def _cancel_query(self) -> None:
        """Cancel the running query and stop the bridge thread."""
        if self._bridge and self._bridge.is_running:
            
            
            self._bridge.cancel()
        self._is_loading = False
        self._streaming_buf.clear()
        self._transcript.append_message(" \x1b[2m[interrupted]\x1b[0m")
        self._footer.update(status="ready")
        self._app.render()

    def _toggle_expand(self) -> None:
        """Ctrl+O:展开/折叠所有工具输出(主路径 + fork 子 agent 行)。

        fork 行交织(多 worker 并发)+ 折叠改行数,无法就地增量改,从最新 snapshot 全量重渲染——
        reducer._messages 只增长(整个 run 期间不清理),fork inner block 的 parent_tool_use_id
        随 message 一起保留在 snapshot.messages 里,故重渲染时 _render_subagent_inner_block 能
        在 _tool_outputs_expanded=True 时把每个 parent 的全部 inner block 都渲染出来(该函数本
        身按 expanded 决定是否跳过截断,不依赖任何"记住哪些行被省略"的额外状态)。
        """
        self._tool_outputs_expanded = not self._tool_outputs_expanded
        self._persist_verbose()
        self._replay_snapshot()

    def _replay_snapshot(self) -> None:
        """从最新 snapshot 全量重渲染 transcript(按当前 _tool_outputs_expanded / _thinking_expanded)。

        见 tests/tui/test_ist_app_replay_snapshot.py:用真实 parent_tool_use_id 消息构造 snapshot,
        断言 expanded 模式下 fork 行数 == 实际 inner block 数(不被 3 行截断丢弃)。
        """
        snap = getattr(self, "_prev_snapshot", None)
        if snap is None or not getattr(snap, "messages", None):
            return
        # 清空 + 重置所有增量渲染累积状态(与 run 开始 reset 对齐),再全量重走渲染逻辑
        self._transcript.clear()
        self._subagent_inner_summaries = {}
        self._subagent_thinking_lines = []
        self._main_thinking_lines = []
        self._tool_output_blocks = []
        self._tool_use_row = {}
        self._ai_stream_idx = -1
        self._stream_commit_idx = -1
        self._last_thinking_idx = -1
        self._last_thinking_text = ""
        for msg in snap.messages:
            for block in getattr(msg, "content", None) or []:
                self._render_content_block(block, msg)
        self._app.render()

    def _load_tui_config(self) -> None:
        """从 ~/.ist/tui_config.json 恢复持久化状态。"""
        try:
            import json
            config_file = Path.home() / ".ist" / "tui_config.json"
            if config_file.exists():
                data = json.loads(config_file.read_text())
                self._tool_outputs_expanded = bool(data.get("verbose", False))
                self._thinking_expanded = bool(data.get("thinking_expanded", False))
        except Exception:  # noqa: BLE001
            pass

    def _persist_verbose(self) -> None:
        """保存 verbose 状态到 ~/.ist/tui_config.json。"""
        try:
            import json
            config_dir = Path.home() / ".ist"
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / "tui_config.json"
            data = {}
            if config_file.exists():
                data = json.loads(config_file.read_text())
            data["verbose"] = self._tool_outputs_expanded
            data["thinking_expanded"] = self._thinking_expanded
            config_file.write_text(json.dumps(data))
        except Exception:  # noqa: BLE001
            pass

    def _toggle_thinking(self) -> None:
        """Toggle thinking blocks (Ctrl+T):主 agent 的**所有** thinking 行 + fork 子 agent 的 ⎿ ∴ Thinking 行。"""
        D = self._DIM
        X = self._RESET
        self._thinking_expanded = not self._thinking_expanded
        self._persist_verbose()
        # 主 agent 的**所有** thinking 行（不只最后一条）——就地折叠/展开
        for rec in getattr(self, "_main_thinking_lines", []):
            if self._thinking_expanded:
                new_line = f" {D}\x1b[3m∴ {rec['full']}{X}"
            else:
                new_line = f" {D}\x1b[3m∴ Thinking{X} {D}(ctrl+t to expand){X}"
            self._transcript.update_message_at(rec["idx"], new_line)
        # fork 子 agent 的 ⎿ ∴ Thinking 行:就地展开全文 / 折回占位(不改行数,故 idx 稳定)
        for rec in getattr(self, "_subagent_thinking_lines", []):
            if self._thinking_expanded:
                nl = f"   {D}\x1b[3m⎿ ∴ {rec['full']}{X}"
            else:
                nl = f"   {D}⎿ ∴ Thinking{X}"
            self._transcript.update_message_at(rec["idx"], nl)
        self._app.render()

    def _history_up(self) -> None:
        result = self._input_history.up(self._prompt.value)
        if result is not None:
            self._prompt.set_value(result)

    def _history_down(self) -> None:
        result = self._input_history.down(self._prompt.value)
        if result is not None:
            self._prompt.set_value(result)
        else:
            self._prompt.clear()

    def _tab_complete(self) -> None:
        """Tab completion for slash commands."""
        val = self._prompt.value
        if not val.startswith("/"):
            return
        from main.ist_core.tui.slash_commands import BUILTIN_COMMANDS
        prefix = val[1:].lower()
        matches = [cmd for cmd in BUILTIN_COMMANDS if cmd.name.lower().startswith(prefix)]
        if not matches:
            return
        if len(matches) == 1:
            self._prompt.set_value(f"/{matches[0].name} ")
        else:
            
            names = "  ".join(f"/{m.name}" for m in matches[:8])
            self._footer._hint_line.set_value(f" {names}  [Tab to fill · Enter to run]")
            self._prompt.set_value(f"/{matches[0].name} ")
        self._app.render()
