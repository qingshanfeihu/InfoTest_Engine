"""Slash 命令：/footprint。

参考 memory_command.py 的子命令分发模式。

提供：
- /footprint                 总览：节点数 + 各 level 分布 + 最丰富节点
- /footprint show <command>  查看某节点完整 footprint 内容
- /footprint search <query>  模糊搜索 footprint
- /footprint stats           统计：节点数、facts、BUG 数
- /footprint list [level]    列出所有节点（可按 leaf/trunk/branch 过滤）
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from main.qa_agent.tui.slash_commands import (
    ErrorResult,
    InfoResult,
    SlashCommandResult,
    TextResult,
)

if TYPE_CHECKING:
    from main.qa_agent.tui.app import IstApp  # noqa: F401

logger = logging.getLogger(__name__)


_HELP_TEXT = """/footprint subcommands:
  /footprint                 总览（默认）
  /footprint show <command>  查看节点完整内容（如 /footprint show http rewrite body）
  /footprint search <query>  模糊搜索（如 /footprint search cookie 加密）
  /footprint stats           统计信息
  /footprint list [level]    列出所有节点（level: leaf/trunk/branch）
"""


def _get_index():
    from main.qa_agent.memory.footprint import get_footprint_index
    return get_footprint_index()


def cmd_footprint(args: str, app: "IstApp") -> SlashCommandResult:
    parts = (args or "").strip().split(None, 1)
    if not parts or parts[0] in ("", "help", "--help", "-h"):
        if parts and parts[0] in ("help", "--help", "-h"):
            return TextResult(text=_HELP_TEXT)
        return _cmd_overview()
    sub = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "stats":
        return _cmd_stats()
    if sub == "show":
        if not rest:
            return ErrorResult(text="usage: /footprint show <command>")
        return _cmd_show(rest)
    if sub == "search":
        if not rest:
            return ErrorResult(text="usage: /footprint search <query>")
        return _cmd_search(rest)
    if sub == "list":
        level = rest.strip() or None
        return _cmd_list(level)
    return ErrorResult(text=f"unknown /footprint subcommand: {sub!r}\n{_HELP_TEXT}")


def _cmd_overview() -> SlashCommandResult:
    """总览：节点统计 + 最丰富节点 top 5。"""
    try:
        idx = _get_index()
        stats = idx.stats()
    except Exception as exc:
        return ErrorResult(text=f"footprint 索引加载失败: {exc}")

    if stats["total_nodes"] == 0:
        return InfoResult(text="(footprint 知识库为空，运行 dream 后再查看)")

    lines = ["## Footprint 知识库总览", ""]
    lines.append(f"  总节点: {stats['total_nodes']}")
    lines.append(f"  总 facts: {stats['total_facts']}")
    lines.append(f"  关联 BUG: {stats['total_bugs']}")
    lines.append("")
    lines.append("  按层级分布:")
    for level, count in sorted(stats["by_level"].items()):
        lines.append(f"    {level:<8s} {count}")
    lines.append("")
    if stats["top_nodes"]:
        lines.append("  最丰富的节点 (verified × facts):")
        for fid, verified, facts in stats["top_nodes"]:
            lines.append(f"    {fid:<40s} verified={verified} facts={facts}")
    return TextResult(text="\n".join(lines))


def _cmd_stats() -> SlashCommandResult:
    """详细统计。"""
    try:
        idx = _get_index()
        stats = idx.stats()
    except Exception as exc:
        return ErrorResult(text=f"footprint 索引加载失败: {exc}")

    lines = [
        f"total_nodes: {stats['total_nodes']}",
        f"total_facts: {stats['total_facts']}",
        f"total_bugs:  {stats['total_bugs']}",
        f"by_level:    {stats['by_level']}",
    ]
    return TextResult(text="\n".join(lines))


def _cmd_show(command: str) -> SlashCommandResult:
    """查看节点完整内容。"""
    try:
        idx = _get_index()
        result = idx.lookup(command)
    except Exception as exc:
        return ErrorResult(text=f"查询失败: {exc}")

    if result is None:
        return InfoResult(text=f"未找到 '{command}' 的 footprint")

    if "children" in result:
        lines = [f"## {result['feature_id']} (前缀, {len(result['children'])} 子节点)"]
        for c in result["children"]:
            lines.append(f"  - {c}")
        return TextResult(text="\n".join(lines))

    return TextResult(text=json.dumps(result, ensure_ascii=False, indent=2))


def _cmd_search(query: str) -> SlashCommandResult:
    """模糊搜索。"""
    try:
        idx = _get_index()
        hits = idx.search(query, top_k=5)
    except Exception as exc:
        return ErrorResult(text=f"搜索失败: {exc}")

    if not hits:
        return InfoResult(text=f"未找到与 '{query}' 相关的 footprint")

    lines = [f"## '{query}' 搜索结果 ({len(hits)} 命中)", ""]
    for fid, summary in hits:
        lines.append(summary)
        lines.append("")
    return TextResult(text="\n".join(lines))


def _cmd_list(level: str | None) -> SlashCommandResult:
    """列出所有节点（按 level 过滤）。"""
    try:
        idx = _get_index()
        nodes = idx.list_nodes(level=level)
    except Exception as exc:
        return ErrorResult(text=f"列出失败: {exc}")

    if not nodes:
        scope = f" (level={level})" if level else ""
        return InfoResult(text=f"(无节点{scope})")

    lines = [f"footprint 节点 ({len(nodes)}{f', level={level}' if level else ''}):"]
    for fid in nodes:
        lines.append(f"  {fid}")
    return TextResult(text="\n".join(lines))


__all__ = ["cmd_footprint"]
