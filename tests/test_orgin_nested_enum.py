"""orgin/ 嵌套子目录递归枚举 + rel_key + 白名单过滤回归测试。

覆盖三处链路：
- ``knowledge_paths.iter_orgin_files`` / ``orgin_rel_key``（共享枚举器）
- ``kms_classifier.bucketize_orgin_dir`` / ``list_orgin_with_reasons``（分桶）
- ``mineru_batch_export._list_input_files``（白名单过滤）

关键不变量：顶层文件 rel_key == basename（旧行为完全保留），
嵌套文件 rel_key == ``subdir/file.ext``，``_pdf_splits`` 与隐藏项被跳过。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from main import knowledge_paths as kp


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


@pytest.fixture()
def orgin_tree(tmp_path: Path) -> Path:
    root = tmp_path / "orgin"
    _touch(root / "top.pdf")
    _touch(root / "sub" / "nested.docx")
    _touch(root / "sub" / "deep" / "more.pdf")
    _touch(root / "other" / "nested.docx")  # 跨目录同名，不能冲突
    # 应被跳过的项
    _touch(root / "_pdf_splits" / "top__part1_p1-200.pdf")
    _touch(root / ".hidden" / "x.pdf")
    _touch(root / ".keep")
    return root


def test_iter_orgin_files_recurses_and_skips(orgin_tree: Path):
    keys = sorted(kp.orgin_rel_key(p, orgin_tree) for p in kp.iter_orgin_files(orgin_tree))
    assert keys == [
        "other/nested.docx",
        "sub/deep/more.pdf",
        "sub/nested.docx",
        "top.pdf",
    ]


def test_iter_orgin_files_missing_dir(tmp_path: Path):
    assert list(kp.iter_orgin_files(tmp_path / "nope")) == []


def test_orgin_rel_key_top_level_is_basename(orgin_tree: Path):
    p = orgin_tree / "top.pdf"
    assert kp.orgin_rel_key(p, orgin_tree) == "top.pdf"


def test_orgin_rel_key_outside_root_falls_back_to_name(tmp_path: Path):
    outside = tmp_path / "elsewhere" / "z.pdf"
    assert kp.orgin_rel_key(outside, tmp_path / "orgin") == "z.pdf"


def test_bucketize_uses_rel_keys_no_collision(orgin_tree: Path):
    from main import kms_classifier as kc

    # 把 LLM 判定 stub 成全部 product，专注验证枚举/键，不打网络。
    def _fake_classify(file_path, key=None):
        return {"category": "product", "confidence": 1.0, "reason": "stub", "source": "llm"}

    with patch.object(kc, "classify_file", side_effect=_fake_classify):
        buckets = kc.bucketize_orgin_dir(orgin_tree)

    products = sorted(buckets["product"])
    assert products == [
        "other/nested.docx",
        "sub/deep/more.pdf",
        "sub/nested.docx",
        "top.pdf",
    ]
    # 跨目录同名两份都在，未互相覆盖
    assert products.count("sub/nested.docx") == 1
    assert "other/nested.docx" in products


def test_classify_file_cache_keyed_by_rel_path(orgin_tree: Path, tmp_path: Path):
    """同名嵌套文件用不同 rel_key 写缓存，不应互相覆盖。"""
    from main import kms_classifier as kc

    cache_file = tmp_path / "cache.json"
    overrides_file = tmp_path / "ov.json"

    calls: list[str] = []

    def _fake_llm(filename, hints):
        calls.append(filename)
        return {"category": "product", "confidence": 0.9, "reason": "r", "source": "llm"}

    with patch.object(kc, "_cache_path", return_value=cache_file), \
         patch.object(kc, "_overrides_path", return_value=overrides_file), \
         patch.object(kc, "_call_llm", side_effect=_fake_llm):
        r1 = kc.classify_file(orgin_tree / "sub" / "nested.docx", key="sub/nested.docx")
        r2 = kc.classify_file(orgin_tree / "other" / "nested.docx", key="other/nested.docx")

    assert r1["category"] == "product"
    assert r2["category"] == "product"
    import json

    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    assert set(cache.keys()) == {"sub/nested.docx", "other/nested.docx"}
    # 两次都真正调了 LLM（没被同名 basename 缓存命中短路）
    assert len(calls) == 2


def test_list_input_files_recurses_and_filters_whitelist(orgin_tree: Path):
    from main.mineru_batch_export import _list_input_files

    # 无白名单：递归收全（pdf/docx 都在 SUPPORTED_EXT）
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KMS_PRODUCT_FILES", None)
        files = _list_input_files(orgin_tree)
    rels = sorted(kp.orgin_rel_key(p, orgin_tree) for p in files)
    assert rels == [
        "other/nested.docx",
        "sub/deep/more.pdf",
        "sub/nested.docx",
        "top.pdf",
    ]

    # 白名单用 rel_key 精确过滤
    with patch.dict(os.environ, {"KMS_PRODUCT_FILES": "sub/nested.docx,top.pdf"}):
        files = _list_input_files(orgin_tree)
    rels = sorted(kp.orgin_rel_key(p, orgin_tree) for p in files)
    assert rels == ["sub/nested.docx", "top.pdf"]


def test_list_input_files_legacy_basename_whitelist(orgin_tree: Path):
    """历史白名单只含 basename 时仍能命中顶层文件（向后兼容）。"""
    from main.mineru_batch_export import _list_input_files

    with patch.dict(os.environ, {"KMS_PRODUCT_FILES": "top.pdf"}):
        files = _list_input_files(orgin_tree)
    rels = sorted(kp.orgin_rel_key(p, orgin_tree) for p in files)
    assert rels == ["top.pdf"]
