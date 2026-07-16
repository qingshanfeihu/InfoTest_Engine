"""C3: 全树 reconcile —— 补建中间节点 + 俄罗斯方块叠加重算 level + 写 children。

在所有 fact 落盘后跑一遍。纯结构操作，无语义判断：
1. 扫 nodes/*.json，按 feature_id 点号建前缀树
2. 补建缺失的中间节点（slb、slb.policy 等空结构父节点）
3. 自底向上算 height：叶子=0，父=max(子)+1
4. height → level：0=leaf / 1=trunk / >=2=branch
5. 每个节点写 children（直接子节点 feature_id），磁盘自包含

不依赖运行时前缀匹配——树在磁盘上完整且自包含。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from main.ist_core.memory.footprint.schema import node_template

logger = logging.getLogger(__name__)

NODES_DIR = "nodes"


def _height_to_level(height: int) -> str:
    if height == 0:
        return "leaf"
    if height == 1:
        return "trunk"
    return "branch"


def _parent_id(feature_id: str) -> str | None:
    """点号路径的父：slb.policy.default → slb.policy；slb → None。"""
    if "." not in feature_id:
        return None
    return feature_id.rsplit(".", 1)[0]


def reconcile(footprint_dir: Path, nodes_subdir: str = "nodes") -> dict:
    """重算整棵树的结构。返回统计 dict。"""
    nodes_dir = footprint_dir / nodes_subdir
    if not nodes_dir.exists():
        return {"total": 0, "created": 0, "by_level": {}}

    
    nodes: dict[str, dict] = {}
    for f in nodes_dir.glob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("reconcile 读取失败 %s: %s", f, exc)
            continue
        fid = d.get("feature_id")
        if fid:
            nodes[fid] = d

    if not nodes:
        return {"total": 0, "created": 0, "by_level": {}}

    
    created = 0
    for fid in list(nodes.keys()):
        parent = _parent_id(fid)
        while parent is not None:
            if parent not in nodes:
                nodes[parent] = node_template(parent)
                created += 1
            parent = _parent_id(parent)

    
    children: dict[str, list[str]] = {fid: [] for fid in nodes}
    for fid in nodes:
        parent = _parent_id(fid)
        if parent is not None and parent in children:
            children[parent].append(fid)

    
    height_cache: dict[str, int] = {}

    def height(fid: str) -> int:
        if fid in height_cache:
            return height_cache[fid]
        kids = children.get(fid, [])
        h = 0 if not kids else max(height(k) for k in kids) + 1
        height_cache[fid] = h
        return h

    
    by_level: dict[str, int] = {}
    for fid, node in nodes.items():
        lvl = _height_to_level(height(fid))
        node["level"] = lvl
        node["children"] = sorted(children.get(fid, []))
        by_level[lvl] = by_level.get(lvl, 0) + 1
        path = nodes_dir / f"{fid}.json"
        path.write_text(
            json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return {"total": len(nodes), "created": created, "by_level": by_level}
