"""Footprint merger：把 RoutedFact 按 fact_kind + fact_key 写入对应 schema 字段。

设计原则：
- 不再做关键词正则判断 slot
- (fact_kind, fact_key) 作为同一节点内的唯一指纹做 dedup
- level gating 已由 router 做完，这里只按 fact_kind 分发
- evidence 验证闸：cli/rule/behavior 必须能在 evidence_file 中实际 grep 到 evidence_quote
  片段，否则 skip — 防止 LLM 幻觉/agent thought 复述污染
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from main.ist_core.memory.footprint.schema import (
    LEVEL_KINDS,
    MergeResult,
    RoutedFact,
    TEMPLATE_MAP,
)

logger = logging.getLogger(__name__)



_LINE_PREFIX_RE = re.compile(r"^\s*\d+:\s*")

_ELLIPSIS_RE = re.compile(r"\.{3,}")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]



_MARKDOWN_ROOT = ("knowledge", "data", "markdown")


def _resolve_evidence_path(evidence_file: str) -> Path | None:
    """把 evidence_file 解析为可读的绝对路径。

    不硬编码具体子目录（product/qa/...），而是在 markdown 树下通用解析：
    1. 直接当项目相对/绝对路径
    2. 在 knowledge/data/markdown 下按 basename 递归匹配（兼容 LLM 只给文件名 /
       未来新增子目录桶的情况）
    """
    if not evidence_file:
        return None
    root = _project_root()

    direct = root / evidence_file
    if direct.is_file():
        return direct

    md_root = root.joinpath(*_MARKDOWN_ROOT)
    if not md_root.is_dir():
        return None

    name = Path(evidence_file).name
    if not name:
        return None
    
    for p in md_root.rglob(name):
        if p.is_file():
            return p
    return None


def _normalize(s: str) -> str:
    """归一化引号、行号、空白，便于子串匹配。"""
    s = _LINE_PREFIX_RE.sub("", s)
    s = _ELLIPSIS_RE.sub("", s)
    s = s.replace("　", " ")
    return " ".join(s.split())


import math



_EVIDENCE_COVERAGE = 0.6


def _covers_quote(quote: str, haystack: str) -> bool:
    """quote 中是否存在长度 ≥ 60% 的连续子串逐字出现在 haystack 里。

    只需检测一个长度 L=ceil(0.6·len)：若某条长度 L 的窗口命中，则最长连续
    匹配 ≥ L，覆盖率达标；若无一命中，则最长匹配必 < L，不达标。无需二分。
    quote ≤300 字符，窗口数 ≈ 0.4·len（最多 ~120 次 C 级 `in`），单次校验亚百毫秒。
    """
    n = len(quote)
    if n == 0:
        return False
    L = math.ceil(n * _EVIDENCE_COVERAGE)
    for i in range(0, n - L + 1):
        if quote[i:i + L] in haystack:
            return True
    return False


def _evidence_supports(fact) -> bool:
    """验证 evidence_quote 能在 evidence_file 中真实命中。

    known_issue 类型有 issue_id 自带凭证，不走这个闸。
    cli/rule/behavior 缺 evidence_quote 或 evidence_file 直接判 false。

    判定：
    1. 归一化后整段子串命中 → 通过（LLM 老实引用的常见情形）
    2. 否则按覆盖率：quote 中最长的逐字命中片段 ≥ quote 长度的 60% → 通过
       （容忍 LLM 在首尾轻微改写/补字，但不容忍整体编造）
    覆盖率与语言、quote 绝对长度无关，不再用 `>=N 字符` 这种硬阈值。
    """
    if not fact.evidence_quote or not fact.evidence_file:
        return False

    path = _resolve_evidence_path(fact.evidence_file)
    if path is None:
        return False

    try:
        haystack = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    quote = _normalize(fact.evidence_quote)
    if not quote:
        return False

    haystack_norm = _normalize(haystack)

    
    if quote in haystack_norm:
        return True

    
    return _covers_quote(quote, haystack_norm)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _update_meta(fp: dict, source_thread: str) -> None:
    meta = fp.setdefault("footprint_meta", {})
    if not meta.get("created_at"):
        meta["created_at"] = _now_iso()
    meta["verified_count"] = meta.get("verified_count", 0) + 1
    threads = meta.setdefault("source_threads", [])
    if source_thread and source_thread not in threads:
        threads.append(source_thread)
        if len(threads) > 10:
            threads[:] = threads[-10:]


def _evidence(fact) -> dict:
    ev: dict = {}
    if fact.evidence_file:
        ev["source_file"] = fact.evidence_file
    if fact.evidence_quote:
        ev["quoted_text"] = fact.evidence_quote
    return ev


def _merge_parameters(existing: list[dict], incoming: list[dict]) -> bool:
    """按 name 合并参数表。新增缺失参数 / 补全已有参数空字段。返回是否有变更。"""
    changed = False
    by_name = {p.get("name"): p for p in existing if p.get("name")}
    for inc in incoming:
        name = inc.get("name")
        if not name:
            continue
        if name not in by_name:
            existing.append(inc)
            by_name[name] = inc
            changed = True
            continue
        cur = by_name[name]
        for k, v in inc.items():
            if k == "name":
                continue
            if v not in (None, "") and not cur.get(k):
                cur[k] = v
                changed = True
    return changed


def _append_cli_command(fp: dict, fact) -> str:
    """按完整 cli_syntax 去重（非 fact_key）。

    同一 feature_id 下，no/show/clear/配置 四态是不同命令，各自完整形态并存：
      slb real http <rs_name>   (配置)
      no slb real http          (否定/删除)
      show slb real http        (查询)
      clear slb real http       (清除)
    它们 feature_path 相同（C1 剥前缀后归一），但 cli_syntax 不同 → 都保留。
    只有 cli_syntax 完全相同才视为重复，此时合并参数表（补全而非丢弃）。
    """
    commands = fp.setdefault("cli", {}).setdefault("commands", [])
    syntax = fact.cli_syntax.strip()
    for existing in commands:
        if existing.get("command", "").strip() == syntax:
            if fact.parameters:
                changed = _merge_parameters(
                    existing.setdefault("parameters", []), fact.parameters
                )
                return "append" if changed else "skip"
            return "skip"
    entry = {
        "fact_key": fact.fact_key,
        "command": fact.cli_syntax,
        "evidence": _evidence(fact),
    }
    if fact.parameters:
        entry["parameters"] = fact.parameters
    commands.append(entry)
    return "append"


def _append_decision_rule(fp: dict, fact) -> str:
    rules = fp.setdefault("decision_rules", [])
    for existing in rules:
        if existing.get("fact_key") == fact.fact_key:
            return "skip"
    rules.append({
        "fact_key": fact.fact_key,
        "condition": fact.condition,
        "decision": fact.decision,
        "evidence": _evidence(fact),
    })
    return "append"


def _append_behavior(fp: dict, fact) -> str:
    behaviors = fp.setdefault("behaviors", [])
    for existing in behaviors:
        if existing.get("fact_key") == fact.fact_key:
            return "skip"
    behaviors.append({
        "fact_key": fact.fact_key,
        "content": fact.content,
        "evidence": _evidence(fact),
    })
    return "append"


def _append_known_issue(fp: dict, fact) -> str:
    issues = fp.setdefault("known_issues", [])
    for existing in issues:
        if existing.get("issue_id") == fact.issue_id:
            
            updated = False
            if fact.issue_title and not existing.get("title"):
                existing["title"] = fact.issue_title
                updated = True
            if fact.affected_versions:
                merged = sorted(set(existing.get("affected_versions", [])) | set(fact.affected_versions))
                if merged != existing.get("affected_versions"):
                    existing["affected_versions"] = merged
                    updated = True
            return "update" if updated else "skip"

    entry: dict[str, Any] = {"issue_id": fact.issue_id}
    if fact.issue_title:
        entry["title"] = fact.issue_title
    if fact.affected_versions:
        entry["affected_versions"] = sorted(set(fact.affected_versions))
        
        if fp.get("level") == "leaf":
            vs = fp.setdefault("version_scope", {})
            cur = set(vs.get("product_versions", []))
            cur.update(fact.affected_versions)
            vs["product_versions"] = sorted(cur)
    issues.append(entry)
    return "append"


_DISPATCH = {
    "cli_command": _append_cli_command,
    "decision_rule": _append_decision_rule,
    "behavior": _append_behavior,
    "known_issue": _append_known_issue,
}


def merge_fact(routed: RoutedFact, footprint_dir: Path) -> MergeResult:
    """把 RoutedFact 写入/合并到目标 footprint 文件。

    level + fact_kind 不匹配（router 已 gating，这里是兜底）→ skip。
    cli/rule/behavior 的 evidence_quote 必须能在 evidence_file 中真实命中，
    否则视为幻觉，skip。
    """
    fact = routed.fact
    target_path = footprint_dir / routed.target_file

    if fact.fact_kind not in LEVEL_KINDS.get(routed.level, set()):
        return MergeResult(action="skip", target_file=routed.target_file, detail="kind not allowed at level")

    
    if fact.fact_kind != "known_issue" and not _evidence_supports(fact):
        return MergeResult(
            action="skip",
            target_file=routed.target_file,
            detail="evidence not found in source file",
        )

    handler = _DISPATCH.get(fact.fact_kind)
    if handler is None:
        return MergeResult(action="skip", target_file=routed.target_file, detail="unknown fact_kind")

    if not target_path.exists():
        template_fn = TEMPLATE_MAP[routed.level]
        fp = template_fn(target_path.stem)
        action = handler(fp, fact)
        if action == "skip":
            return MergeResult(action="skip", target_file=routed.target_file, detail="empty after handler")
        _update_meta(fp, fact.source_thread)
        _write_json(target_path, fp)
        return MergeResult(action="create", target_file=routed.target_file, detail=fact.fact_kind)

    try:
        fp = json.loads(target_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("footprint read failed %s: %s", target_path, exc)
        return MergeResult(action="skip", target_file=routed.target_file, detail=str(exc))

    action = handler(fp, fact)
    if action == "skip":
        return MergeResult(action="skip", target_file=routed.target_file, detail="duplicate")

    _update_meta(fp, fact.source_thread)
    _write_json(target_path, fp)
    return MergeResult(action=action, target_file=routed.target_file, detail=fact.fact_kind)
