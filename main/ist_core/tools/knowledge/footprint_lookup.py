"""qa_footprint_lookup — agent 查询 footprint 知识的工具。

agent 在评审或回答产品问题时，通过 CLI 命令名查询已积累的 footprint 知识，
获取已验证的产品事实、决策规则、已知缺陷等。

走 FootprintIndex 单例（懒加载 + dict 索引）。
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _format_node(data: dict) -> str:
    """将 footprint JSON 格式化为人可读摘要。"""
    lines: list[str] = []
    fid = data.get("feature_id", "?")
    level = data.get("level", "?")
    meta = data.get("footprint_meta", {})
    lines.append(f"## {fid} ({level}, verified {meta.get('verified_count', 0)}x)")

    cli = data.get("cli", {}).get("commands", [])
    if cli:
        lines.append(f"\nCLI commands ({len(cli)}):")
        for cmd in cli[:5]:
            lines.append(f"  - {cmd.get('command', '?')}")

    rules = data.get("decision_rules", [])
    if rules:
        lines.append(f"\nDecision rules ({len(rules)}):")
        for r in rules[:5]:
            cond = r.get("condition", "")[:140]
            dec = r.get("decision", "")
            if dec:
                lines.append(f"  - IF {cond} → {dec}")
            else:
                lines.append(f"  - {cond}")

    behaviors = data.get("behaviors", [])
    if behaviors:
        lines.append(f"\nBehaviors ({len(behaviors)}):")
        for b in behaviors[:3]:
            lines.append(f"  - {b.get('content', '')[:140]}")

    issues = data.get("known_issues", [])
    if issues:
        lines.append(f"\nKnown issues ({len(issues)}):")
        for iss in issues[:5]:
            title = iss.get("title", "")
            lines.append(f"  - {iss.get('issue_id', '?')}: {title[:80]}")

    vs = data.get("version_scope", {})
    if vs.get("product_versions"):
        lines.append(f"\nVersions: {', '.join(vs['product_versions'][:5])}")

    return "\n".join(lines)


@tool(parse_docstring=True)
def qa_footprint_lookup(command: str) -> str:
    """查询 CLI 命令的产品知识（已验证的规则、行为、缺陷）。

    在评审或回答产品问题时使用。读到 CLI 命令文档后调用此工具，
    获取该命令的历史评审积累知识，避免重复检索原始文档。

    支持两种查询模式：
    - 精确查询：如 "slb mode ircookie" → 返回该命令的完整 footprint
    - 前缀查询：如 "slb mode" → 列出该前缀下的所有子命令

    Args:
        command: CLI 命令名（精确或前缀）。

    Returns:
        匹配的 footprint 内容（CLI 语法、决策规则、行为、已知缺陷），
        或 "未找到" 提示。
    """
    try:
        from main.ist_core.memory.footprint import get_footprint_index
        idx = get_footprint_index()
        result = idx.lookup(command)
        if result is None:
            return f"未找到 '{command}' 的 footprint 知识。"

        if "children" in result:
            children_str = "\n".join(f"  - {c}" for c in result["children"])
            return (
                f"## {result['feature_id']} (前缀匹配, "
                f"{len(result['children'])} 个子命令)\n{children_str}"
            )

        return _format_node(result)
    except Exception as exc:
        logger.warning("qa_footprint_lookup error: %s", exc)
        return f"查询失败: {exc}"
