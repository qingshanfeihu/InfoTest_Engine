"""Footprint 内存索引：从 JSON 文件懒加载，提供精确查找和模糊搜索。

参照 backend.py:_store_singleton 模式，模块级单例。
首次访问时构建索引（O(N), N=节点数, ~50ms for 500 nodes）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKEN_SPLIT_RE = re.compile(r"[^\w一-鿿]+")
_BUG_RE = re.compile(r"BUG-\d+", re.IGNORECASE)


def _format_footprint(data: dict) -> str:
    """将 footprint JSON 格式化为简洁摘要（注入用）。"""
    lines: list[str] = []
    fid = data.get("feature_id", "?")
    level = data.get("level", "?")
    meta = data.get("footprint_meta", {})
    lines.append(f"[{fid}] ({level}, verified {meta.get('verified_count', 0)}x)")

    cli = data.get("cli", {}).get("commands", [])
    for cmd in cli[:5]:
        lines.append(f"  cmd: {cmd.get('command', '')}")

    for r in data.get("decision_rules", [])[:4]:
        cond = r.get("condition", "")[:120]
        dec = r.get("decision", "")
        if dec:
            lines.append(f"  rule: {cond} → {dec}")
        else:
            lines.append(f"  rule: {cond}")

    for b in data.get("behaviors", [])[:3]:
        lines.append(f"  behavior: {b.get('content', '')[:120]}")

    for iss in data.get("known_issues", [])[:4]:
        lines.append(f"  issue: {iss.get('issue_id', '')} {iss.get('title', '')[:80]}")

    vs = data.get("version_scope", {})
    if vs.get("product_versions"):
        lines.append(f"  versions: {', '.join(vs['product_versions'][:5])}")

    return "\n".join(lines)


class FootprintIndex:
    """内存中的 footprint 索引。

    构建时间: ~50ms for 500 nodes
    内存占用: ~1.5MB for 500 nodes
    """

    def __init__(self, footprint_dir: Path):
        self._dir = footprint_dir
        self._nodes: dict[str, dict] = {}
        self._bug_index: dict[str, str] = {}
        self._token_index: dict[str, set[str]] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if not self._dir.exists():
            self._loaded = True
            return

        for f in self._dir.rglob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.debug("footprint 加载失败 %s: %s", f, exc)
                continue

            fid = data.get("feature_id")
            if not fid:
                continue
            self._nodes[fid] = data

            for issue in data.get("known_issues", []):
                bug = issue.get("issue_id")
                if bug:
                    self._bug_index[bug.upper()] = fid

            tokens_to_index: set[str] = set()
            for tok in fid.split("."):
                if tok:
                    tokens_to_index.add(tok.lower())
            content_str = json.dumps(data, ensure_ascii=False).lower()
            for tok in _TOKEN_SPLIT_RE.split(content_str):
                if len(tok) >= 2:
                    tokens_to_index.add(tok)
            for tok in tokens_to_index:
                self._token_index.setdefault(tok, set()).add(fid)

        self._loaded = True
        logger.info("FootprintIndex loaded: %d nodes, %d BUG, %d tokens",
                    len(self._nodes), len(self._bug_index), len(self._token_index))

    def lookup(self, command: str) -> dict | None:
        """精确查找。

        - 完整命令: "http rewrite body" → leaf 完整内容
        - 前缀命令: "slb mode" → 返回子节点列表
        - 找不到: None
        """
        self._ensure_loaded()
        if not command:
            return None
        key = ".".join(command.lower().split())
        if key in self._nodes:
            return self._nodes[key]

        prefix_matches = [
            v for k, v in self._nodes.items()
            if k.startswith(key + ".")
        ]
        if prefix_matches:
            return {
                "feature_id": key,
                "level": "trunk",
                "children": [m["feature_id"] for m in prefix_matches],
                "summary": f"找到 {len(prefix_matches)} 个子节点",
            }
        return None

    def search(self, query: str, *, top_k: int = 3) -> list[tuple[str, str]]:
        """模糊搜索：BUG → token → content 三路匹配。"""
        self._ensure_loaded()
        if not query or not self._nodes:
            return []

        scores: dict[str, int] = {}

        for bug in _BUG_RE.findall(query):
            fid = self._bug_index.get(bug.upper())
            if fid:
                scores[fid] = scores.get(fid, 0) + 100

        query_tokens = [t for t in _TOKEN_SPLIT_RE.split(query.lower()) if t]
        for tok in query_tokens:
            for fid in self._token_index.get(tok, ()):
                scores[fid] = scores.get(fid, 0) + 5

        if not scores:
            for fid, data in self._nodes.items():
                content_str = json.dumps(data, ensure_ascii=False).lower()
                hits = sum(1 for tok in query_tokens if tok in content_str)
                if hits > 0:
                    scores[fid] = hits

        ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_k]
        return [(fid, _format_footprint(self._nodes[fid])) for fid, _ in ranked]

    def stats(self) -> dict:
        """返回索引统计信息（供 /footprint stats 使用）。"""
        self._ensure_loaded()
        by_level: dict[str, int] = {}
        total_facts = 0
        most_verified: list[tuple[str, int, int]] = []
        for fid, data in self._nodes.items():
            level = data.get("level", "?")
            by_level[level] = by_level.get(level, 0) + 1
            facts = (
                len(data.get("cli", {}).get("commands", []))
                + len(data.get("decision_rules", []))
                + len(data.get("behaviors", []))
                + len(data.get("known_issues", []))
            )
            total_facts += facts
            verified = data.get("footprint_meta", {}).get("verified_count", 0)
            most_verified.append((fid, verified, facts))

        most_verified.sort(key=lambda x: -x[1])
        return {
            "total_nodes": len(self._nodes),
            "by_level": by_level,
            "total_facts": total_facts,
            "total_bugs": len(self._bug_index),
            "top_nodes": most_verified[:5],
        }

    def list_nodes(self, level: str | None = None) -> list[str]:
        """列出所有节点的 feature_id（按 level 过滤）。"""
        self._ensure_loaded()
        if level is None:
            return sorted(self._nodes.keys())
        return sorted(
            fid for fid, data in self._nodes.items()
            if data.get("level") == level
        )

    def invalidate(self) -> None:
        """显式失效（dream 写入后调用）。"""
        self._loaded = False
        self._nodes.clear()
        self._bug_index.clear()
        self._token_index.clear()


_FOOTPRINT_INDEX_SINGLETON: FootprintIndex | None = None


def get_footprint_index() -> FootprintIndex:
    """获取进程级 FootprintIndex 单例。"""
    global _FOOTPRINT_INDEX_SINGLETON
    if _FOOTPRINT_INDEX_SINGLETON is None:
        from main.qa_agent.memory.backend import get_default_root
        fp_dir = get_default_root().parent / "knowledge" / "footprints"
        _FOOTPRINT_INDEX_SINGLETON = FootprintIndex(fp_dir)
    return _FOOTPRINT_INDEX_SINGLETON


def invalidate_footprint_index() -> None:
    """全局失效（dream 写入后或测试时使用）。"""
    if _FOOTPRINT_INDEX_SINGLETON is not None:
        _FOOTPRINT_INDEX_SINGLETON.invalidate()
