"""MinerU 解析缓存的内容寻址索引（content-addressed source index）。

背景：MinerU 解析走付费 API，``knowledge/.intermediate/mineru/`` 下已积累数百个
``{stem}.mineru.zip``。历史命中判定只看 ``{stem}.mineru.zip`` 是否存在，纯靠**文件名**，
导致三类问题：

1. 同名、内容改了 → 命中旧 zip，静默用陈旧内容（正确性 bug）。
2. 改名、内容不变 → 重新调 API（浪费钱）。
3. 异名、内容相同 → 各解析一遍（浪费钱）。

本模块把命中键从文件名换成**源文件内容 sha256**：

- ``by_hash``：``{source_sha256: {zip, stem, source, parsed_at}}`` —— 命中键。
- ``by_path``：``{rel_path: {mtime, size, hash}}`` —— 快表，文件 ``(mtime,size)`` 未变时
  跳过读盘哈希，避免每轮对数百个文件全量 sha256。

zip 仍按 stem 命名（不重命名历史产物）；index 命中时复用对应 zip，按各自文件名重出
markdown。``record()`` 写新条目前会清掉所有指向同一 zip 文件名的旧 hash 条目，避免
同名改内容覆盖 zip 后残留悬空条目造成错配。

索引文件落 ``<output_dir>/.source_index.json``，属 ``.intermediate``（agent 不可见、
不进 git）。所有失败静默降级（返回空索引 / miss），不阻断 mineru 主流程。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INDEX_FILENAME = ".source_index.json"
_HASH_CHUNK = 1 << 16  # 64 KiB，分块读，兼顾上百 MB 的 PDF


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_HASH_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class SourceIndex:
    """MinerU 解析缓存的内容寻址索引（单进程内使用，非线程安全）。"""

    def __init__(self, base_dir: Path, index_path: Path, data: dict[str, Any]):
        self._base = base_dir
        self._path = index_path
        self._by_hash: dict[str, dict] = data.get("by_hash", {}) or {}
        self._by_path: dict[str, dict] = data.get("by_path", {}) or {}

    # ---- 加载 / 持久化 ----------------------------------------------------

    @classmethod
    def load(cls, base_dir: Path, output_dir: Path) -> "SourceIndex":
        index_path = output_dir / INDEX_FILENAME
        data: dict[str, Any] = {}
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("source index load failed (%s): %s", index_path, exc)
                data = {}
        return cls(base_dir.resolve(), index_path, data)

    def save(self) -> None:
        payload = {
            "version": 1,
            "by_hash": self._by_hash,
            "by_path": self._by_path,
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self._path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("source index save failed (%s): %s", self._path, exc)

    # ---- 哈希（带快表）---------------------------------------------------

    def _path_key(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self._base).as_posix()
        except ValueError:
            return p.resolve().as_posix()

    def source_hash(self, p: Path) -> str:
        """返回源文件内容 sha256；``(mtime,size)`` 未变时走快表跳过读盘。"""
        key = self._path_key(p)
        try:
            st = p.stat()
            sig = (round(st.st_mtime, 3), st.st_size)
        except OSError:
            return _sha256_file(p)

        cached = self._by_path.get(key)
        if cached and cached.get("mtime") == sig[0] and cached.get("size") == sig[1]:
            h = cached.get("hash")
            if h:
                return h

        h = _sha256_file(p)
        self._by_path[key] = {"mtime": sig[0], "size": sig[1], "hash": h}
        return h

    # ---- 查 / 写 ----------------------------------------------------------

    def lookup(self, source_hash: str) -> dict | None:
        return self._by_hash.get(source_hash)

    def record(
        self, source_hash: str, *, stem: str, zipname: str, source_name: str
    ) -> None:
        """登记一条解析结果；先清掉指向同一 zip 文件名的旧 hash 条目（防悬空）。"""
        stale = [
            h
            for h, e in self._by_hash.items()
            if e.get("zip") == zipname and h != source_hash
        ]
        for h in stale:
            del self._by_hash[h]
        self._by_hash[source_hash] = {
            "zip": zipname,
            "stem": stem,
            "source": source_name,
            "parsed_at": _utc_now(),
        }

    def has_hash(self, source_hash: str) -> bool:
        return source_hash in self._by_hash
