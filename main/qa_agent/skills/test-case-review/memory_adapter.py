"""评审场景 Memory 适配层。

通用层（middleware.py）接受回调实现业务定制。本模块提供评审专用的：
- review_query_extractor: 从 messages 提取检索 query
- review_key_resolvers: 返回直接读取路径列表
- review_finalizer: 检测评审结束 + 蒸馏 findings

核心 key 用"用例文件名"（评审输入必有），ticket_id 是可选元数据。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main.qa_agent.memory.store import MemoryStore

logger = logging.getLogger(__name__)

_TICKET_RE = re.compile(
    r"(BUG|ZT|STORY|PLM|JIRA|ISSUE)[-_](\d+)", re.IGNORECASE
)
_CASE_FILE_RE = re.compile(
    r"Test\s*List[^/]*?(\d{4,})[^/]*\.(?:md|xlsx)", re.IGNORECASE
)


def _extract_ticket_id(messages: list) -> str | None:
    """从 messages 倒序找 ticket id（BUG-121100 / ZT-456 等）。"""
    from langchain_core.messages import HumanMessage, ToolMessage

    for m in reversed(messages or []):
        text = ""
        if isinstance(m, HumanMessage):
            text = m.content if isinstance(m.content, str) else str(m.content)
        elif isinstance(m, ToolMessage):
            text = m.content if isinstance(m.content, str) else str(m.content)
        if text:
            match = _TICKET_RE.search(text)
            if match:
                return f"{match.group(1).upper()}-{match.group(2)}"
    return None


def _extract_case_filename(messages: list) -> str | None:
    """从 messages 提取用例文件名标识（如 'cookie121100'）。"""
    from langchain_core.messages import HumanMessage

    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            text = m.content if isinstance(m.content, str) else str(m.content)
            match = _CASE_FILE_RE.search(text)
            if match:
                return f"case_{match.group(1)}"
            if "knowledge/data/markdown/qa/" in text:
                parts = text.split("knowledge/data/markdown/qa/")
                if len(parts) > 1:
                    fname = parts[1].split()[0].strip("'\"")
                    slug = re.sub(r"[^\w]", "_", fname.replace(".md", ""))[:60]
                    return slug
    return None


# ----------------------------------------------------------------------
# 通用回调接口实现
# ----------------------------------------------------------------------


def review_query_extractor(messages: list) -> str:
    """从 messages 提取检索 query：ticket id + 用例文件关键词。"""
    parts = []
    ticket = _extract_ticket_id(messages)
    if ticket:
        parts.append(ticket)
    case = _extract_case_filename(messages)
    if case:
        parts.append(case)
    if not parts:
        from langchain_core.messages import HumanMessage
        for m in reversed(messages or []):
            if isinstance(m, HumanMessage):
                text = m.content if isinstance(m.content, str) else str(m.content)
                if len(text) > 10:
                    parts.append(text[:100])
                    break
    return " ".join(parts)


def review_key_resolvers(messages: list) -> list[tuple[str, str]]:
    """返回 [(namespace, key)] 列表。

    评审场景三种 key（按优先级）：
    1. cases/<case_filename>/findings.md — 必有
    2. tickets/<ticket_id>/findings.md — 可选
    3. users/default/preferences.md — 始终
    """
    keys: list[tuple[str, str]] = []

    case_file = _extract_case_filename(messages)
    if case_file:
        keys.append(("reviews", f"reviews/cases/{case_file}/findings.md"))

    ticket_id = _extract_ticket_id(messages)
    if ticket_id:
        keys.append(("reviews", f"reviews/tickets/{ticket_id}/findings.md"))

    keys.append(("reviews", "reviews/users/default/preferences.md"))
    return keys


def review_finalizer(messages: list, store: "MemoryStore") -> dict[str, str] | None:
    """检测评审结束，蒸馏 findings 写入 store。

    结束条件：最后一条 AIMessage 无 tool_calls 且含"建议修改汇总"或"P0"关键词。
    """
    from langchain_core.messages import AIMessage

    if not messages:
        return None

    last_ai = None
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            last_ai = m
            break
    if last_ai is None:
        return None

    has_tool_calls = bool(getattr(last_ai, "tool_calls", None))
    if has_tool_calls:
        return None

    content = last_ai.content if isinstance(last_ai.content, str) else str(last_ai.content)
    is_final_report = any(kw in content for kw in ("建议修改汇总", "P0", "P1", "证据缺口"))
    if not is_final_report:
        return None

    case_file = _extract_case_filename(messages)
    ticket_id = _extract_ticket_id(messages)

    if not case_file and not ticket_id:
        return None

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    frontmatter = f"""---
name: {case_file or ticket_id}
type: case-finding
case_filename: {case_file or "unknown"}
ticket_id: {ticket_id or ""}
created: {now}
---

"""
    report_snippet = content[-3000:] if len(content) > 3000 else content

    write_plan: dict[str, str] = {}
    if case_file:
        path = f"reviews/cases/{case_file}/findings.md"
        write_plan[path] = frontmatter + report_snippet
    if ticket_id:
        path = f"reviews/tickets/{ticket_id}/findings.md"
        write_plan[path] = frontmatter + report_snippet

    return write_plan
