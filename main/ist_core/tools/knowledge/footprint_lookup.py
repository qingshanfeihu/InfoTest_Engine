"""kb_footprint — agent 查询 footprint 知识的工具。

agent 在评审或回答产品问题时，通过 CLI 命令名查询已积累的 footprint 知识，
获取已验证的产品事实、决策规则、已知缺陷等。

走 FootprintIndex 单例（懒加载 + dict 索引）。
"""

from __future__ import annotations

import logging
import re

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 启用/总开关命令的形态：含 {on|off}/{enable|disable} 选项,或以 on/enable 结尾。
_ENABLE_CMD_RE = re.compile(
    r"\{\s*on\s*\|\s*off\s*\}|\{\s*enable\s*\|\s*disable\s*\}|\bon\b\s*$|\benable\b\s*$",
    re.IGNORECASE,
)


def _module_enable_hint(idx, command: str) -> str:
    """子功能查询时,上溯模块根节点、带回它的「启用/总开关」命令。

    根因(实测): `sdns on` 是 `sdns {on|off}` 的形态,存在模块根节点 `sdns` 里;查子功能
    (sdns host/pool…)时检索不到它 → draft 漏总开关 → 服务不起、上机全 fail。这里对任何
    `<module> <sub...>` 查询,把模块根的启用命令作为"需先执行"附上。通用(任何模块同理),
    不写死具体命令。
    """
    toks = (command or "").lower().split()
    if len(toks) < 2:
        return ""  # 查的就是根本身,无需提示
    root = toks[0]
    try:
        rnode = idx.lookup(root)
    except Exception:  # noqa: BLE001
        return ""
    if not rnode:
        return ""
    for cm in (rnode.get("cli", {}) or {}).get("commands", []):
        c = cm.get("command", "") if isinstance(cm, dict) else str(cm)
        if c and _ENABLE_CMD_RE.search(c):
            return (f"⚠ 模块总开关(用任何 {root} 功能前**必须先执行**,否则配了也不生效、"
                    f"服务不起、上机全 fail): {c}\n\n")
    return ""


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
def kb_footprint(command: str) -> str:
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
        enable_hint = _module_enable_hint(idx, command)

        def _has_commands(r: dict | None) -> bool:
            return bool(r and r.get("cli", {}).get("commands"))

        def _collect_descendant_command_nodes(node: dict, seen: set[str]) -> list[dict]:
            """递归收集 node 子树里**所有带命令的后代节点**（深度优先，去重）。
            治：trunk 的直接子节点本身是空 branch、命令在孙节点时，单层展开会漏。"""
            out: list[dict] = []
            for cid in node.get("children", []) or []:
                if cid in seen:
                    continue
                seen.add(cid)
                cnode = idx.lookup(cid)
                if cnode is None:
                    continue
                if _has_commands(cnode):
                    out.append(cnode)
                # 子节点即便自己有命令，也可能还有更深的孙节点，继续下潜
                out.extend(_collect_descendant_command_nodes(cnode, seen))
            return out

        # 命中的节点自己没有命令（branch/trunk 空壳索引节点，或合成前缀结果）：
        if not _has_commands(result):
            # 这是一个**已知的 branch**（lookup 命中了，有 children）→ 递归展开其子树里
            # 带命令的后代节点，给 draft 它真正要的命令（而不是全树模糊的无关节点）。
            if result and result.get("children"):
                child_nodes = _collect_descendant_command_nodes(result, set())
                if child_nodes:
                    parts = [f"## 「{command}」是父节点，展开其子树中 "
                             f"{len(child_nodes)} 个带命令的节点："]
                    for node in child_nodes:
                        parts.append("\n" + _format_node(node))
                    return enable_hint + "\n".join(parts)
                # branch 存在但整棵子树都没有命令 → 如实说明，不要用 branch 的 token
                # 去全树模糊匹配（那会返回仅共享一个词的无关节点，误导 draft）。
                return (f"## {result.get('feature_id', command)} "
                        f"是父节点，但其子树未记录任何 CLI 命令。")

            # result is None：查询不对应任何节点/前缀（多为自然措辞，如
            # "sdns host method rr"）→ 全树模糊兜底，只收带命令的叶子。
            hits = idx.search(command, top_k=3)
            leaf_hits = []
            for fid, _ in hits:
                node = idx.lookup(fid)
                if _has_commands(node):
                    leaf_hits.append(node)
            if leaf_hits:
                parts = [f"## 「{command}」精确未命中，模糊匹配到 "
                         f"{len(leaf_hits)} 个相关命令节点："]
                for node in leaf_hits:
                    parts.append("\n" + _format_node(node))
                return enable_hint + "\n".join(parts)
            return (enable_hint + f"未找到 '{command}' 的 footprint 知识。") if enable_hint \
                else f"未找到 '{command}' 的 footprint 知识。"

        # 命中的节点自己有命令：展开它；若同时是 branch（带子节点）附子命令清单。
        out = _format_node(result)
        children = result.get("children") or []
        if children:
            out += "\n\n子命令 ({}):\n".format(len(children)) + "\n".join(
                f"  - {c}" for c in children
            )
        return enable_hint + out
    except Exception as exc:
        logger.warning("kb_footprint error: %s", exc)
        return f"查询失败: {exc}"
