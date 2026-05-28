"""层级路由：确定 fact 归属的 level、target_file 和 slot。"""

from __future__ import annotations

import re
from pathlib import Path

from main.qa_agent.memory.footprint.schema import RawFact, RoutedFact

_OP_PREFIXES = frozenset({"no", "show", "clear"})


def _normalize_command(tokens: list[str]) -> list[str]:
    if tokens and tokens[0] in _OP_PREFIXES:
        return tokens[1:]
    return tokens


def _longest_common_prefix(seqs: list[tuple[str, ...]]) -> tuple[str, ...]:
    if not seqs:
        return ()
    prefix = list(seqs[0])
    for seq in seqs[1:]:
        i = 0
        while i < len(prefix) and i < len(seq) and prefix[i] == seq[i]:
            i += 1
        prefix = prefix[:i]
        if not prefix:
            break
    return tuple(prefix)


def _determine_level(commands: list[list[str]]) -> str:
    if not commands:
        return "root"
    normalized = [tuple(_normalize_command(c)) for c in commands]
    unique = list(set(normalized))
    if not unique:
        return "root"
    if len(unique) == 1:
        return "leaf"
    prefix = _longest_common_prefix(unique)
    if len(prefix) >= 2:
        return "leaf"
    elif len(prefix) == 1:
        return "trunk"
    else:
        return "branch"


def _resolve_feature_id(level: str, commands: list[list[str]]) -> str:
    normalized = [tuple(_normalize_command(c)) for c in commands]
    unique = list(set(normalized))

    if level == "root":
        return ""  # 空 → 调用方丢弃
    if level == "leaf":
        if len(unique) == 1:
            tokens = unique[0]
            # 4+ tokens 的命令取前 3 个作为 feature_id（子命令不进 id）
            if len(tokens) >= 4:
                return ".".join(tokens[:3])
            return ".".join(tokens)
        prefix = _longest_common_prefix(unique)
        return ".".join(prefix) if prefix else ".".join(unique[0][:3])
    if level == "trunk":
        modules = sorted({t[0] for t in unique if t})
        return modules[0] if modules else "unknown"
    # branch
    modules = sorted({t[0] for t in unique if t})
    return "__".join(modules[:3])


def _resolve_target_file(level: str, feature_id: str) -> str:
    return f"{level}/{feature_id}.json"


def _find_existing_leaf(normalized_tokens: list[str], footprint_dir: Path) -> str | None:
    """新命令是否属于已有 leaf？用前缀重叠匹配。

    匹配规则：新命令和已有 leaf 的 feature_id tokens 共享 >= 3 个前缀 token
    即可归入该 leaf。这样 http.rewrite.body.rule 和 http.rewrite.body.limit
    都会归入同一个 leaf。
    """
    leaf_dir = footprint_dir / "leaf"
    if not leaf_dir.exists():
        return None

    best_match: str | None = None
    best_overlap = 0

    for f in leaf_dir.glob("*.json"):
        existing_tokens = f.stem.split(".")
        # 计算公共前缀长度
        overlap = 0
        for a, b in zip(normalized_tokens, existing_tokens):
            if a == b:
                overlap += 1
            else:
                break

        # 至少 3 个 token 重叠，或者完全包含
        if overlap >= 3 and overlap > best_overlap:
            best_overlap = overlap
            best_match = f"leaf/{f.name}"
        elif overlap >= 2:
            # 2 token 重叠：只有当其中一方完全被包含时才匹配
            if overlap == len(existing_tokens) or overlap == len(normalized_tokens):
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_match = f"leaf/{f.name}"

    return best_match


_CONDITION_SIGNALS = re.compile(
    r"如果|当|需要|必须|不支持|不允许|条件|默认|only|must|require|not support",
    re.IGNORECASE,
)
_CLI_SYNTAX_SIGNALS = re.compile(r"[<\[{].*[>\]}]")
_BUG_SOURCE_RE = re.compile(r"^BUG-\d+$")


def _determine_slot(fact: RawFact) -> str:
    if _BUG_SOURCE_RE.match(fact.source_file):
        return "known_issues"
    if "cli__part" in fact.source_file and _CLI_SYNTAX_SIGNALS.search(fact.content):
        return "cli.commands"
    if _CONDITION_SIGNALS.search(fact.content):
        return "decision_rules"
    if fact.content and any(
        kw in fact.content for kw in ("用于", "功能", "流程", "改写", "转发", "算法")
    ):
        return "behaviors"
    return "_overflow"


def route_facts(facts: list[RawFact], footprint_dir: Path) -> list[RoutedFact]:
    """路由 facts 到目标 footprint 文件。

    两阶段路由：
    1. 先根据命令前缀分组（共享 3+ tokens 的归同一文件）
    2. 再查已有文件进行合并
    """
    results: list[RoutedFact] = []

    # Phase 1: 收集所有 leaf 级 fact 的规范化命令，建立前缀分组
    # key: 规范化命令 tuple → value: (level, feature_id, target_file)
    leaf_prefix_map: dict[tuple[str, ...], str] = {}

    for fact in facts:
        level = _determine_level(fact.cli_commands)
        if level != "leaf":
            # 非 leaf：trunk/branch 正常路由，root 丢弃
            feature_id = _resolve_feature_id(level, fact.cli_commands)
            if not feature_id:
                continue  # 无法路由（root/unknown），丢弃
            target_file = _resolve_target_file(level, feature_id)
            slot = _determine_slot(fact)
            results.append(RoutedFact(fact=fact, level=level, target_file=target_file, slot=slot))
            continue

        # Leaf 级：找到规范化命令的最短公共前缀
        normalized = [tuple(_normalize_command(c)) for c in fact.cli_commands]
        unique = list(set(normalized))
        if not unique:
            unique = [()]

        primary = unique[0]

        # 检查是否有已知的前缀能匹配（共享 3+ tokens）
        matched_prefix: tuple[str, ...] | None = None
        for known_prefix in leaf_prefix_map:
            overlap = 0
            for a, b in zip(primary, known_prefix):
                if a == b:
                    overlap += 1
                else:
                    break
            if overlap >= 3:
                matched_prefix = known_prefix
                break

        if matched_prefix is not None:
            target_file = leaf_prefix_map[matched_prefix]
        else:
            # 查磁盘已有文件
            if primary:
                target_file = _find_existing_leaf(list(primary), footprint_dir)
            else:
                target_file = None

            if target_file is None:
                feature_id = _resolve_feature_id(level, fact.cli_commands)
                target_file = _resolve_target_file(level, feature_id)

            # 用公共前缀（至少 3 tokens）作为分组 key
            group_key = primary[:3] if len(primary) >= 3 else primary
            leaf_prefix_map[group_key] = target_file

        slot = _determine_slot(fact)
        results.append(RoutedFact(fact=fact, level=level, target_file=target_file, slot=slot))

    return results
