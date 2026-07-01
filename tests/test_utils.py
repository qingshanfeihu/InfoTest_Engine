"""Tests for main.utils — shared IO, hashing and environment utilities."""

from __future__ import annotations

import json
import re
from pathlib import Path

from main.utils import (
    atomic_write_json,
    file_sha256,
    load_json,
    stable_json_hash,
    utc_iso,
)


class TestLoadJson:
    def test_round_trip(self, tmp_path: Path):
        p = tmp_path / "data.json"
        obj = {"key": "值", "list": [1, 2, 3]}
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        assert load_json(p) == obj

    def test_empty_object(self, tmp_path: Path):
        p = tmp_path / "empty.json"
        p.write_text("{}", encoding="utf-8")
        assert load_json(p) == {}


class TestAtomicWriteJson:
    def test_creates_file(self, tmp_path: Path):
        p = tmp_path / "out.json"
        obj = {"hello": "world"}
        atomic_write_json(p, obj)
        assert p.exists()
        assert load_json(p) == obj

    def test_creates_parent_dirs(self, tmp_path: Path):
        p = tmp_path / "a" / "b" / "out.json"
        atomic_write_json(p, [1, 2])
        assert load_json(p) == [1, 2]

    def test_overwrites_existing(self, tmp_path: Path):
        p = tmp_path / "out.json"
        atomic_write_json(p, {"v": 1})
        atomic_write_json(p, {"v": 2})
        assert load_json(p) == {"v": 2}

    def test_unicode_preserved(self, tmp_path: Path):
        p = tmp_path / "cn.json"
        obj = {"中文": "测试", "emoji": "😀"}
        atomic_write_json(p, obj)
        assert load_json(p) == obj

    def test_no_temp_files_left_on_success(self, tmp_path: Path):
        p = tmp_path / "clean.json"
        atomic_write_json(p, {"x": 1})
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "clean.json"


class TestUtcIso:
    def test_format(self):
        ts = utc_iso()
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts)


class TestFileSha256:
    def test_known_content(self, tmp_path: Path):
        p = tmp_path / "hello.txt"
        p.write_bytes(b"hello")
        import hashlib
        expected = hashlib.sha256(b"hello").hexdigest()
        assert file_sha256(p) == expected

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        import hashlib
        assert file_sha256(p) == hashlib.sha256(b"").hexdigest()


class TestStableJsonHash:
    def test_key_order_irrelevant(self):
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert stable_json_hash(a) == stable_json_hash(b)

    def test_different_values_differ(self):
        assert stable_json_hash({"x": 1}) != stable_json_hash({"x": 2})

    def test_nested_objects(self):
        obj = {"outer": {"inner": [1, 2, 3]}}
        h = stable_json_hash(obj)
        assert isinstance(h, str) and len(h) == 64
