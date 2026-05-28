"""Footprint merge 逻辑：将 RoutedFact 写入/合并到目标 JSON 文件。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from main.qa_agent.memory.footprint.schema import (
    MergeResult,
    RoutedFact,
    branch_template,
    leaf_template,
    root_template,
    trunk_template,
)

logger = logging.getLogger(__name__)

_TEMPLATE_MAP = {
    "leaf": leaf_template,
    "trunk": trunk_template,
    "branch": branch_template,
    "root": root_template,
}


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


def _build_evidence(fact) -> dict:
    ev: dict = {}
    if fact.source_file:
        ev["source_file"] = fact.source_file
    if fact.quoted_text:
        ev["quoted_text"] = fact.quoted_text[:300]
    return ev


def _merge_known_issue(fp: dict, fact) -> str:
    import re
    issues = fp.setdefault("known_issues", [])
    bug_match = re.search(r"BUG-\d+", fact.source_file)
    if not bug_match:
        return "skip"
    bug_id = bug_match.group(0)
    for existing in issues:
        if existing.get("issue_id") == bug_id:
            return "skip"

    title = ""
    title_match = re.search(r'"title":\s*"([^"]+)"', fact.quoted_text)
    if title_match:
        title = title_match.group(1)[:120]

    entry: dict = {"issue_id": bug_id}
    if title:
        entry["title"] = title

    versions: list[str] = []
    ver_match = re.search(r"Affected Release[:\s]*([^\n\"]+)", fact.quoted_text)
    if ver_match:
        versions = [v.strip() for v in ver_match.group(1).replace(",", " ").split() if v.strip()]
    if versions:
        entry["fixed_in"] = versions
        vs = fp.setdefault("version_scope", {})
        existing_vers = set(vs.get("product_versions", []))
        existing_vers.update(versions)
        vs["product_versions"] = sorted(existing_vers)

    issues.append(entry)
    return "append"


def _merge_cli_command(fp: dict, fact) -> str:
    commands = fp.setdefault("cli", {}).setdefault("commands", [])
    from main.cli_command_utils import extract_command_tokens

    content_tokens = extract_command_tokens(fact.content)
    if not content_tokens:
        return "skip"

    token_str = " ".join(content_tokens)
    for existing in commands:
        existing_tokens = extract_command_tokens(existing.get("command", ""))
        if existing_tokens == content_tokens:
            return "skip"

    entry = {"command": token_str, "evidence": _build_evidence(fact)}
    commands.append(entry)
    return "append"


def _merge_decision_rule(fp: dict, fact) -> str:
    rules = fp.setdefault("decision_rules", [])
    content_short = fact.content[:100]
    for existing in rules:
        if existing.get("condition", "")[:80] in content_short:
            return "skip"
        if content_short[:80] in existing.get("condition", ""):
            return "skip"

    entry = {
        "condition": fact.content[:200],
        "decision": "",
        "evidence": _build_evidence(fact),
    }
    rules.append(entry)
    return "append"


def _merge_behavior(fp: dict, fact) -> str:
    behaviors = fp.setdefault("behaviors", [])
    content_short = fact.content[:100]
    for existing in behaviors:
        if content_short[:60] in existing.get("content", ""):
            return "skip"

    entry = {"content": fact.content[:300], "evidence": _build_evidence(fact)}
    behaviors.append(entry)
    return "append"


def _merge_overflow(fp: dict, fact) -> str:
    facts_list = fp.setdefault("facts", [])
    content_short = fact.content[:80]
    for existing in facts_list:
        if content_short in existing.get("content", ""):
            return "skip"

    entry = {"content": fact.content[:400], "evidence": _build_evidence(fact)}
    facts_list.append(entry)
    return "append"


def merge_fact(routed: RoutedFact, footprint_dir: Path) -> MergeResult:
    """将一个 RoutedFact 写入/合并到目标 footprint 文件。"""
    target_path = footprint_dir / routed.target_file
    fact = routed.fact

    if not target_path.exists():
        template_fn = _TEMPLATE_MAP.get(routed.level, leaf_template)
        feature_id = target_path.stem
        fp = template_fn(feature_id)
        _update_meta(fp, fact.source_thread)

        if routed.slot == "known_issues":
            action = _merge_known_issue(fp, fact)
        elif routed.slot == "cli.commands":
            action = _merge_cli_command(fp, fact)
        elif routed.slot == "decision_rules":
            action = _merge_decision_rule(fp, fact)
        elif routed.slot == "behaviors":
            action = _merge_behavior(fp, fact)
        else:
            action = _merge_overflow(fp, fact)

        if action == "skip":
            return MergeResult(action="skip", target_file=routed.target_file, detail="duplicate")

        _write_json(target_path, fp)
        return MergeResult(
            action="create",
            target_file=routed.target_file,
            detail=f"created {routed.level} footprint",
        )

    try:
        fp = json.loads(target_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("footprint read failed %s: %s", target_path, exc)
        return MergeResult(action="skip", target_file=routed.target_file, detail=str(exc))

    if routed.slot == "known_issues":
        action = _merge_known_issue(fp, fact)
    elif routed.slot == "cli.commands":
        action = _merge_cli_command(fp, fact)
    elif routed.slot == "decision_rules":
        action = _merge_decision_rule(fp, fact)
    elif routed.slot == "behaviors":
        action = _merge_behavior(fp, fact)
    else:
        action = _merge_overflow(fp, fact)

    if action == "skip":
        return MergeResult(action="skip", target_file=routed.target_file, detail="duplicate")

    _update_meta(fp, fact.source_thread)
    _write_json(target_path, fp)
    return MergeResult(action=action, target_file=routed.target_file, detail=routed.slot)
