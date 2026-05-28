"""规则抽取（hot path）+ fork agent 输入格式化。

参考实现：
- Claude Code src/services/extractMemories/ 的两阶段抽取（规则浓缩 + LLM 升级）
- main/qa_agent/graph._MainAgentProgressHandler 已经能识别 thinking/tool_call/text block
- 本仓库 graph.py:131-155 的 message content block 解析逻辑

为什么分两层：
1. extract_working_entry 只跑规则，毫秒级，每轮都跑——L1 工作记忆主要是"工具命中清单"
2. format_extraction_input 把对话压扁喂给 fork agent，让它判断"是否升级到 L2/L3"
"""

from __future__ import annotations

import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)


_THOUGHT_MAX = 600
_TOOL_OUT_MAX = 200
_TOOL_INPUT_MAX = 200


def _ai_text_and_thought(msg: AIMessage) -> tuple[str, list[dict[str, Any]]]:
    """从 AIMessage 抽取（纯文本, tool_calls 列表）。

    复用 graph.py:131-155 的解析逻辑：content 可能是 str / list[block dict]，
    后者含 type=text/thinking/tool_use 三种块。
    """
    content = getattr(msg, "content", "")
    text_parts: list[str] = []
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "text":
                    t = block.get("text") or ""
                    if t:
                        text_parts.append(t)
            elif isinstance(block, str):
                text_parts.append(block)
    text = "\n".join(text_parts).strip()

    tool_calls = list(getattr(msg, "tool_calls", None) or [])
    return text, tool_calls


def _truncate(s: str, n: int) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


def _normalize_tool_input(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        s = raw
    elif isinstance(raw, dict):
        # 抽前几个 kv 拼成单行
        parts = []
        for k, v in list(raw.items())[:5]:
            v_str = str(v)
            if len(v_str) > 80:
                v_str = v_str[:77] + "..."
            parts.append(f"{k}={v_str}")
        s = ", ".join(parts)
    else:
        s = str(raw)
    s = " ".join(s.split())
    return _truncate(s, _TOOL_INPUT_MAX)


def extract_working_entry(messages: list[BaseMessage]) -> str:
    """从最后一条 AIMessage 抽出 working 笔记。

    after_model 触发时 messages 末尾两种形态：
    1. AIMessage(tool_calls=...) —— LLM 决定调工具，工具还没跑
       → 抓 AIMessage 自己的 thought + tool_calls 列表
    2. AIMessage(text) —— LLM 给最终回答，前面是 ToolMessage 结果
       → 抓 AIMessage 自己的 thought + 它之前连续的 ToolMessage

    返回带时间戳的多行 markdown 片段。无可用片段时返回 ""。
    """
    if not messages:
        return ""

    # 找最后一条 AIMessage
    last_ai_idx: int | None = None
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            last_ai_idx = i
            break
    if last_ai_idx is None:
        return ""

    ai = messages[last_ai_idx]
    text, tool_calls = _ai_text_and_thought(ai)

    # 它之前连续的 ToolMessage（形态 2）
    preceding_tools: list[ToolMessage] = []
    j = last_ai_idx - 1
    while j >= 0 and isinstance(messages[j], ToolMessage):
        preceding_tools.append(messages[j])
        j -= 1
    preceding_tools.reverse()

    lines: list[str] = []
    if text:
        thought = _truncate(" ".join(text.split()), _THOUGHT_MAX)
        lines.append(f"- thought: {thought}")

    # 形态 2：tool_call 已经在前面的 AIMessage 里，找前一条 AIMessage 取 tool_calls 配对
    prior_tc_by_id: dict[str, dict[str, Any]] = {}
    if preceding_tools and j >= 0 and isinstance(messages[j], AIMessage):
        _, prior_tcs = _ai_text_and_thought(messages[j])
        for tc in prior_tcs:
            if isinstance(tc, dict):
                tid = tc.get("id") or tc.get("tool_call_id") or ""
                if tid:
                    prior_tc_by_id[tid] = tc

    for tm in preceding_tools:
        tname = getattr(tm, "name", "") or ""
        tid = getattr(tm, "tool_call_id", "") or ""
        out = getattr(tm, "content", "")
        if not isinstance(out, str):
            out = str(out)
        out_short = _truncate(" ".join((out or "").split()), _TOOL_OUT_MAX)
        tc = prior_tc_by_id.get(tid, {})
        args = tc.get("args") if isinstance(tc, dict) else None
        in_short = _normalize_tool_input(args)
        if in_short:
            lines.append(f"- tool: {tname}({in_short}) → {out_short}")
        else:
            lines.append(f"- tool: {tname} → {out_short}")

    # 形态 1：AIMessage 自己有 tool_calls，记录将要调用的工具
    for tc in tool_calls:
        if isinstance(tc, dict):
            name = tc.get("name") or ""
            args = _normalize_tool_input(tc.get("args"))
            lines.append(f"- pending tool_call: {name}({args})")

    if not lines:
        return ""

    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return f"\n## turn {ts}\n" + "\n".join(lines)


def format_extraction_input(
    messages: list[BaseMessage], *, tail_n: int = 8
) -> str:
    """把最近 tail_n 条消息压扁，作为 fork agent 的 user 输入。

    fork agent 只读这一段就要决定是否 upsert /memories/。
    """
    if not messages:
        return "(no recent messages)"
    tail = messages[-tail_n:]
    lines: list[str] = []
    for m in tail:
        if isinstance(m, HumanMessage):
            c = m.content if isinstance(m.content, str) else str(m.content)
            # 跳过自身注入的 reminder（含 <system-reminder> 或 <memory-context>）
            if "<system-reminder>" in c or "<memory-context>" in c:
                continue
            lines.append(f"USER: {_truncate(c, 800)}")
        elif isinstance(m, AIMessage):
            text, tool_calls = _ai_text_and_thought(m)
            if text:
                lines.append(f"AI: {_truncate(text, 800)}")
            for tc in tool_calls:
                if isinstance(tc, dict):
                    name = tc.get("name") or ""
                    args = _normalize_tool_input(tc.get("args"))
                    lines.append(f"AI(tool_call): {name}({args})")
        elif isinstance(m, ToolMessage):
            name = getattr(m, "name", "") or ""
            content = m.content if isinstance(m.content, str) else str(m.content)
            lines.append(f"TOOL[{name}]: {_truncate(content, 400)}")
    return "\n".join(lines) if lines else "(no recent messages)"


__all__ = ["extract_working_entry", "format_extraction_input"]
