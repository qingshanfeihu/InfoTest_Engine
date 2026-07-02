"""Footprint 路由：feature_path → target_file（扁平存储）。

LLM 已给出 feature_path（C1 已从 cli_syntax 剥前缀/参数派生），代码只做纯结构：
- 同一 feature_path 的所有 fact 落同一文件 nodes/<feature_id>.json
- level 不在这里定——存储扁平，level 由 reconcile 全树重算后写回
  （俄罗斯方块叠加：height 0=leaf / 1=trunk / >=2=branch）

不替 LLM 做"这命令值不值得记"的语义裁决——LLM 给了 fact 就落盘。
"""

from __future__ import annotations

import re

from main.ist_core.memory.footprint.schema import RawFact, RoutedFact


NODES_DIR = "nodes"

# feature_id 直接拼进 target_file 路径(nodes/<feature_id>.json),须挡路径穿越字符——只允许
# dot 分隔的 [A-Za-z0-9_-] 段,拒 / \ .. 前导点空段。安全评审高危项(feature_path 取自 G 命令
# 首 token、可被 provenance 内容控制 → 无收敛会写到 footprint 根外/项目外)。与 merger 写盘前的
# relative_to 收敛纵深防御(dream/verify 写核共用)。
_SAFE_FEATURE_SEG = re.compile(r"[A-Za-z0-9_\-]+")


def _feature_id_safe(feature_id: str) -> bool:
    """feature_id 是否是安全的扁平文件名段(无路径穿越)。"""
    if not feature_id or feature_id.startswith(".") or ".." in feature_id:
        return False
    return all(_SAFE_FEATURE_SEG.fullmatch(seg) for seg in feature_id.split("."))


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
        # 安全：feature_id 进路径前先过白名单,含 / .. 等穿越字符直接丢弃(不路由、不写盘)。
        if not _feature_id_safe(feature_id):
            continue


        results.append(RoutedFact(
            fact=fact,
            level="leaf",  # type: ignore[arg-type]
            target_file=f"{NODES_DIR}/{feature_id}.json",
        ))

    return results

