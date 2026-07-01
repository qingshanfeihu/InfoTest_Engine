"""主循环连接韧性 + 健康心跳（V3 配套：治 V2 验收 run 主 agent APIConnectionError 崩溃）。

V2 验收实测：61 draft + 60 grade 全完成，但主 agent 在 graph.invoke 中途遇
APIConnectionError（端点连接被持续掐断）崩溃，未到合并阶段 → 0 产出。
模型层 max_retries=2 只覆盖单次 API 调用，主循环跑数小时遇到的**持续性**连接抖动
（端点重启/网络分区）会耗尽重试后向上抛，整个编排崩。

本模块提供：
1. run_with_resilience：把 graph.invoke 包一层**外层重试**，遇连接类错误指数退避重跑，
   不让一次抖动毁掉整轮编排。
2. Heartbeat：后台线程定时把"还活着 + 已跑多久"写到心跳文件，供外部监控判断进程
   是卡死还是在正常跑（长 LLM 往返时 CPU 近 0，纯靠进程在不在不够）。

两者都可 env 关闭，默认开。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 主循环外层重试默认值（env 可覆盖）。
_DEFAULT_OUTER_RETRIES = 3
_DEFAULT_OUTER_BASE_SLEEP = 5.0

# 连接类错误标志（跨 SDK 靠消息匹配兜底；APIConnectionError/Connection error 等）。
_CONNECTION_MARKERS = (
    "apiconnectionerror", "connection error", "connection aborted",
    "connection reset", "connection refused", "remote end closed",
    "max retries exceeded", "read timed out", "timed out", "temporarily unavailable",
    "bad gateway", "service unavailable", "gateway timeout",
    # 不放裸 "502"/"503"/"504"——会误中 autoid/IP/计数等任意含该子串的文本
    # （如 autoid 203031754291994957 里的 "4291"）；HTTP 5xx 文字描述上面已覆盖。
)


def _is_connection_error(exc: BaseException) -> bool:
    s = f"{type(exc).__name__}: {exc}".lower()
    return any(m in s for m in _CONNECTION_MARKERS)


# transient 端点压力标志：在连接类之外补上**流式协议中断 + 限流 + 过载**。
# 16 并发 draft 把端点压垮时常见 RemoteProtocolError("peer closed connection ...
# incomplete chunked read") / 429 / overloaded——这些都该触发"降并发 + 退避重试"，
# 而非当成 draft 质量失败。
_TRANSIENT_EXTRA_MARKERS = (
    "remoteprotocol", "peer closed connection", "incomplete chunked",
    # 不放裸 "429"——同理误中数字子串；限流用下面的文字描述兜。
    "rate limit", "too many requests", "overloaded", "incompleteread",
)


def is_transient_error(text_or_exc) -> bool:
    """端点 transient 压力判定（连接抖动 + 流中断 + 限流 + 过载）。

    入参可为异常或 execute_fork_skill 返回的 'ERROR: ...' 字符串（fork 把异常吞成串了）。
    供自适应并发限流器决定"降并发 + 退避重试" vs "真失败"。
    """
    if isinstance(text_or_exc, BaseException):
        s = f"{type(text_or_exc).__name__}: {text_or_exc}".lower()
    else:
        s = str(text_or_exc or "").lower()
    return (any(m in s for m in _CONNECTION_MARKERS)
            or any(m in s for m in _TRANSIENT_EXTRA_MARKERS))


class AdaptiveLimiter:
    """AIMD 自适应并发限流器：端点健康就缓升并发，丢连接/限流就骤降（减半）。

    类比 TCP 拥塞控制——加性增（连续成功才 +1，慢升不冲爆）、乘性减（一遇 transient 折半）。
    用它替代"手动调 IST_FANOUT_CONCURRENCY"：随端点实时健康自动伸缩，压垮就退、恢复就进。

    用法：
        lim = AdaptiveLimiter(start=8, min_limit=1, max_limit=16)
        with lim:                       # 阻塞直到有名额
            out = call_llm()
            if is_transient_error(out): lim.record_overload()
            else:                       lim.record_success()
    """

    def __init__(self, start: int, min_limit: int = 1, max_limit: int = 16):
        self.min = max(1, int(min_limit))
        self.max = max(self.min, int(max_limit))
        self.limit = max(self.min, min(int(start), self.max))
        self._active = 0
        self._succ = 0
        self._cv = threading.Condition()
        self.history: list[str] = []   # 限流变化轨迹（可观测）

    def acquire(self) -> None:
        with self._cv:
            while self._active >= self.limit:
                self._cv.wait(timeout=1.0)   # 周期性复检（limit 可能被调高）
            self._active += 1

    def release(self) -> None:
        with self._cv:
            self._active = max(0, self._active - 1)
            self._cv.notify()

    def __enter__(self) -> "AdaptiveLimiter":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def record_success(self) -> None:
        with self._cv:
            self._succ += 1
            # 加性增：连续成功数 ≥ 当前 limit 才 +1（慢升，避免又冲爆端点）
            if self._succ >= self.limit and self.limit < self.max:
                self.limit += 1
                self._succ = 0
                self.history.append(f"↑{self.limit}")
                self._cv.notify()

    def record_overload(self) -> None:
        with self._cv:
            new = max(self.min, self.limit // 2)   # 乘性减
            if new != self.limit:
                self.limit = new
                self.history.append(f"↓{self.limit}")
            self._succ = 0
            # 不 notify：要的是更少并发，让在飞的自然回落到新 limit

    @property
    def current(self) -> int:
        return self.limit


def _resolve_outer_retries() -> tuple[int, float]:
    try:
        n = int(os.environ.get("IST_MAINLOOP_RETRIES") or _DEFAULT_OUTER_RETRIES)
    except (TypeError, ValueError):
        n = _DEFAULT_OUTER_RETRIES
    try:
        base = float(os.environ.get("IST_MAINLOOP_RETRY_SLEEP") or _DEFAULT_OUTER_BASE_SLEEP)
    except (TypeError, ValueError):
        base = _DEFAULT_OUTER_BASE_SLEEP
    return max(0, n), max(0.5, base)


def run_with_resilience(fn: Callable[[], Any], *, label: str = "mainloop") -> Any:
    """执行 fn（通常是 graph.invoke），遇连接类错误指数退避外层重跑。

    非连接类错误（业务异常/编程错误）立即上抛，不重试——只对端点连接抖动兜底。
    env IST_MAINLOOP_RETRIES=0 可关闭外层重试（退回原行为）。
    """
    retries, base = _resolve_outer_retries()
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 — 需拦截连接类一切异常
            last_exc = exc
            if not _is_connection_error(exc):
                raise
            if attempt >= retries:
                logger.error("%s 连接重试耗尽(%d 次)，上抛: %s", label, retries, exc)
                raise
            sleep_s = base * (2 ** attempt)
            logger.warning("%s 遇连接类错误，第 %d/%d 次外层重试，退避 %.0fs: %s",
                           label, attempt + 1, retries, sleep_s, exc)
            time.sleep(sleep_s)
    if last_exc:
        raise last_exc


class Heartbeat:
    """后台心跳：定时把"存活 + 已运行秒数 + 自定义 note"写到心跳文件。

    供外部监控区分"进程在正常跑长 LLM 往返(CPU 近 0 但活着)" vs "卡死"。
    心跳文件含 mtime——监控只要看 mtime 是否在推进即可判活。env IST_HEARTBEAT=0 关闭。
    """

    def __init__(self, path: str | Path | None = None, interval_s: float = 30.0):
        default = Path(__file__).resolve().parents[1] / "runtime" / "logs" / "heartbeat.json"
        self.path = Path(path or os.environ.get("IST_HEARTBEAT_PATH") or default)
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_ts = 0.0
        self._note = ""
        self._enabled = os.environ.get("IST_HEARTBEAT", "1") == "1"

    def set_note(self, note: str) -> None:
        self._note = note

    def _write(self) -> None:
        import json
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                "pid": os.getpid(),
                "alive": not self._stop.is_set(),
                "elapsed_s": round(time.monotonic() - self._start_ts, 1),
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "note": self._note,
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001 — 心跳绝不能影响主流程
            pass

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._write()

    def __enter__(self) -> "Heartbeat":
        if not self._enabled:
            return self
        self._start_ts = time.monotonic()
        self._write()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="ist-heartbeat")
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        if not self._enabled:
            return
        self._stop.set()
        self._write()
        if self._thread:
            self._thread.join(timeout=2)


# ── 主 agent 活动日志（治"卡在 prep 之后看不见主 agent 在干嘛"的盲区）──────────
# heartbeat 只说"活着"、fork_status 只记子 agent fork；主 agent 自己每一步 tool 调用
# 之前只 emit 到 event bus（print 模式丢弃）→ 长跑卡住时完全看不见主 agent 时间线。
# 这里把主 agent 每个 tool_call 落成 durable JSONL（崩溃/卡死后可回放主 agent 干了什么）。

_MAIN_ACTIVITY_PATH = os.environ.get("IST_MAIN_ACTIVITY_LOG") or str(
    Path(__file__).resolve().parents[1] / "runtime" / "logs" / "main_activity.jsonl"
)

# 进程内引用当前 Heartbeat，便于主 agent tool_call 时同步更新 note（当前阶段可见）。
_ACTIVE_HEARTBEAT: "Heartbeat | None" = None


def set_active_heartbeat(hb: "Heartbeat | None") -> None:
    global _ACTIVE_HEARTBEAT
    _ACTIVE_HEARTBEAT = hb


def record_main_activity(event: str, tool_name: str = "", detail: str = "") -> None:
    """把主 agent 的一次活动（tool_call 起/止）落 durable JSONL，并刷新 heartbeat note。

    event: 'tool_start' | 'tool_end' | 其他阶段标记。失败静默，绝不影响主流程。
    """
    if os.environ.get("IST_MAIN_ACTIVITY", "1") != "1":
        return
    try:
        import json as _json
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            "tool": tool_name,
            "detail": (detail or "")[:200],
        }
        p = Path(_MAIN_ACTIVITY_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass
    # 同步刷新 heartbeat 的 note：让外部看心跳就知道主 agent 当前在调哪个 tool。
    try:
        if _ACTIVE_HEARTBEAT is not None and event == "tool_start" and tool_name:
            _ACTIVE_HEARTBEAT.set_note(f"tool={tool_name}")
    except Exception:  # noqa: BLE001
        pass
