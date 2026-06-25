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

# CLI legend 的操作前缀(保留词,仅这 3 个)。extractor 铸 feature_id 时剥掉它们,
# 故 lookup 的 verb 回退须用同一集合,保持铸造端/查询端一致。见 extractor._OP_PREFIXES。
_OP_PREFIXES = ("no", "show", "clear")


def _command_pattern_matches(pattern: str, concrete: str) -> bool:
    """concrete 命令(如 ``sdns on``)是否匹配存储的命令模式(如 ``sdns {on|off}``)。

    **只认 ``{a|b|c}`` alternation 选支**:concrete token 必须是某选支之一;其余 token
    一律字面相等(``<x>``/``[x]`` 占位符**不通配**,否则 "demo svc method rr" 会误匹配
    "demo svc method <a>" 把本该 fuzzy 回退的自然短语吞掉)。concrete 可短于 pattern
    (前缀匹配:查 ``sdns service enable`` 命中 ``sdns service {enable|disable} <name>``)。
    专治"on|off 竖线匹配不上 concrete 'on'"——查 ``sdns on`` 找不到 ``sdns {on|off}`` 节点。
    """
    ptoks = pattern.lower().split()
    ctoks = concrete.lower().split()
    if not ptoks or not ctoks or len(ctoks) > len(ptoks):
        return False
    for p, c in zip(ptoks, ctoks):
        if p.startswith("{") and p.endswith("}"):
            if c not in [a.strip() for a in p[1:-1].split("|")]:
                return False
        elif p != c:
            return False
    return True


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

        - 完整命令: "http rewrite body" → 完整内容（含 on-disk children）
        - 前缀命令: "slb mode" → 返回子节点列表
        - 既是精确节点又有子节点（如 branch "slb" 自带 bug + 子命令）:
          返回节点内容并附 children，两者都不丢
        - 找不到: None

        children 优先用 reconcile 写入磁盘的字段（自包含）；缺失时回退前缀匹配。

        verb 回退：feature_id 由 extractor 剥 `no`/`show`/`clear` 后铸造（裸命令主体），
        但 agent 常按手册原样查 `no/show/clear <cmd>`（命令本身就这么写）。先按**原样**查
        （护住 `show.statistics` / `clear.config` / `no.acl` 等真以动词起头的节点），原样
        miss 再剥前导动词重试一次，把 `no sdns session persistence` 映回 `sdns.session.persistence`。
        """
        self._ensure_loaded()
        if not command:
            return None
        result = self._lookup_key(command)
        if result is not None:
            return result
        toks = command.lower().split()
        j = 0
        while j < len(toks) and toks[j] in _OP_PREFIXES:
            j += 1
        if 0 < j < len(toks):  # 确有前导动词且剥后非空 → 用裸命令主体再查一次
            return self._lookup_key(" ".join(toks[j:]))
        return None

    def _lookup_key(self, command: str) -> dict | None:
        """按命令**原样**（不剥动词）做 精确 key → 前缀 branch → alternation 三级查找。"""
        key = ".".join(command.lower().split())

        if key in self._nodes:
            result = dict(self._nodes[key])
            
            if not result.get("children"):
                prefix_matches = sorted(
                    m["feature_id"] for k, m in self._nodes.items()
                    if k.startswith(key + ".")
                )
                if prefix_matches:
                    result["children"] = prefix_matches
            return result

        prefix_matches = sorted(
            m["feature_id"] for k, m in self._nodes.items()
            if k.startswith(key + ".")
        )
        if prefix_matches:
            return {
                "feature_id": key,
                "level": "branch",
                "children": prefix_matches,
                "summary": f"找到 {len(prefix_matches)} 个子节点",
            }
        # exact + 前缀都没中:试 alternation —— query `sdns on` 是祖先节点命令
        # `sdns {on|off}` 的具体实例(竖线 {a|b} 选支 / <x> 占位 / [x] 可选 展开匹配)。
        return self._alternation_lookup(command)

    def _alternation_lookup(self, command: str) -> dict | None:
        """exact key miss 时沿命令 token 前缀回溯:若某祖先节点的某条命令(展开
        ``{a|b}``/``<x>``/``[x]`` 后)能匹配整条 concrete 查询,返回该节点(经 lookup 拿全 children)。
        治 ``sdns on`` 找不到 ``sdns {on|off}`` 节点(on|off 竖线匹配不上 concrete 'on')。"""
        toks = command.lower().split()
        for i in range(len(toks) - 1, 0, -1):
            parent_key = ".".join(toks[:i])
            node = self._nodes.get(parent_key)
            if not node:
                continue
            for cmd in (node.get("cli", {}) or {}).get("commands", []):
                if _command_pattern_matches(cmd.get("command", ""), command):
                    return self.lookup(parent_key)
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
        from main import knowledge_paths as kp
        # 扫描根必须是 nodes/ 子目录,不是 footprints/ 父目录:_ensure_loaded 用 rglob 递归,
        # 指父目录会把 footprints/.archive_*/ 里的旧/畸形节点一并加载(归档清理形同虚设、
        # 同 fid 两份还会按 rglob 顺序互相 shadow)。与 reconcile(footprint_dir/nodes) 对齐。
        fp_dir = kp.KNOWLEDGE_FOOTPRINTS_NODES
        _FOOTPRINT_INDEX_SINGLETON = FootprintIndex(fp_dir)
    return _FOOTPRINT_INDEX_SINGLETON


def invalidate_footprint_index() -> None:
    """全局失效（dream 写入后或测试时使用）。"""
    if _FOOTPRINT_INDEX_SINGLETON is not None:
        _FOOTPRINT_INDEX_SINGLETON.invalidate()
