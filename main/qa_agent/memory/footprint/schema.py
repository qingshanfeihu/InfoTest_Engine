"""Footprint 数据结构定义和 JSON 模板。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawFact:
    """从 working memory 中提取的一条原始事实。"""

    content: str
    cli_commands: list[list[str]] = field(default_factory=list)
    source_file: str = ""
    quoted_text: str = ""
    source_thread: str = ""


@dataclass
class RoutedFact:
    """路由后的事实，已确定目标层级和文件。"""

    fact: RawFact
    level: str = ""       # "leaf" | "trunk" | "branch" | "root"
    target_file: str = ""  # 相对于 footprints/ 的路径
    slot: str = ""         # "cli.commands" | "decision_rules" | "behaviors" | ...


@dataclass
class MergeResult:
    """merge 操作结果。"""

    action: str = "skip"   # "skip" | "update" | "append" | "create"
    target_file: str = ""
    detail: str = ""


def leaf_template(feature_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "feature_id": feature_id,
        "level": "leaf",
        "cli": {"commands": []},
        "decision_rules": [],
        "behaviors": [],
        "known_issues": [],
        "version_scope": {},
        "footprint_meta": {
            "created_at": None,
            "verified_count": 0,
            "source_threads": [],
        },
    }


def trunk_template(feature_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "feature_id": feature_id,
        "level": "trunk",
        "related_commands": [],
        "interactions": [],
        "footprint_meta": {
            "created_at": None,
            "verified_count": 0,
            "source_threads": [],
        },
    }


def branch_template(feature_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "feature_id": feature_id,
        "level": "branch",
        "related_modules": [],
        "interactions": [],
        "footprint_meta": {
            "created_at": None,
            "verified_count": 0,
            "source_threads": [],
        },
    }


def root_template(feature_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "feature_id": feature_id,
        "level": "root",
        "facts": [],
        "footprint_meta": {
            "created_at": None,
            "verified_count": 0,
            "source_threads": [],
        },
    }
