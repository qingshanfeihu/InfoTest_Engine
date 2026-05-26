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
    """评审场景 finalizer：彻底不写"评审结论"类条目。

    历史规则（已废弃 2026-05-26）：检测 P0-P7 关键字 → 写
    ``reviews/cases/<case>/findings.md`` + ``reviews/tickets/<id>/findings.md``。
    实测发现：写入的评审结论被 ``review_key_resolvers`` 注入回主 agent，
    导致下次评审复用历史结论（trace 实证 LLM thought 出现"memory context 里
    提到已有评审结果"），形成"越评越懒"反馈环。

    新规则（仿 cc-haha "不存评审结论到 memory"源头治理）：
    评审结论留在当轮 ``state.final_review`` + 当轮对话即可，下次评审 fresh
    重跑。需要历史 archive 时跑
    ``scripts/maintenance/archive_review_findings.py``。

    cc-haha 对照：grep ``review.*cache`` /cc-haha/src 无结果——cc-haha review
    skill 跑一次出报告就完，不存进 memory；治"复用历史结论"的方式不是 inject
    端过滤，是源头不写。
    """
    return None
