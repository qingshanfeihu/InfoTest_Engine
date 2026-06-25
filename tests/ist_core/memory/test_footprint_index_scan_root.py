"""get_footprint_index 扫描根契约:只扫 nodes/，绝不吞 footprints/.archive_*/。

历史 bug:扫描根误设为 footprints/ 父目录 + _ensure_loaded 用 rglob 递归 → 归档到
footprints/.archive_*/ 的旧/畸形节点被一并加载;归档清理形同虚设,同 fid 两份还按
rglob 顺序互相 shadow。修复:扫描根锁定 KNOWLEDGE_FOOTPRINTS_NODES 子目录,与
reconcile(footprint_dir/nodes) 一致。
"""
from __future__ import annotations

import json
from pathlib import Path

import main.knowledge_paths as kp
import main.ist_core.memory.footprint.index as idx_mod
from main.ist_core.memory.footprint.index import get_footprint_index


def _write_node(path: Path, fid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "1",
        "feature_id": fid,
        "level": "leaf",
        "cli": {"commands": [{"command": fid.replace(".", " ")}]},
        "footprint_meta": {"verified_count": 1},
    }), encoding="utf-8")


def test_index_scans_nodes_only_excludes_archive(tmp_path, monkeypatch):
    fp = tmp_path / "footprints"
    _write_node(fp / "nodes" / "ping.json", "ping")
    # 归档放在 footprints/ 下、nodes/ 之外，并故意塞一个畸形 fid——绝不能进索引
    _write_node(fp / ".archive_x" / "ghost.json",
                "sdns.host.persistence.[ipv4_netmask")

    monkeypatch.setattr(kp, "KNOWLEDGE_FOOTPRINTS_NODES", fp / "nodes")
    monkeypatch.setattr(idx_mod, "_FOOTPRINT_INDEX_SINGLETON", None)
    try:
        idx = get_footprint_index()
        idx._ensure_loaded()
        assert idx._dir == fp / "nodes"               # 扫描根是 nodes/ 子目录
        assert "ping" in idx._nodes                    # nodes/ 内节点加载
        assert "sdns.host.persistence.[ipv4_netmask" not in idx._nodes  # archive 不加载
        assert len(idx._nodes) == 1                    # 只有 nodes/ 那一个
    finally:
        idx_mod._FOOTPRINT_INDEX_SINGLETON = None       # 别把测试索引漏给后续用例
