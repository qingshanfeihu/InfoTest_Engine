# -*- coding: utf-8 -*-
"""#58 footprint 检索可靠性守卫(Fix A 版本回退 / Fix B 载入完整性)。

#54 whole-domain footprint 断连根因:kb_footprint(version=X) → nodes_<X>/ 不存在 → 空索引 →
静默 not found(ssl+slb 全域;写回落默认 nodes/、查询读 nodes_<version>/,subdir 路由不一致)。
Fix A 让版本查回退默认树;Fix B 让云盘瞬态偏载不被单例固化。
"""
from __future__ import annotations

import json
from pathlib import Path

from main.ist_core.memory.footprint.index import (
    FootprintIndex, get_footprint_index, invalidate_footprint_index,
)


def _seed(nodes_dir: Path, fids):
    nodes_dir.mkdir(parents=True, exist_ok=True)
    for fid in fids:
        (nodes_dir / f"{fid}.json").write_text(
            json.dumps({"feature_id": fid, "level": "leaf", "cli": {"commands": []}}),
            encoding="utf-8")


# ── Fix A:版本 subdir 缺失回退默认 nodes/ ──────────────────────────────────────


def test_missing_version_subdir_falls_back_to_default():
    """不存在的 nodes_<version>/ → get_footprint_index 回退默认 nodes/ 同一单例。"""
    invalidate_footprint_index()
    try:
        assert get_footprint_index("nodes_10.5.0.585") is get_footprint_index("nodes"), \
            "版本分区缺失应回退默认单例(Fix A)"
    finally:
        invalidate_footprint_index()


def test_default_subdir_unchanged():
    """默认 'nodes' 行为不变(回退只对缺失的版本 subdir 生效)。"""
    invalidate_footprint_index()
    try:
        idx = get_footprint_index("nodes")
        assert idx is get_footprint_index()
    finally:
        invalidate_footprint_index()


# ── Fix B:瞬态读失败不缓存偏载、重试;永久损坏跳过不重试 ───────────────────────────


def test_transient_read_failure_not_cached_then_retries(tmp_path, monkeypatch):
    nodes = tmp_path / "nodes"
    _seed(nodes, ["a", "b", "c"])
    idx = FootprintIndex(nodes)
    calls = {"n": 0}
    orig = Path.read_text

    def flaky(self, *a, **k):
        if self.name == "b.json" and calls["n"] < 1:   # 首次对 b 抛 OSError(瞬态,如云盘 sync-lag)
            calls["n"] += 1
            raise OSError("cloud-drive sync lag")
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    idx._ensure_loaded()
    assert not idx._loaded, "瞬态偏载不应被缓存(Fix B:不置 _loaded、下次重试)"
    idx._ensure_loaded()   # 重试:b 读成功
    assert idx._loaded and len(idx._nodes) == 3, "重试后应全载 3 节点"


def test_permanent_corrupt_json_skipped_not_blocking(tmp_path):
    nodes = tmp_path / "nodes"
    _seed(nodes, ["a", "b"])
    (nodes / "bad.json").write_text("{ not valid json", encoding="utf-8")
    idx = FootprintIndex(nodes)
    idx._ensure_loaded()
    # JSONDecodeError=永久损坏,跳过但不触发重试、不阻塞缓存
    assert idx._loaded and len(idx._nodes) == 2, "损坏 JSON 应跳过并正常缓存其余"


def test_transient_retry_capped(tmp_path, monkeypatch):
    """瞬态持续失败超上限 → 缓存现状(避免病态每访问重 glob)。"""
    nodes = tmp_path / "nodes"
    _seed(nodes, ["a", "b"])
    idx = FootprintIndex(nodes)
    orig = Path.read_text

    def always_fail_b(self, *a, **k):
        if self.name == "b.json":
            raise OSError("persistent")
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", always_fail_b)
    for _ in range(idx._MAX_LOAD_RETRY + 1):
        idx._ensure_loaded()
    assert idx._loaded, "超重试上限应缓存现状,不无限重试"
    assert "a" in idx._nodes, "达上限缓存已成功载入的节点"
