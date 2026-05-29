"""Footprint 子系统：从 working memory 提取产品/测试知识，按 CLI 命令树组织。

Public API:
    extract_facts(content, *, llm_chat) -> list[RawFact]
    route_facts(facts, footprint_dir) -> list[RoutedFact]
    merge_fact(routed, footprint_dir) -> MergeResult
    get_footprint_index() -> FootprintIndex   # 单例索引
    invalidate_footprint_index() -> None      # 失效（dream 写后/测试用）
"""

from __future__ import annotations

from main.ist_core.memory.footprint.schema import MergeResult, RawFact, RoutedFact
from main.ist_core.memory.footprint.extractor import extract_facts
from main.ist_core.memory.footprint.router import route_facts
from main.ist_core.memory.footprint.merger import merge_fact
from main.ist_core.memory.footprint.reconcile import reconcile
from main.ist_core.memory.footprint.index import (
    FootprintIndex,
    get_footprint_index,
    invalidate_footprint_index,
)

__all__ = [
    "RawFact",
    "RoutedFact",
    "MergeResult",
    "extract_facts",
    "route_facts",
    "merge_fact",
    "reconcile",
    "FootprintIndex",
    "get_footprint_index",
    "invalidate_footprint_index",
]
