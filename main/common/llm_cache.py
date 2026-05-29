"""SHA256-keyed disk cache for LLM chat completion results.

Skips duplicate LLM calls during pipeline re-runs. Cache key derives from
(model, max_tokens, system, user) joined with NUL bytes; on-disk format is
``<root>/<sha256>.json`` with atomic write via tmp + rename. Corrupt or
unreadable entries self-heal by returning None on read.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


class LLMCache:
    """Content-hash disk cache for parsed LLM JSON results."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(*, model: str, max_tokens: int, system: str, user: str) -> str:
        h = hashlib.sha256()
        h.update(model.encode("utf-8"))
        h.update(b"\x00")
        h.update(str(max_tokens).encode("utf-8"))
        h.update(b"\x00")
        h.update(system.encode("utf-8"))
        h.update(b"\x00")
        h.update(user.encode("utf-8"))
        return h.hexdigest()

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int,
    ) -> dict[str, Any] | None:
        path = self._path(self._key(model=model, max_tokens=max_tokens, system=system, user=user))
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def put(
        self,
        *,
        result: dict[str, Any],
        system: str,
        user: str,
        model: str,
        max_tokens: int,
    ) -> None:
        path = self._path(self._key(model=model, max_tokens=max_tokens, system=system, user=user))
        
        
        tmp = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        tmp.replace(path)
