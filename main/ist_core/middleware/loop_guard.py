"""Loop guard middleware — 死循环 / 空转护栏.

为什么需要这个 middleware：
- LangGraph 的 ``recursion_limit`` 只是粗粒度兜底（数 graph 步数，主 agent 设 300
  ≈ 100+ LLM turn），且超限是 raise 异常而非优雅收尾。实际死循环往往在 20~30
  turn 就已经"原地复读"——反复发相同 grep、连续 no matches，却远不触发 300。
- 对照业界 agent 框架：常见做法是分层 maxTurns 硬上限 + prompt 约束兜底，没有代码级指纹去重。
  本 middleware 做更精准的两件事，**纯 prompt 注入、不强杀**，保持优雅收敛：
    1. 重复工具调用检测：最近窗口内同一 (tool_name + 规范化 args) 指纹出现 ≥ 阈值
       （窗口频次，能抓住 A/B/A/B 交替空转，不止连续重复），注入打断 reminder。
    2. 连续空结果检测：最近窗口内 grep/read 空命中（no matches）数 ≥ 阈值。
    3. 软 turn 预算：本轮 user query 以来的 tool_call 总数超阈值，注入收敛提醒。

实现要点（与 PerTurnSkillReminderMiddleware 对齐）：
- 用 ``wrap_model_call`` hook 改 ``ModelRequest.messages``（**不持久化到 state**）。
  绝不 ``before_model`` 返回 {"messages": [...]}——那会被 add_messages reducer
  持久化为对话历史，reminder 被当成"用户新输入"反而加剧死循环。
- 每次只往 per-call messages 副本插一条 system-reminder，离当前 reasoning 最近。
- 检测基于**最近 N 个工具调用的滑动窗口**：模型一旦改变行为（换关键词 / 收敛），
  旧的重复调用滑出窗口，检测自然复位、不再提醒；若模型无视提醒继续空转，则每轮
  重新提醒（这是期望的兜底行为），最终由 recursion_limit 硬上限收口。

关键 env：
- ``IST_LOOP_GUARD_ENABLED``（默认 1）— 总开关
- ``IST_LOOP_DUP_THRESHOLD``（默认 3）— 最近窗口内同一指纹出现多少次触发打断
- ``IST_LOOP_EMPTY_THRESHOLD``（默认 4）— 最近窗口内空结果多少次触发打断
- ``IST_LOOP_SOFT_BUDGET``（默认 25）— 本轮 tool_call 软预算，超出注入收敛提醒
- ``IST_LOOP_WINDOW``（默认 8）— 检测滑动窗口大小（最近多少个工具调用 / 结果）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _enabled() -> bool:
    return (os.environ.get("IST_LOOP_GUARD_ENABLED", "1") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


# 空结果标记：file_tools.py grep/glob 无命中返回 "(no matches)"；read 失败返回
# path-not-found / empty 等。命中任一即视为"该工具调用无新信息"。
_EMPTY_MARKERS = (
    "(no matches)",
    "no matches",
    "path not found",
    "file empty",
    "(empty)",
    "未找到",
)

_REMINDER_TAG = "loop-guard"


def _msg_content_str(content: Any) -> str:
    """把 message.content（可能是 str 或 list[block]）规整成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", "") or "")
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content or "")


def _tool_call_fingerprint(name: str, args: Any) -> str:
    """对 (tool_name + 规范化 args) 取稳定指纹。

    args 里的 pattern/path/glob 是判定"是否同一搜索"的关键；用 sort_keys 的
    JSON 序列化消除 key 顺序差异，再 sha1 取短码。
    """
    try:
        norm = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        norm = str(args)
    raw = f"{name}::{norm}"
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:16]


def _is_empty_result(content: str) -> bool:
    """判断工具结果是否"无新信息"（空 / no matches / path not found）。

    只对**短结果**做 marker 子串判断——长结果（>200 字符）即便正文恰好含
    "未找到" / "no matches" 字样（如评审材料引用、文档解释正则），也显然不是
    空结果，避免假阳性抬高 empty 计数。
    """
    low = content.strip().lower()
    if not low:
        return True
    if len(low) > 200:
        return False
    for marker in _EMPTY_MARKERS:
        if marker.lower() in low:
            return True
    return False


