"""Footprint 路由：feature_path → target_file（扁平存储）。

LLM 已给出 feature_path（C1 已从 cli_syntax 剥前缀/参数派生），代码只做纯结构：
- 同一 feature_path 的所有 fact 落同一文件 nodes/<feature_id>.json
- level 不在这里定——存储扁平，level 由 reconcile 全树重算后写回
  （俄罗斯方块叠加：height 0=leaf / 1=trunk / >=2=branch）

不替 LLM 做"这命令值不值得记"的语义裁决——LLM 给了 fact 就落盘。
"""

from __future__ import annotations

from main.ist_core.memory.footprint.schema import RawFact, RoutedFact


NODES_DIR = "nodes"


def route_facts(facts: list[RawFact], footprint_dir=None) -> list[RoutedFact]:
    """LLM 已给齐 feature_path + fact_kind，路由是纯结构判断。

    Args:
        facts: extractor 输出
        footprint_dir: 未使用
    """
    results: list[RoutedFact] = []
    for fact in facts:
        if not fact.feature_path:
            continue

        feature_id = ".".join(fact.feature_path)
        if not feature_id:
            continue

        
        results.append(RoutedFact(
            fact=fact,
            level="leaf",  # type: ignore[arg-type]
            target_file=f"{NODES_DIR}/{feature_id}.json",
        ))

    return results

