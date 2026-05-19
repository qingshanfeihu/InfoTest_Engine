"""TUI 内部 reactive 状态容器。

不是 LangGraph state（那是 graph 内部）；这是 Textual UI 侧的轻量持有者，跟踪
当前 thread_id、累计 token usage、phase、运行状态等，供 widgets 订阅。


Python 等价物：Textual 的 reactive 字段挂在 App 上，外部用 dataclass 封装传递。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TuiState:
    """TUI 全局可变状态。Textual App 持有一个实例，widget 通过 app.tui_state 读。"""

    #: 当前 LangGraph thread_id（HIL 续跑全程不变）
    thread_id: str = ""

    #: 当前活跃 run_id（每次新 run 由 EventBus 发的 run_start 事件填充）
    run_id: str = ""

    #: 当前 phase（reviewer 用 phase_marker；通用 agent 用最近 node_start.name 兜底）
    phase: str = "idle"

    #: 累计 token 使用量
    tokens_used: int = 0

    #: Token 预算（DashScope qwen-plus 上下文窗口约 128k；StatusBar 计算占用率）
    tokens_budget: int = 128000

    #: 是否处于流式 LLM 输出中
    streaming: bool = False

    #: 累计 LLM 调用次数（ProgressTrail 用）
    llm_calls: int = 0

    #: 累计工具调用次数（ProgressTrail 用）
    tool_calls: int = 0

    #: 最近 8 条日志（ProgressTrail Tail Log 显示）
    log_tail: list[str] = field(default_factory=list)

    def reset_run(self, run_id: str = "") -> None:
        """新 run 开始时重置 per-run 计数器，但保留 thread_id 和 token budget。"""
        self.run_id = run_id
        self.phase = "running"
        self.streaming = False
        self.llm_calls = 0
        self.tool_calls = 0
        self.log_tail.clear()

    def append_log(self, line: str, *, max_keep: int = 8) -> None:
        self.log_tail.append(line)
        if len(self.log_tail) > max_keep:
            del self.log_tail[: len(self.log_tail) - max_keep]