def _last_human_index(messages: list) -> int:
    """找到最后一条"真实用户输入"的下标（跳过 system-reminder / memory-context 注入的 Human）。

    PerTurnSkillReminder / 本 middleware / MemoryInjection 注入的 reminder 也是
    HumanMessage，但 content 以 ``<system-reminder`` 开头（注意可能带属性，如
    ``<system-reminder data-source="loop-guard">``，故用前缀匹配不带 ``>``）或含
    ``<memory-context>``。真实 user query 不会。用这个区分本轮起点。
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, HumanMessage):
            text = _msg_content_str(msg.content).lstrip()
            if text.startswith("<system-reminder"):
                continue
            if text.startswith("<memory-context") or "<memory-context>" in text[:80]:
                continue
            return i
    return 0


def _analyze(messages: list, *, window: int) -> dict[str, Any]:
    """扫描本轮（最后一条真实 user query 之后）的工具调用，返回统计。

    用**滑动窗口频次**而非"末尾连续"——能抓住 A/B/A/B 交替空转这类原地打转，
    不止连续重复。模型一旦改变行为，旧调用滑出窗口，计数自然下降。

    Returns dict:
      - tool_call_count: 本轮 tool_call 总数（用于软预算）
      - dup_count: 最近 window 个调用里出现最多的那个指纹的次数
      - dup_label: 该高频指纹对应的 tool 名 + 关键参数（给提醒用）
      - empty_count: 最近 window 个工具结果里的空结果数
    """
    start = _last_human_index(messages)
    win = messages[start:]

    fingerprints: list[str] = []
    labels: dict[str, str] = {}
    empty_flags: list[bool] = []
    tool_call_count = 0

    for msg in win:
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            for tc in tcs:
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                fp = _tool_call_fingerprint(name, args)
                fingerprints.append(fp)
                tool_call_count += 1
                # 关键参数 label（pattern / path）
                if isinstance(args, dict):
                    key_bits = []
                    for k in ("pattern", "query", "file_path", "path", "glob"):
                        if args.get(k):
                            key_bits.append(f"{k}={args[k]}")
                    labels[fp] = f"{name}({', '.join(key_bits)})" if key_bits else name
                else:
                    labels[fp] = name

        # ToolMessage：标记结果是否为空
        if getattr(msg, "type", "") == "tool" or msg.__class__.__name__ == "ToolMessage":
            content = _msg_content_str(getattr(msg, "content", ""))
            empty_flags.append(_is_empty_result(content))

    # 最近 window 个调用里的最高频指纹
    recent_fps = fingerprints[-window:]
    dup_count = 0
    dup_label = ""
    if recent_fps:
        counts: dict[str, int] = {}
        for fp in recent_fps:
            counts[fp] = counts.get(fp, 0) + 1
        top_fp = max(counts, key=lambda k: counts[k])
        dup_count = counts[top_fp]
        dup_label = labels.get(top_fp, "")

    # 最近 window 个结果里的空结果数
    empty_count = sum(1 for flag in empty_flags[-window:] if flag)

    return {
        "tool_call_count": tool_call_count,
        "dup_count": dup_count,
        "dup_label": dup_label,
        "empty_count": empty_count,
    }


def _build_reminder(stats: dict[str, Any], *, dup_thr: int, empty_thr: int, soft_budget: int) -> str | None:
    dup_count = stats["dup_count"]
    empty_count = stats["empty_count"]
    count = stats["tool_call_count"]
    label = stats["dup_label"]

    triggers: list[str] = []
    if dup_count >= dup_thr:
        triggers.append(
            f"你最近 {dup_count} 次发起了**相同的工具调用**"
            + (f"（{label}）" if label else "")
            + "，参数没变、结果也不会变。"
        )
    if empty_count >= empty_thr:
        triggers.append(
            f"最近 {empty_count} 次搜索**无命中**（no matches / 空结果）。"
        )
    budget_hit = count >= soft_budget and not triggers
    if budget_hit:
        triggers.append(
            f"本轮已发起 {count} 次工具调用仍未收敛。"
        )

    if not triggers:
        return None

    body = " ".join(triggers)
    return (
        f"<system-reminder data-source=\"{_REMINDER_TAG}\">\n"
        f"⚠ 循环护栏：{body}\n\n"
        "停止重复尝试。Don't retry the identical action blindly——立刻改变策略，三选一：\n"
        "1. **收敛输出**：基于已经找到的材料给出结论；对未在文档命中的部分，"
        "如实标注「知识库未找到 / 未在文档直接命中」，给出基于现有证据的最佳判断，"
        "不要假装找到了。\n"
        "2. **升级检索**：若确实需要更广的搜索，改用 explore 子代理或换不同的关键词/路径，"
        "不要原样重发同一个 grep。\n"
        "3. **向用户澄清**：若信息缺口必须用户补充，用 ask_user 提问。\n"
        "继续重复相同的无效搜索是不允许的。\n"
        "</system-reminder>"
    )


class LoopGuardMiddleware(AgentMiddleware):
    """检测重复工具调用 / 连续空结果 / 软预算超限，注入收敛 reminder。

    纯 per-call messages 注入，不写回 state（避免 reminder 被当成用户输入而加剧
    死循环——与 PerTurnSkillReminderMiddleware 同一约束）。
    """

    def __init__(
        self,
        *,
        dup_threshold: int | None = None,
        empty_threshold: int | None = None,
        soft_budget: int | None = None,
        window: int | None = None,
    ) -> None:
        self._dup_thr = dup_threshold if dup_threshold is not None else _env_int("IST_LOOP_DUP_THRESHOLD", 3)
        self._empty_thr = empty_threshold if empty_threshold is not None else _env_int("IST_LOOP_EMPTY_THRESHOLD", 4)
        self._soft_budget = soft_budget if soft_budget is not None else _env_int("IST_LOOP_SOFT_BUDGET", 25)
        self._window = window if window is not None else _env_int("IST_LOOP_WINDOW", 8)

    def _maybe_reminder_messages(self, request: ModelRequest) -> list:
        messages = request.messages
        if not _enabled():
            return list(messages)
        try:
            stats = _analyze(messages, window=self._window)
        except Exception as exc:  # noqa: BLE001
            logger.debug("loop_guard analyze 失败，跳过: %s", exc)
            return list(messages)

        reminder_text = _build_reminder(
            stats,
            dup_thr=self._dup_thr,
            empty_thr=self._empty_thr,
            soft_budget=self._soft_budget,
        )
        if not reminder_text:
            return list(messages)

        logger.info(
            "loop_guard 触发: dup_count=%s empty_count=%s tool_calls=%s",
            stats["dup_count"], stats["empty_count"], stats["tool_call_count"],
        )
        new_msgs = list(messages)
        new_msgs.append(HumanMessage(content=reminder_text))
        return new_msgs

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        modified = request.override(messages=self._maybe_reminder_messages(request))
        return handler(modified)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        modified = request.override(messages=self._maybe_reminder_messages(request))
        return await handler(modified)


__all__ = ["LoopGuardMiddleware"]
