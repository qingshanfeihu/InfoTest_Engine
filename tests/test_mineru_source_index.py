"""MinerU 内容寻址缓存索引（SourceIndex）回归测试。

覆盖三类核心场景：
- 同名、内容改了 → 哈希失配 → 不命中（修正确性 bug）
- 改名 / 异名、内容相同 → 哈希命中 → 复用 zip（省 API）
- (mtime,size) 快表避免重复读盘哈希
- record() 清理指向同一 zip 的悬空旧条目
- backfill 把已有 zip 按内容哈希灌入索引
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from main.mineru_source_index import SourceIndex, _sha256_file


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture()
def dirs(tmp_path: Path):
    base = tmp_path / "orgin"
    out = tmp_path / "mineru"
    base.mkdir()
    out.mkdir()
    return base, out


def test_lookup_miss_on_empty(dirs):
    base, out = dirs
    idx = SourceIndex.load(base, out)
    assert idx.lookup("deadbeef") is None


def test_record_and_lookup_roundtrip(dirs):
    base, out = dirs
    idx = SourceIndex.load(base, out)
    idx.record("h1", stem="doc", zipname="doc.mineru.zip", source_name="doc.pdf")
    entry = idx.lookup("h1")
    assert entry["zip"] == "doc.mineru.zip"
    assert entry["stem"] == "doc"
    assert entry["source"] == "doc.pdf"


def test_persist_and_reload(dirs):
    base, out = dirs
    idx = SourceIndex.load(base, out)
    idx.record("h1", stem="doc", zipname="doc.mineru.zip", source_name="doc.pdf")
    idx.save()

    idx2 = SourceIndex.load(base, out)
    assert idx2.lookup("h1")["zip"] == "doc.mineru.zip"


def test_source_hash_matches_content_not_name(dirs):
    base, out = dirs
    a = base / "a.pdf"
    b = base / "renamed.pdf"
    _write(a, b"identical bytes")
    _write(b, b"identical bytes")
    idx = SourceIndex.load(base, out)
    assert idx.source_hash(a) == idx.source_hash(b)  # 异名同内容 → 同哈希


def test_source_hash_changes_with_content(dirs):
    base, out = dirs
    p = base / "doc.pdf"
    _write(p, b"version one")
    idx = SourceIndex.load(base, out)
    h1 = idx.source_hash(p)
    _write(p, b"version two")  # 同名改内容
    # 重建索引（清快表）后哈希应不同
    idx2 = SourceIndex.load(base, out)
    assert idx2.source_hash(p) != h1


def test_quick_table_skips_rehash(dirs, monkeypatch):
    base, out = dirs
    p = base / "doc.pdf"
    _write(p, b"stable content")
    idx = SourceIndex.load(base, out)
    h1 = idx.source_hash(p)  # 首次：真算

    calls = {"n": 0}
    import main.mineru_source_index as mod

    real = mod._sha256_file

    def _counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(mod, "_sha256_file", _counting)
    h2 = idx.source_hash(p)  # (mtime,size) 未变 → 走快表
    assert h2 == h1
    assert calls["n"] == 0


def test_record_evicts_stale_hash_for_same_zip(dirs):
    """同名 zip 被新内容覆盖后，旧 hash 条目应被清除，避免悬空错配。"""
    base, out = dirs
    idx = SourceIndex.load(base, out)
    idx.record("old_hash", stem="doc", zipname="doc.mineru.zip", source_name="doc.pdf")
    idx.record("new_hash", stem="doc", zipname="doc.mineru.zip", source_name="doc.pdf")
    assert idx.lookup("old_hash") is None
    assert idx.lookup("new_hash")["zip"] == "doc.mineru.zip"


def test_corrupt_index_degrades_to_empty(dirs):
    base, out = dirs
    (out / ".source_index.json").write_text("{not json", encoding="utf-8")
    idx = SourceIndex.load(base, out)  # 不应抛
    assert idx.lookup("anything") is None


def test_backfill_indexes_existing_zips(dirs):
    from main.mineru_batch_export import _backfill_source_index

    base, out = dirs
    p1 = base / "a.pdf"
    p2 = base / "sub" / "b.docx"
    _write(p1, b"content a")
    _write(p2, b"content b")
    # 模拟已存在的 zip（stem 命名）
    _write(out / "a.mineru.zip", b"zipA")
    _write(out / "b.mineru.zip", b"zipB")

    idx = SourceIndex.load(base, out)
    n = _backfill_source_index(idx, [p1, p2], out)
    assert n == 2
    assert idx.lookup(idx.source_hash(p1))["zip"] == "a.mineru.zip"
    assert idx.lookup(idx.source_hash(p2))["zip"] == "b.mineru.zip"


def test_backfill_skips_missing_zip(dirs):
    from main.mineru_batch_export import _backfill_source_index

    base, out = dirs
    p1 = base / "a.pdf"
    _write(p1, b"content a")
    # 没有对应 zip
    idx = SourceIndex.load(base, out)
    n = _backfill_source_index(idx, [p1], out)
    assert n == 0
    assert idx.lookup(idx.source_hash(p1)) is None
